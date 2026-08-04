"""
Rendering layer for PixelVeil redaction. Given a frame and a bounding box,
apply one visual redaction treatment to that box:

    blur_region(frame, bbox)                      -> blur the region
    box_region(frame, bbox, color=(0, 0, 0))      -> cover with a solid box
    fake_data_region(frame, bbox, text, ...)      -> cover, then draw `text`

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
    fill_color=(255, 255, 255),
    text_color=(0, 0, 0),
):
    """Cover `bbox`'s original content and draw the supplied replacement `text`
    over it (in place).

    The region is first filled with `fill_color` (default white) so the
    original content is fully obscured, then `text` is drawn in `text_color`
    (default black) at a font scale chosen to fit inside the box. `text` is the
    already-generated replacement string — this module does not generate it.
    No-op for an invalid/zero-area/off-frame box; if `text` is empty the region
    is still covered (equivalent to a solid box).

    Returns the (same) frame.
    """
    if frame is None or getattr(frame, "size", 0) == 0:
        return frame
    h, w = frame.shape[:2]
    clamped = _clamp_bbox(bbox, w, h)
    if clamped is None:
        return frame
    x, y, bw, bh = clamped

    # Cover the original content first.
    frame[y:y + bh, x:x + bw] = fill_color

    if not text:
        return frame

    # Choose the largest font scale whose rendered text fits within the box
    # (with a small padding margin), down to a legible floor.
    font = cv2.FONT_HERSHEY_SIMPLEX
    thickness = 1
    pad = max(2, bw // 20)
    scale = 2.0
    while scale > 0.3:
        (tw, th), baseline = cv2.getTextSize(text, font, scale, thickness)
        if tw <= bw - 2 * pad and th + baseline <= bh - 2 * pad:
            break
        scale -= 0.1

    (tw, th), baseline = cv2.getTextSize(text, font, scale, thickness)
    # Center the text within the box.
    tx = x + max(pad, (bw - tw) // 2)
    ty = y + (bh + th) // 2
    cv2.putText(
        frame, text, (tx, ty), font, scale, text_color, thickness, cv2.LINE_AA
    )
    return frame
