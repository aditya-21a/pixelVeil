"""
Face detection using MediaPipe. See docs/DECISIONS.md D5 for why MediaPipe
was chosen over dlib/face_recognition.

Public API:
    detect_faces(frame) -> list[bbox]

A ``bbox`` is a 4-tuple ``(x, y, w, h)`` of integer pixel coordinates, where
``(x, y)`` is the top-left corner and ``(w, h)`` are the width and height. All
values are clamped to the frame so downstream code (redactor, zone_manager)
can slice ``frame[y:y+h, x:x+w]`` without bounds checks. Frames are expected in
OpenCV BGR order, the format produced by ``cv2.VideoCapture``.
"""

import cv2
import mediapipe as mp

# Default detection tuning. model_selection=1 is MediaPipe's full-range model
# (out to ~5m), which handles the small webcam picture-in-picture faces common
# in screen recordings better than the short-range model. Both values are
# overridable per call.
_DEFAULT_MODEL_SELECTION = 1
_DEFAULT_MIN_CONFIDENCE = 0.5

# A FaceDetection instance is reusable across frames, so we cache one keyed by
# its construction parameters instead of rebuilding the model every frame.
_detector = None
_detector_key = None


def _get_detector(model_selection, min_confidence):
    """Return a cached MediaPipe FaceDetection, rebuilding it only if the
    tuning parameters change."""
    global _detector, _detector_key
    key = (model_selection, min_confidence)
    if _detector is None or _detector_key != key:
        _detector = mp.solutions.face_detection.FaceDetection(
            model_selection=model_selection,
            min_detection_confidence=min_confidence,
        )
        _detector_key = key
    return _detector


def detect_faces(
    frame,
    min_confidence=_DEFAULT_MIN_CONFIDENCE,
    model_selection=_DEFAULT_MODEL_SELECTION,
):
    """Detect faces in a single BGR video frame.

    Args:
        frame: An OpenCV BGR image (H x W x 3 numpy array).
        min_confidence: Minimum detection confidence in [0.0, 1.0].
        model_selection: 0 for MediaPipe's short-range model, 1 for full-range.

    Returns:
        A list of ``(x, y, w, h)`` integer pixel bounding boxes, one per
        detected face. Empty list if no faces are found.
    """
    if frame is None or getattr(frame, "size", 0) == 0:
        return []

    height, width = frame.shape[:2]
    detector = _get_detector(model_selection, min_confidence)

    # MediaPipe expects RGB; OpenCV frames are BGR.
    results = detector.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    if not results.detections:
        return []

    boxes = []
    for detection in results.detections:
        rel = detection.location_data.relative_bounding_box
        x = int(rel.xmin * width)
        y = int(rel.ymin * height)
        w = int(rel.width * width)
        h = int(rel.height * height)

        # Clamp to frame bounds; MediaPipe can return boxes that spill slightly
        # past the edges for faces near the border.
        x = max(0, min(x, width))
        y = max(0, min(y, height))
        w = max(0, min(w, width - x))
        h = max(0, min(h, height - y))
        if w == 0 or h == 0:
            continue
        boxes.append((x, y, w, h))

    return boxes
