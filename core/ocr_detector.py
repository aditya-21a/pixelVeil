"""
Text detection using RapidOCR on the ONNX Runtime engine. See docs/DECISIONS.md
D17 (which supersedes D6) for why RapidOCR replaced the originally planned
Tesseract/pytesseract backend.

Public API:
    detect_text(frame) -> list[(text, bbox)]

Each item is a ``(text, bbox)`` pair where ``text`` is the recognized string
and ``bbox`` is a 4-tuple ``(x, y, w, h)`` of integer pixel coordinates:
``(x, y)`` is the top-left corner and ``(w, h)`` the width and height. Like
``face_detector.detect_faces``, all values are clamped to the frame so
downstream code (pii_matcher, redactor, video_pipeline) can slice
``frame[y:y+h, x:x+w]`` without bounds checks. Frames are expected in OpenCV
BGR order, the format produced by ``cv2.VideoCapture``.

The RapidOCR backend is an implementation detail. RapidOCR-specific objects
(the ``RapidOCROutput`` result, ``EngineType``, polygon corner arrays) never
leave this module — callers only ever see the normalized ``(text, bbox)`` list.
"""

import numpy as np

from rapidocr import RapidOCR, EngineType

# Minimum recognition confidence for a detected text box to be returned. This
# is deliberately permissive: PixelVeil is a redaction tool, so a false
# negative (real PII left un-redacted) is a privacy failure, while a false
# positive is merely an extra box that pii_matcher.py will discard when no PII
# pattern matches. Bias toward recall — do not raise this to "clean up" output.
_DEFAULT_MIN_CONFIDENCE = 0.5

# A RapidOCR instance loads its ONNX models once and is reusable across frames,
# so we cache a single engine rather than rebuilding it every call. The models
# ship inside the rapidocr wheel, so construction is fully offline — no network
# download at runtime (see DECISIONS.md D17).
_engine = None


def _get_engine():
    """Return a cached RapidOCR engine, constructing it on first use.

    The engine is explicitly pinned to the ONNX Runtime execution engine for
    detection, classification, and recognition so the backend stays predictable
    regardless of what other inference engines happen to be installed.
    """
    global _engine
    if _engine is None:
        _engine = RapidOCR(
            params={
                "Global.log_level": "error",
                "Det.engine_type": EngineType.ONNXRUNTIME,
                "Cls.engine_type": EngineType.ONNXRUNTIME,
                "Rec.engine_type": EngineType.ONNXRUNTIME,
            }
        )
    return _engine


def _poly_to_bbox(poly, width, height):
    """Convert a RapidOCR 4-point polygon to a clamped ``(x, y, w, h)`` box.

    RapidOCR returns each text region as four ``(x, y)`` corner points (which
    can be a slightly rotated quadrilateral). PixelVeil works in axis-aligned
    integer pixel boxes, so we take the bounding rectangle of the polygon and
    clamp it to the frame. Returns ``None`` if the box collapses to zero area.
    """
    pts = np.asarray(poly, dtype=float)
    if pts.size == 0:
        return None

    xs = pts[:, 0]
    ys = pts[:, 1]
    x_min = int(np.floor(xs.min()))
    y_min = int(np.floor(ys.min()))
    x_max = int(np.ceil(xs.max()))
    y_max = int(np.ceil(ys.max()))

    x = max(0, min(x_min, width))
    y = max(0, min(y_min, height))
    w = max(0, min(x_max - x_min, width - x))
    h = max(0, min(y_max - y_min, height - y))
    if w == 0 or h == 0:
        return None
    return (x, y, w, h)


def detect_text(frame, min_confidence=_DEFAULT_MIN_CONFIDENCE):
    """Detect text in a single BGR video frame.

    Args:
        frame: An OpenCV BGR image (H x W x 3 numpy array).
        min_confidence: Minimum per-box recognition confidence in [0.0, 1.0].

    Returns:
        A list of ``(text, (x, y, w, h))`` pairs, one per detected text region,
        with boxes clamped to the frame. Empty list if the frame is empty/invalid
        or no text is found.
    """
    if frame is None or getattr(frame, "size", 0) == 0:
        return []

    height, width = frame.shape[:2]
    engine = _get_engine()

    # RapidOCR accepts a BGR numpy array directly (it handles colour conversion
    # internally), so no cv2.cvtColor is needed here.
    result = engine(frame)

    # An empty result is falsy and carries None for txts/boxes/scores. Guard on
    # all three so a malformed/partial result can't raise here.
    if not result:
        return []
    texts = getattr(result, "txts", None)
    boxes = getattr(result, "boxes", None)
    scores = getattr(result, "scores", None)
    if texts is None or boxes is None:
        return []

    detections = []
    for i, text in enumerate(texts):
        if text is None:
            continue
        text = str(text).strip()
        if not text:
            continue

        # Drop low-confidence recognitions when a score is available; if scores
        # are missing for any reason, keep the box (bias toward recall).
        if scores is not None and i < len(scores) and scores[i] is not None:
            if scores[i] < min_confidence:
                continue

        if i >= len(boxes):
            continue
        bbox = _poly_to_bbox(boxes[i], width, height)
        if bbox is None:
            continue

        detections.append((text, bbox))

    return detections
