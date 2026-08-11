"""
Face detection backends for PixelVeil.

Two backends are provided, selected by ``compute_device``:

    MediaPipe (CPU-only)
        The original backend (DECISIONS.md D5). Always available, no model
        file needed (models ship inside the mediapipe wheel). Used when
        ``compute_device == "cpu"`` or when the ONNX backend is unavailable.

    YuNet via ORT (CPU or CUDA)
        A lightweight ONNX face detector (``face_detection_yunet_2023mar.onnx``,
        227 KB) running through ONNX Runtime. Used when
        ``compute_device == "cuda"`` or when ``compute_device == "auto"`` and
        CUDA is validated by device_manager. YuNet detects angled/partial faces
        that MediaPipe misses, improving privacy recall (verified benchmark
        2026-08-11, see docs/development-log.md).

        **License:** MIT — Copyright (c) 2020 Shiqi Yu <shiqi.yu@gmail.com>
        Source: https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet
        Commercially usable — see assets/models/LICENSE_yunet for the exact
        license text.

Public API (UNCHANGED — all callers see the same contract):
    detect_faces(frame, min_confidence=0.5, model_selection=1) -> list[bbox]
    DEFAULT_MIN_CONFIDENCE

A ``bbox`` is a 4-tuple ``(x, y, w, h)`` of integer pixel coordinates, where
``(x, y)`` is the top-left corner and ``(w, h)`` are the width and height.
All values are clamped to the frame so downstream code (redactor,
zone_manager) can slice ``frame[y:y+h, x:x+w]`` without bounds checks.
Frames are expected in OpenCV BGR order.

Device routing:
    The active backend is determined once at module initialisation time by
    ``set_compute_device()``, which is called by video_pipeline.process_video()
    before the frame loop. Calling ``detect_faces()`` without ever calling
    ``set_compute_device()`` falls back to MediaPipe for backwards compatibility.

See docs/DECISIONS.md D5 (MediaPipe), D27 (GPU acceleration).
"""

import os
import sys
import logging
from typing import Optional

# Ensure PyTorch CUDA DLLs are visible to ORT (Windows only)
# This must happen BEFORE any ORT session is initialized to prevent deadlocks.
if hasattr(os, "add_dll_directory"):
    try:
        import torch  # noqa: PLC0415
        _torch_lib = os.path.join(os.path.dirname(torch.__file__), "lib")
        if os.path.isdir(_torch_lib):
            os.add_dll_directory(_torch_lib)
    except Exception:  # noqa: BLE001
        pass

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults — exposed publicly so callers (Settings screen) can display them.
# ---------------------------------------------------------------------------
_DEFAULT_MODEL_SELECTION = 1
_DEFAULT_MIN_CONFIDENCE = 0.5
DEFAULT_MIN_CONFIDENCE = _DEFAULT_MIN_CONFIDENCE

# ---------------------------------------------------------------------------
# Model paths — relative to the project root.
# Resolved dynamically so the module works regardless of where Python is
# invoked from.
# ---------------------------------------------------------------------------
_YUNET_MODEL_FILENAME = "face_detection_yunet_2023mar.onnx"
_YUNET_LICENSE_FILENAME = "LICENSE_yunet"

_SCRFD_MODEL_FILENAME = "det_500m.onnx"

def _model_path(filename: str) -> str:
    """Return the absolute path to a model file in assets/models."""
    this_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(this_dir)
    return os.path.join(project_root, "assets", "models", filename)


# ---------------------------------------------------------------------------
# Module-level state — device selection and cached sessions.
# ---------------------------------------------------------------------------
_compute_device: str = "cpu"  # "cpu" or "cuda"
_backend: str = "mediapipe"   # "mediapipe" or "yunet"

# MediaPipe backend cache (keyed by (model_selection, min_confidence))
_mp_detector = None
_mp_detector_key = None

# ONNX backend caches (keyed by device string)
_yunet_session: dict = {}   # {device: ort.InferenceSession}
_scrfd_detector: dict = {}  # {device: core.scrfd.SCRFD}

# YuNet decode constants
_YUNET_INPUT_SIZE = (640, 640)  # (W, H) — model fixed input
_YUNET_STRIDES = [8, 16, 32]


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------

def set_compute_device(device: str) -> None:
    """Configure which backend and device detect_faces() uses.

    Called by video_pipeline.process_video() before the frame loop.
    Can be called multiple times — changes are applied from the next
    detect_faces() call onwards (sessions are lazily created on first use).

    Args:
        device: "auto", "cpu", "cuda", "scrfd_cpu", "scrfd_cuda", "yunet_cpu", "yunet_cuda", "mediapipe_cpu".
            "auto" — use SCRFD CUDA if possible, else SCRFD CPU.
            "cpu"  — use SCRFD CPU.
            "cuda" — use SCRFD CUDA, raising RuntimeError if unavailable.
    """
    global _compute_device, _backend
    device = device.lower().strip()
    
    if device in ("auto", "cpu", "cuda"):
        from core.device_manager import get_compute_device
        resolved = get_compute_device(device)
        device = f"scrfd_{resolved}"
        
    if device in ("scrfd_cpu", "scrfd_cuda"):
        model_path = _model_path(_SCRFD_MODEL_FILENAME)
        if os.path.isfile(model_path):
            _backend = "scrfd"
            _compute_device = "cuda" if "cuda" in device else "cpu"
        else:
            logger.warning("SCRFD model not found at %s — falling back to MediaPipe CPU.", model_path)
            _backend = "mediapipe"
            _compute_device = "cpu"
            
    elif device in ("yunet_cuda", "yunet_cpu"):
        model_path = _model_path(_YUNET_MODEL_FILENAME)
        if os.path.isfile(model_path):
            _backend = "yunet"
            _compute_device = "cuda" if "cuda" in device else "cpu"
        else:
            logger.warning("YuNet model not found at %s — falling back to MediaPipe CPU.", model_path)
            _backend = "mediapipe"
            _compute_device = "cpu"
            
    elif device == "mediapipe_cpu":
        _backend = "mediapipe"
        _compute_device = "cpu"
        
    else:
        raise ValueError(f"Unknown device configuration: {device!r}")


def get_active_backend() -> str:
    """Return 'mediapipe', 'yunet', or 'scrfd' — the backend currently in use."""
    return _backend


def get_active_model_name() -> str:
    """Return a display-friendly name of the active model."""
    if _backend == "scrfd":
        return "SCRFD-500M"
    elif _backend == "yunet":
        return "YuNet"
    return "MediaPipe"


def get_active_provider() -> str:
    """Return the ORT ExecutionProvider name or 'MediaPipe' for diagnostics."""
    if _backend in ("yunet", "scrfd"):
        return "CUDAExecutionProvider" if _compute_device == "cuda" else "CPUExecutionProvider"
    return "MediaPipe"


# ---------------------------------------------------------------------------
# MediaPipe backend
# ---------------------------------------------------------------------------

def _get_mp_detector(model_selection: int, min_confidence: float):
    """Return a cached MediaPipe FaceDetection, rebuilding on parameter change."""
    global _mp_detector, _mp_detector_key
    import mediapipe as mp
    key = (model_selection, min_confidence)
    if _mp_detector is None or _mp_detector_key != key:
        _mp_detector = mp.solutions.face_detection.FaceDetection(
            model_selection=model_selection,
            min_detection_confidence=min_confidence,
        )
        _mp_detector_key = key
    return _mp_detector


def _detect_mediapipe(frame, min_confidence: float, model_selection: int) -> list:
    """Run face detection using MediaPipe."""
    height, width = frame.shape[:2]
    detector = _get_mp_detector(model_selection, min_confidence)
    results = detector.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    if not results.detections:
        return []
    boxes = []
    for det in results.detections:
        rel = det.location_data.relative_bounding_box
        x = int(rel.xmin * width)
        y = int(rel.ymin * height)
        w = int(rel.width * width)
        h = int(rel.height * height)
        x = max(0, min(x, width));   y = max(0, min(y, height))
        w = max(0, min(w, width - x)); h = max(0, min(h, height - y))
        if w > 0 and h > 0:
            boxes.append((x, y, w, h))
    return boxes


# ---------------------------------------------------------------------------
# YuNet ORT backend
# ---------------------------------------------------------------------------

def _get_ort_session(model_path: str, device: str):
    """Return a cached ORT InferenceSession, keyed by device.

    Sessions are created once (not per frame).
    """
    import onnxruntime as ort  # noqa: PLC0415
    sess_opts = ort.SessionOptions()
    sess_opts.log_severity_level = 3  # ERROR

    if device == "cuda":
        providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        provider_options = [{"device_id": 0}, {}]
    else:
        providers = ["CPUExecutionProvider"]
        provider_options = [{}]

    session = ort.InferenceSession(
        model_path,
        providers=providers,
        provider_options=provider_options,
        sess_options=sess_opts,
    )
    active = session.get_providers()
    if device == "cuda" and "CUDAExecutionProvider" not in active:
        logger.warning(
            "ORT silently fell back to CPU (active providers: %s). "
            "Check CUDA/cuDNN compatibility.",
            active,
        )
    return session


def _get_yunet_session(device: str):
    global _yunet_session
    if device in _yunet_session:
        return _yunet_session[device]

    model_path = _model_path(_YUNET_MODEL_FILENAME)
    if not os.path.isfile(model_path):
        raise FileNotFoundError(f"YuNet model not found at {model_path!r}.")

    session = _get_ort_session(model_path, device)
    _yunet_session[device] = session
    logger.debug("YuNet ORT session created for device=%s", device)
    return session


def _preprocess_yunet(frame):
    """Resize and convert a BGR frame to the YuNet ONNX input tensor."""
    W, H = _YUNET_INPUT_SIZE
    resized = cv2.resize(frame, (W, H))
    # BGR -> NCHW float32
    blob = resized.astype(np.float32).transpose(2, 0, 1)[np.newaxis]
    return blob


def _decode_yunet(outputs, orig_w: int, orig_h: int,
                  score_thresh: float, nms_thresh: float = 0.3) -> list:
    """Decode YuNet's multi-scale outputs into clamped (x, y, w, h) boxes.

    YuNet produces 12 output tensors (cls/obj/bbox/kps at strides 8/16/32).
    We use cls, obj, and bbox only. Scores are the geometric mean of cls and
    obj scores; boxes are decoded from anchor-free offsets; NMS is applied
    with cv2.dnn.NMSBoxes.
    """
    # outputs order: cls_8, cls_16, cls_32, obj_8, obj_16, obj_32,
    #                bbox_8, bbox_16, bbox_32, kps_8, kps_16, kps_32
    cls_outs  = [outputs[0], outputs[1], outputs[2]]
    obj_outs  = [outputs[3], outputs[4], outputs[5]]
    bbox_outs = [outputs[6], outputs[7], outputs[8]]

    IH, IW = _YUNET_INPUT_SIZE[1], _YUNET_INPUT_SIZE[0]
    scale_x = orig_w / IW
    scale_y = orig_h / IH

    all_boxes  = []
    all_scores = []

    for stride, cls_o, obj_o, bbox_o in zip(
        _YUNET_STRIDES, cls_outs, obj_outs, bbox_outs
    ):
        # Score: geometric mean of class and objectness probabilities
        scores = (cls_o[0, :, 0] * obj_o[0, :, 0]) ** 0.5
        bboxes = bbox_o[0]   # [N, 4]

        fH = IH // stride
        fW = IW // stride

        for i, sc in enumerate(scores):
            if sc < score_thresh:
                continue
            r = i // fW
            c = i % fW
            cx = (c + 0.5 + bboxes[i, 0]) * stride
            cy = (r + 0.5 + bboxes[i, 1]) * stride
            bw = math.exp(float(bboxes[i, 2])) * stride
            bh = math.exp(float(bboxes[i, 3])) * stride
            x1 = (cx - bw / 2) * scale_x
            y1 = (cy - bh / 2) * scale_y
            all_boxes.append([x1, y1, bw * scale_x, bh * scale_y])
            all_scores.append(float(sc))

    if not all_boxes:
        return []

    indices = cv2.dnn.NMSBoxes(all_boxes, all_scores, score_thresh, nms_thresh)
    if len(indices) == 0:
        return []

    results = []
    for idx in indices.flatten():
        x, y, w, h = all_boxes[idx]
        x = max(0, min(int(round(x)), orig_w - 1))
        y = max(0, min(int(round(y)), orig_h - 1))
        w = max(1, min(int(round(w)), orig_w - x))
        h = max(1, min(int(round(h)), orig_h - y))
        results.append((x, y, w, h))
    return results


def _detect_yunet(frame, min_confidence: float) -> list:
    """Run face detection using YuNet via ORT."""
    height, width = frame.shape[:2]
    session = _get_yunet_session(_compute_device)
    blob = _preprocess_yunet(frame)
    outputs = session.run(None, {"input": blob})
    return _decode_yunet(outputs, width, height, score_thresh=min_confidence)

# ---------------------------------------------------------------------------
# SCRFD Backend
# ---------------------------------------------------------------------------

def _get_scrfd_detector(device: str):
    global _scrfd_detector
    if device in _scrfd_detector:
        return _scrfd_detector[device]

    model_path = _model_path(_SCRFD_MODEL_FILENAME)
    if not os.path.isfile(model_path):
        raise FileNotFoundError(f"SCRFD model not found at {model_path!r}.")

    session = _get_ort_session(model_path, device)
    from core.scrfd import SCRFD
    detector = SCRFD(model_file=model_path, session=session)
    _scrfd_detector[device] = detector
    logger.debug("SCRFD detector created for device=%s", device)
    return detector

def _detect_scrfd(frame, min_confidence: float) -> list:
    """Run face detection using SCRFD via ORT."""
    height, width = frame.shape[:2]
    detector = _get_scrfd_detector(_compute_device)
    
    # max_num=0 means return all faces. input_size fixes the inference resolution.
    # SCRFD supports dynamic sizing but a fixed 640x640 is standard for the 500M model.
    bboxes_with_scores, _ = detector.detect(frame, input_size=(640, 640), max_num=0)
    
    results = []
    if bboxes_with_scores is not None and len(bboxes_with_scores) > 0:
        for box in bboxes_with_scores:
            score = float(box[4])
            if score < min_confidence:
                continue
            x = max(0, min(int(round(box[0])), width - 1))
            y = max(0, min(int(round(box[1])), height - 1))
            w = max(1, min(int(round(box[2] - box[0])), width - x))
            h = max(1, min(int(round(box[3] - box[1])), height - y))
            results.append((x, y, w, h))
            
    return results


# ---------------------------------------------------------------------------
# Public API (unchanged contract)
# ---------------------------------------------------------------------------

def detect_faces(
    frame,
    min_confidence: float = _DEFAULT_MIN_CONFIDENCE,
    model_selection: int = _DEFAULT_MODEL_SELECTION,
) -> list:
    """Detect faces in a single BGR video frame.

    Dispatches to the active backend (MediaPipe or YuNet) as configured by
    the most recent call to ``set_compute_device()``. When no device has been
    configured, MediaPipe is used (backwards-compatible default).

    Args:
        frame: An OpenCV BGR image (H x W x 3 numpy array).
        min_confidence: Minimum detection confidence in [0.0, 1.0].
            Interpreted as the score threshold for both backends.
        model_selection: 0 (short-range) or 1 (full-range). Used by MediaPipe
            only; ignored by YuNet (it has no equivalent parameter).

    Returns:
        A list of ``(x, y, w, h)`` integer pixel bounding boxes, one per
        detected face. Empty list if no faces are found.
    """
    if frame is None or getattr(frame, "size", 0) == 0:
        return []

    if _backend == "yunet":
        return _detect_yunet(frame, min_confidence)
    elif _backend == "scrfd":
        return _detect_scrfd(frame, min_confidence)
    else:
        return _detect_mediapipe(frame, min_confidence, model_selection)
