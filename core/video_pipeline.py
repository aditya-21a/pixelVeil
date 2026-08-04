"""
Orchestrator — ties together face_detector, ocr_detector, pii_matcher,
zone_manager, and redactor to process a full video file.

See docs/architecture.md section 6 (Data Flow) for the exact per-frame
sequence, and docs/DECISIONS.md D8 for why ffmpeg muxing is used for the
final output rather than OpenCV's VideoWriter alone.

Public API:
    process_video(input_path, output_path, mode="blur", zones=None,
                  ocr_sample_rate=1, progress_callback=None) -> dict

This module is orchestration only: it reads frames, calls each component's
existing public API, and writes frames back. It contains no face-detection,
OCR, PII-matching, redaction-drawing, fake-data-generation, or zone logic of
its own — every such operation is delegated to the owning module.

Scope note (this task): OCR runs on every frame and the output is the
OpenCV-written intermediate video (video only). Two follow-on TASKS.md items
are deliberately NOT implemented here and are documented as deferred:
  * OCR every-N-frame sampling + bbox persistence between samples
    (architecture.md 6.4/6.5, 7) — `ocr_sample_rate` is accepted for API
    stability but is not yet honored.
  * ffmpeg re-mux of the original audio track (architecture.md 6.9, D8).
"""

import cv2

from core import face_detector
from core import ocr_detector
from core import pii_matcher
from core import redactor
from core.zone_manager import ZoneManager
from utils import fake_data

# OCR text is classified to a PII type in this order. EMAIL and IP are checked
# before CARD/PHONE because their punctuation makes them unambiguous, whereas
# the digit-oriented card/phone patterns are broader; checking the specific
# shapes first avoids an IP or email being mis-typed as a phone number. The
# type string is what utils.fake_data.generate() expects.
_PII_CLASSIFIERS = (
    ("EMAIL", pii_matcher.is_email),
    ("IP", pii_matcher.is_ipv4),
    ("CARD", pii_matcher.is_card),
    ("PHONE", pii_matcher.is_phone),
)


def _classify_pii(text):
    """Return the PII type string for `text`, or None if it isn't PII."""
    for pii_type, matcher in _PII_CLASSIFIERS:
        if matcher(text):
            return pii_type
    return None


def process_video(
    input_path,
    output_path,
    mode="blur",
    zones=None,
    ocr_sample_rate=1,
    progress_callback=None,
):
    """Process `input_path` frame by frame and write the redacted result to
    `output_path`.

    Per-frame sequence (architecture.md 6): detect faces → detect text →
    classify PII → redact faces (always blurred) → redact matched PII (per
    `mode`) → apply static zones → write frame.

    Args:
        input_path: path to the source video file.
        output_path: path to write the redacted (video-only) intermediate.
        mode: "blur" (PII regions blurred) or "fake_data" (PII regions covered
            and overwritten with a generated placeholder). Faces are always
            blurred regardless of mode.
        zones: optional list of static zone ``(x, y, w, h)`` bboxes, applied to
            every frame via ZoneManager.
        ocr_sample_rate: accepted for API stability; not yet honored — OCR runs
            on every frame (sampling/persistence is a deferred TASKS.md item).
        progress_callback: optional callable(event: dict) invoked once per
            frame with {"frame", "total", "faces", "pii"} for the test harness.

    Returns:
        A summary dict: frames_processed, faces_blurred, pii_by_type (counts
        per PII type), zones_applied.

    Raises:
        ValueError: if `mode` is invalid or the input video cannot be opened.
    """
    if mode not in ("blur", "fake_data"):
        raise ValueError(f"mode must be 'blur' or 'fake_data', got {mode!r}")

    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        cap.release()
        raise ValueError(f"could not open input video: {input_path!r}")

    zone_manager = ZoneManager()
    for zone in zones or []:
        zone_manager.add_zone(zone)

    summary = {
        "frames_processed": 0,
        "faces_blurred": 0,
        "pii_by_type": {"EMAIL": 0, "PHONE": 0, "CARD": 0, "IP": 0},
        "zones_applied": 0,
    }

    writer = None
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        if fps <= 0:
            # Some containers report 0 fps; fall back to a sane default so the
            # writer still produces a playable file.
            fps = 25.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        # mp4v is broadly compatible for the OpenCV intermediate; the final
        # container/codec choice belongs to the deferred ffmpeg mux step (D8).
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")

        while True:
            ok, frame = cap.read()
            if not ok:
                break

            height, width = frame.shape[:2]
            if writer is None:
                writer = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
                if not writer.isOpened():
                    raise ValueError(
                        f"could not open output video for writing: {output_path!r}"
                    )

            # 1. faces
            face_boxes = face_detector.detect_faces(frame)
            # 2. text
            detections = ocr_detector.detect_text(frame)
            # 3. classify OCR text
            pii_regions = []  # (pii_type, bbox)
            for text, bbox in detections:
                pii_type = _classify_pii(text)
                if pii_type is not None:
                    pii_regions.append((pii_type, bbox))

            # 4. redact faces — always blurred, regardless of mode
            for fbox in face_boxes:
                redactor.blur_region(frame, fbox)
            summary["faces_blurred"] += len(face_boxes)

            # 5. redact matched PII, per mode
            for pii_type, bbox in pii_regions:
                if mode == "blur":
                    redactor.blur_region(frame, bbox)
                else:  # fake_data
                    replacement = fake_data.generate(pii_type)
                    redactor.fake_data_region(frame, bbox, replacement)
                summary["pii_by_type"][pii_type] += 1

            # 6. static zones — every frame, via ZoneManager
            zone_manager.apply_zones(frame, mode="blur")
            summary["zones_applied"] += len(zone_manager.get_zones())

            # 7. write frame
            writer.write(frame)
            summary["frames_processed"] += 1

            if progress_callback is not None:
                progress_callback(
                    {
                        "frame": summary["frames_processed"],
                        "total": total_frames,
                        "faces": len(face_boxes),
                        "pii": len(pii_regions),
                    }
                )
    finally:
        cap.release()
        if writer is not None:
            writer.release()

    return summary
