"""
Rendering layer for PixelVeil redaction. Given a frame and a bounding box,
apply one visual redaction treatment to that box:

    blur_region(frame, bbox)                      -> blur the region
    box_region(frame, bbox, color=(0, 0, 0))      -> cover with a solid box
    fake_data_region(frame, bbox, text, ...)      -> cover, then draw `text`
    estimate_text_style(frame, bbox)              -> extract visual properties
    inpaint_region(frame, mask, method)           -> fill using inpainting

This module is **rendering only**. It does not detect faces, run OCR, match
PII, generate fake data, or process videos — callers (ultimately
video_pipeline.py) decide *what* to redact and *which* treatment to use, and
pass the already-chosen bbox and (for fake-data) the already-generated
replacement string. Fake-data strings come from utils/fake_data.py, which is
the caller's concern, not this module's.

Bounding boxes use the same convention as face_detector/ocr_detector:
``(x, y, w, h)`` integer pixels, ``(x, y)`` top-left. Boxes are clamped to the
frame here, so a box at the edge or partially out of frame is handled safely; a
zero-area or fully off-frame box is a no-op (the frame is returned unchanged).
Frames are OpenCV BGR numpy arrays and are modified in place and returned.

Style estimation (`estimate_text_style`) must be called BEFORE the original
pixels are destroyed by removal/inpainting. The returned style dict can then
be passed to `fake_data_region` to render replacement text that approximately
matches the source appearance.
"""

import cv2
import numpy as np


def _clamp_bbox(bbox, width, height):
    """Clamp ``(x, y, w, h)`` to the frame. Return a clamped ``(x, y, w, h)``
    with positive area, or ``None`` if the box is invalid or collapses to zero
    area inside the frame (caller should then no-op)."""
    if bbox is None or len(bbox) != 4:
        return None
    x, y, w, h = (int(v) for v in bbox)
    if w <= 0 or h <= 0:
        return None

    # Convert to corner coordinates, clamp both corners to the frame.
    x0 = max(0, min(x, width))
    y0 = max(0, min(y, height))
    x1 = max(0, min(x + w, width))
    y1 = max(0, min(y + h, height))

    cw = x1 - x0
    ch = y1 - y0
    if cw <= 0 or ch <= 0:
        return None
    return (x0, y0, cw, ch)


def estimate_text_style(frame, bbox):
    """Extract visual properties from a text region before removal.

    Must be called BEFORE the original pixels are destroyed. Estimates foreground
    (text) color, background color, text height, vertical placement, and original
    value width from the source region. These properties can guide fake-data
    rendering to approximately match the source appearance.

    Args:
        frame: OpenCV BGR numpy array.
        bbox: (x, y, w, h) bounding box of the text region.

    Returns:
        A dict with estimated style properties:
        - "text_color": BGR 3-tuple, estimated foreground/text color
        - "bg_color": BGR 3-tuple, estimated local background color
        - "text_height": int, approximate text height in pixels
        - "baseline_offset": int, approximate vertical text placement offset
        - "width": int, original region width (for alignment reference)

        Returns None if the bbox is invalid/off-frame or frame is empty.

    Example:
        >>> style = estimate_text_style(frame, (100, 50, 200, 30))
        >>> if style:
        ...     # Use style["text_color"] and style["bg_color"] when rendering
    """
    if frame is None or getattr(frame, "size", 0) == 0:
        return None
    h, w = frame.shape[:2]
    clamped = _clamp_bbox(bbox, w, h)
    if clamped is None:
        return None
    x, y, bw, bh = clamped

    roi = frame[y:y + bh, x:x + bw]
    if roi.size == 0:
        return None

    # Estimate foreground (text) and background colors using clustering.
    # Text is typically a minority of pixels (stroke pixels vs background/fill).
    # We use k-means with k=2 to split the region into two color clusters,
    # then pick the cluster with fewer pixels as foreground (text).
    pixels = roi.reshape(-1, 3).astype(np.float32)
    if len(pixels) < 2:
        # Degenerate case: use the single color for both
        avg = np.mean(pixels, axis=0) if len(pixels) > 0 else np.array([128, 128, 128])
        return {
            "text_color": tuple(int(c) for c in avg),
            "bg_color": tuple(int(c) for c in avg),
            "text_height": bh,
            "baseline_offset": 0,
            "width": bw,
        }

    # k-means clustering to find two dominant colors
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
    _, labels, centers = cv2.kmeans(
        pixels, 2, None, criteria, 3, cv2.KMEANS_PP_CENTERS
    )

    # Count pixels in each cluster
    counts = [np.sum(labels == i) for i in range(2)]
    # Foreground is the minority cluster (text strokes), background is majority
    fg_idx = 0 if counts[0] < counts[1] else 1
    bg_idx = 1 - fg_idx

    text_color = tuple(int(c) for c in centers[fg_idx])
    bg_color = tuple(int(c) for c in centers[bg_idx])

    # Estimate text height: look for horizontal runs of foreground pixels.
    # The height is approximated as the median height of such runs.
    # This is a heuristic; exact glyph height would require font information.
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    # Binarize with Otsu, then normalize polarity so the *text* pixels are the
    # white (255) foreground that findContours(RETR_EXTERNAL) will trace. In a
    # text-line region the ink is the minority of pixels (strokes vs. fill),
    # matching the minority-cluster == foreground assumption used for the colors
    # above, so we invert whenever white is the majority. A brightness
    # comparison of the two cluster centers gets this backwards for BOTH
    # polarities (it made the contour pass trace the background blob, so
    # text_height collapsed to the full box height regardless of the real glyph
    # size); the minority rule is polarity-agnostic and self-consistent.
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if np.count_nonzero(binary) * 2 > binary.size:
        binary = cv2.bitwise_not(binary)

    # Find contours to estimate text structure
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if contours:
        heights = [cv2.boundingRect(c)[3] for c in contours if cv2.contourArea(c) > 3]
        if heights:
            text_height = int(np.median(heights))
        else:
            text_height = max(bh // 2, 10)
    else:
        # Fallback: assume text is roughly 60-70% of the box height
        text_height = max(int(bh * 0.65), 10)

    # Baseline offset: text typically sits slightly above the bottom of the box
    # Estimate as a small fraction of box height
    baseline_offset = max(int(bh * 0.15), 0)

    return {
        "text_color": text_color,
        "bg_color": bg_color,
        "text_height": text_height,
        "baseline_offset": baseline_offset,
        "width": bw,
    }


def inpaint_region(frame, mask, method="telea"):
    """Fill masked pixels using classical OpenCV inpainting.

    Args:
        frame: OpenCV BGR numpy array.
        mask: Single-channel uint8 numpy array, same height/width as frame.
            Non-zero pixels mark the region to inpaint (remove and reconstruct).
        method: "telea" or "ns" (Navier-Stokes). Both are classical lightweight
            algorithms already in OpenCV; no new dependencies.

    Returns:
        The inpainted frame (modified in place and returned). If frame or mask
        is invalid, returns frame unchanged.

    Raises:
        ValueError: if method is not "telea" or "ns".
    """
    if method not in ("telea", "ns"):
        raise ValueError(f"method must be 'telea' or 'ns', got {method!r}")

    if frame is None or getattr(frame, "size", 0) == 0:
        return frame
    if mask is None or getattr(mask, "size", 0) == 0:
        return frame

    h, w = frame.shape[:2]
    if mask.shape[:2] != (h, w):
        return frame

    # Map method name to OpenCV constant
    flag = cv2.INPAINT_TELEA if method == "telea" else cv2.INPAINT_NS

    # Inpaint radius: small for local PII text removal (3-5 pixels typically sufficient)
    inpaint_radius = 3

    # cv2.inpaint modifies a copy; we apply it back to frame for in-place semantics
    inpainted = cv2.inpaint(frame, mask, inpaint_radius, flag)
    np.copyto(frame, inpainted)
    return frame


def blur_region(frame, bbox):
    """Blur the region of `frame` covered by `bbox` (in place).

    Uses a Gaussian blur with a kernel scaled to the region size, so the
    redaction is strong enough that text/faces are unreadable regardless of box
    dimensions. No-op for an invalid/zero-area/off-frame box.

    Returns the (same) frame.
    """
    if frame is None or getattr(frame, "size", 0) == 0:
        return frame
    h, w = frame.shape[:2]
    clamped = _clamp_bbox(bbox, w, h)
    if clamped is None:
        return frame
    x, y, bw, bh = clamped

    roi = frame[y:y + bh, x:x + bw]
    # Kernel scaled to region; must be a positive odd integer.
    k = max(bw, bh) // 2
    if k % 2 == 0:
        k += 1
    k = max(k, 3)
    frame[y:y + bh, x:x + bw] = cv2.GaussianBlur(roi, (k, k), 0)
    return frame


def _get_face_mask_and_box(frame_shape, bbox):
    """
    Given a face detector bbox (x, y, w, h) and frame shape (H, W),
    compute an expanded rounded/oval mask that conservatively covers
    the forehead, cheeks, and chin.
    
    Returns:
        (clamped_roi_bbox, mask_roi)
        - clamped_roi_bbox: (x0, y0, cw, ch) the region of the frame
        - mask_roi: 2D numpy array (float32, 0.0 to 1.0) of shape (ch, cw)
          representing the alpha mask.
    """
    if bbox is None or len(bbox) != 4:
        return None, None
    x, y, w, h = (int(v) for v in bbox)
    if w <= 0 or h <= 0:
        return None, None

    H, W = frame_shape[:2]
    
    # Conservatively expand bbox to cover forehead, cheeks, chin.
    # Typical face detector: y=eyebrows, y+h=mouth, x/w tight to eyes/cheeks.
    x_min = x - 0.25 * w
    x_max = x + w + 0.25 * w
    y_min = y - 0.45 * h
    y_max = y + h + 0.15 * h
    
    cx = (x_min + x_max) / 2.0
    cy = (y_min + y_max) / 2.0
    axes_x = (x_max - x_min) / 2.0
    axes_y = (y_max - y_min) / 2.0
    
    # Bounding box of the ellipse, padded slightly for anti-aliasing/feathering.
    # We add generous padding to accommodate the feathering radius.
    feather_k = max(3, int(axes_x * 0.15))
    if feather_k % 2 == 0:
        feather_k += 1
    pad = feather_k + 2
    
    roi_x_min = int(np.floor(x_min)) - pad
    roi_x_max = int(np.ceil(x_max)) + pad
    roi_y_min = int(np.floor(y_min)) - pad
    roi_y_max = int(np.ceil(y_max)) + pad
    
    # Clamp roi to frame boundaries
    c_x_min = max(0, min(roi_x_min, W))
    c_x_max = max(0, min(roi_x_max, W))
    c_y_min = max(0, min(roi_y_min, H))
    c_y_max = max(0, min(roi_y_max, H))
    
    cw = c_x_max - c_x_min
    ch = c_y_max - c_y_min
    
    if cw <= 0 or ch <= 0:
        return None, None
        
    mask_roi_u8 = np.zeros((ch, cw), dtype=np.uint8)
    
    # Draw the ellipse into the mask ROI.
    rel_cx = int(round(cx - c_x_min))
    rel_cy = int(round(cy - c_y_min))
    axes = (max(1, int(round(axes_x))), max(1, int(round(axes_y))))
    
    # cv2.LINE_AA gives a 1-pixel soft boundary, inside is 100% opaque.
    cv2.ellipse(mask_roi_u8, (rel_cx, rel_cy), axes, 0, 0, 360, 255, -1, cv2.LINE_AA)
    
    # Feather OUTSIDE the core to make the boundary even smoother without compromising the core.
    blurred_u8 = cv2.GaussianBlur(mask_roi_u8, (feather_k, feather_k), 0)
    # maximum ensures the protected core (255) remains exactly 255.
    final_mask_u8 = np.maximum(mask_roi_u8, blurred_u8)
    
    mask_roi = final_mask_u8.astype(np.float32) / 255.0
    return (c_x_min, c_y_min, cw, ch), mask_roi


def redact_face(frame, bbox, method="blur", blur_intensity="medium"):
    """
    Apply a privacy-first, face-following redaction mask.
    
    Args:
        frame: OpenCV BGR numpy array.
        bbox: (x, y, w, h) original detector bounding box.
        method: "blur" or "pixelate".
        blur_intensity: "low", "medium", "high".
        
    Returns:
        The (same) frame, modified in place.
    """
    if frame is None or getattr(frame, "size", 0) == 0:
        return frame
        
    roi_data = _get_face_mask_and_box(frame.shape, bbox)
    if roi_data[0] is None:
        return frame
        
    (rx, ry, rw, rh), mask = roi_data
    roi = frame[ry:ry+rh, rx:rx+rw]
    
    effect = np.empty_like(roi)
    
    if method == "blur":
        w = int(bbox[2])
        if blur_intensity == "low":
            k = max(3, w // 8)
        elif blur_intensity == "high":
            k = max(11, w // 2)
        else:
            k = max(7, w // 4)
            
        if k % 2 == 0:
            k += 1
        effect = cv2.GaussianBlur(roi, (k, k), 0)
        
    elif method == "pixelate":
        # Adaptive pixelation grid:
        # Smaller faces receive a coarse mosaic (fewer cells).
        # Larger faces receive more cells, but strong anonymity is maintained.
        # Cells scale sublinearly with expanded ROI width (rw).
        cells_x = max(3, int(rw ** 0.35))
        # Keep approximately square cells based on ROI aspect ratio
        cells_y = max(3, int(cells_x * (rh / rw)))

        down_w = min(rw, cells_x)
        down_h = min(rh, cells_y)
        
        # Quantitative Diagnostics
        pixels_per_cell = rw / max(1, down_w)
        privacy_floor = "APPLIED" if int(rw ** 0.35) < 3 else "NOT_APPLIED"
        print(f"diagnostic: face_width={int(bbox[2])} roi_width={rw} grid={down_w}x{down_h} pixels_per_cell={pixels_per_cell:.1f} privacy_floor={privacy_floor}")

        # INTER_AREA for downsampling (averaging pixels)
        small = cv2.resize(roi, (down_w, down_h), interpolation=cv2.INTER_AREA)
        # INTER_NEAREST for upsampling (blocky pixelation)
        effect = cv2.resize(small, (rw, rh), interpolation=cv2.INTER_NEAREST)

    else:
        effect = roi
        
    mask_3d = mask[:, :, np.newaxis]
    blended = (mask_3d * effect) + ((1.0 - mask_3d) * roi)
    
    frame[ry:ry+rh, rx:rx+rw] = blended.astype(np.uint8)
    return frame


def box_region(frame, bbox, color=(0, 0, 0)):
    """Cover the region of `frame` covered by `bbox` with a solid `color` box
    (in place). `color` is a BGR 3-tuple, default black. No-op for an
    invalid/zero-area/off-frame box.

    Returns the (same) frame.
    """
    if frame is None or getattr(frame, "size", 0) == 0:
        return frame
    h, w = frame.shape[:2]
    clamped = _clamp_bbox(bbox, w, h)
    if clamped is None:
        return frame
    x, y, bw, bh = clamped
    frame[y:y + bh, x:x + bw] = color
    return frame


def fake_data_region(
    frame,
    bbox,
    text,
    fill_color=None,
    text_color=None,
    inpaint_method=None,
    style=None,
):
    """Cover `bbox`'s original content and draw the supplied replacement `text`
    over it (in place).

    The original content is removed using inpainting (default) or solid fill.
    Replacement text is drawn using source-estimated or explicitly-supplied
    colors and sizing. `text` is the already-generated replacement string —
    this module does not generate it.

    Args:
        frame: OpenCV BGR numpy array.
        bbox: (x, y, w, h) bounding box of the region to replace.
        text: Replacement text string (already generated by the caller).
        fill_color: Optional BGR 3-tuple for solid-fill fallback. When None and
            `style` is provided, uses style["bg_color"]. Default white (255,255,255)
            is used only when both are None.
        text_color: Optional BGR 3-tuple for text rendering. When None and
            `style` is provided, uses style["text_color"]. Default black (0,0,0).
        inpaint_method: "telea" or "ns" for background reconstruction, or None
            to skip inpainting and use solid fill only (backward-compatible).
        style: Optional dict from estimate_text_style() with keys:
            - "text_color": estimated foreground color
            - "bg_color": estimated background color
            - "text_height": approximate text height in pixels
            - "baseline_offset": vertical placement offset
            - "width": original region width
            When provided, these guide rendering to approximately match the source.

    Returns:
        The (same) frame, modified in place.

    Notes:
        - No-op for an invalid/zero-area/off-frame box.
        - If `text` is empty the region is still covered/inpainted.
        - Backward compatibility: calling without style/inpaint_method produces
          the old solid-white-fill + black-text behavior.
    """
    if frame is None or getattr(frame, "size", 0) == 0:
        return frame
    h, w = frame.shape[:2]
    clamped = _clamp_bbox(bbox, w, h)
    if clamped is None:
        return frame
    x, y, bw, bh = clamped

    # Resolve colors from style or explicit args or defaults
    if text_color is None:
        if style and "text_color" in style:
            text_color = style["text_color"]
        else:
            text_color = (0, 0, 0)  # default black

    if fill_color is None:
        if style and "bg_color" in style:
            fill_color = style["bg_color"]
        else:
            fill_color = (255, 255, 255)  # default white

    # Remove original content
    if inpaint_method:
        # Validate method before building mask
        if inpaint_method not in ("telea", "ns"):
            raise ValueError(
                f"inpaint_method must be 'telea' or 'ns', got {inpaint_method!r}"
            )

        # Create a mask for the region to inpaint
        mask = np.zeros((h, w), dtype=np.uint8)
        # Add a small safety margin around the bbox to ensure all glyph pixels
        # (including antialiasing) are covered. The margin is bounded and
        # proportional to box dimensions.
        margin = min(max(2, min(bw, bh) // 15), 5)
        x_safe = max(0, x - margin)
        y_safe = max(0, y - margin)
        x_end = min(w, x + bw + margin)
        y_end = min(h, y + bh + margin)
        mask[y_safe:y_end, x_safe:x_end] = 255

        # Inpaint to reconstruct background
        try:
            inpaint_region(frame, mask, method=inpaint_method)
        except cv2.error:
            # Fallback to solid fill if inpainting fails (but not for ValueError)
            frame[y:y + bh, x:x + bw] = fill_color
    else:
        # Solid fill (backward-compatible fallback)
        frame[y:y + bh, x:x + bw] = fill_color

    if not text:
        return frame

    # Render replacement text
    font = cv2.FONT_HERSHEY_SIMPLEX
    thickness = 1

    # If style is provided, use it to guide text sizing and placement
    if style and "text_height" in style:
        target_height = style["text_height"]
        # Choose an initial scale to approximately match the estimated text
        # height. FONT_HERSHEY_SIMPLEX renders a cap height of ~22 px at
        # scale 1.0 (measured via cv2.getTextSize), and estimate_text_style()
        # reports the source glyph height in px, so scale ≈ target / 22 lands
        # the replacement near the source size. (A larger divisor such as 40
        # under-sizes the text by ~40%.) Width-fitting below only ever shrinks
        # this, so start from the height match.
        scale = target_height / 22.0
        scale = max(0.3, min(scale, 3.0))  # reasonable bounds

        # Refine scale to fit within box width
        pad = max(2, bw // 20)
        for _ in range(5):  # iterative refinement
            (tw, th), baseline = cv2.getTextSize(text, font, scale, thickness)
            if tw <= bw - 2 * pad:
                break
            scale -= 0.1
            if scale < 0.3:
                break
        scale = max(0.3, scale)

        # Placement: use baseline_offset from style
        (tw, th), baseline = cv2.getTextSize(text, font, scale, thickness)
        tx = x + max(pad, (bw - tw) // 2)

        # Vertical: align based on style's baseline_offset
        baseline_offset = style.get("baseline_offset", int(bh * 0.15))
        ty = y + bh - baseline_offset - baseline
    else:
        # Fallback: auto-scale to fit (backward-compatible)
        pad = max(2, bw // 20)
        scale = 2.0
        while scale > 0.3:
            (tw, th), baseline = cv2.getTextSize(text, font, scale, thickness)
            if tw <= bw - 2 * pad and th + baseline <= bh - 2 * pad:
                break
            scale -= 0.1

        (tw, th), baseline = cv2.getTextSize(text, font, scale, thickness)
        tx = x + max(pad, (bw - tw) // 2)
        ty = y + (bh + th) // 2

    cv2.putText(
        frame, text, (tx, ty), font, scale, text_color, thickness, cv2.LINE_AA
    )
    return frame
