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

OCR sampling (architecture.md 6.4/6.5, 7): OCR is expensive, so it runs only
on every `ocr_sample_rate`-th frame (frames 0, N, 2N, ...). Between samples the
most recent PII detections (type + bbox, and — in fake-data mode — the already
generated replacement string) are persisted and re-applied, rather than
re-running OCR. This avoids both wasted computation and visual flicker in the
output. `ocr_sample_rate=1` reproduces "OCR on every frame". Face detection and
static zones still run on every frame regardless of the OCR sample rate.

Output (architecture.md 6.8/6.9, DECISIONS.md D8): processed frames are written
to a temporary video-only intermediate via OpenCV, then ffmpeg (bundled with
`imageio-ffmpeg`) re-muxes that video with the **original** audio track into the
final `output_path`. Both streams are copied, not re-encoded. The intermediate
is always removed, on success and on failure. A source with no audio still
produces a valid video-only output.
"""

import os
import subprocess
import tempfile

import cv2
import imageio_ffmpeg

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


def _mux_audio(processed_video_path, source_path, output_path):
    """Combine the processed (video-only) stream with the source's audio.

    Muxes the video stream from `processed_video_path` (the OpenCV-written
    intermediate) with the audio stream from the original `source_path` into
    `output_path`, using the ffmpeg binary bundled with `imageio-ffmpeg`
    (DECISIONS.md D8). Streams are copied, not re-encoded — the processed video
    is preserved exactly and the original audio is preserved without
    reprocessing. The audio mapping is optional (``1:a:0?``) so a source with no
    audio track still produces a valid video-only output.

    Args are passed to ffmpeg as a subprocess argument list (never a shell
    string). Raises RuntimeError with ffmpeg's stderr on a non-zero exit.
    """
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    args = [
        ffmpeg_exe,
        "-y",                 # overwrite output without prompting
        "-nostdin",           # never block waiting on stdin
        "-loglevel", "error",
        "-i", processed_video_path,   # input 0: processed video
        "-i", source_path,            # input 1: original (audio source)
        "-map", "0:v:0",              # video from the processed stream
        "-map", "1:a:0?",             # audio from the original, if it exists
        "-c:v", "copy",               # keep processed video exactly as written
        "-c:a", "copy",               # preserve original audio, no re-encode
        "-shortest",                  # guard against audio outlasting the video
        output_path,
    ]
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            "ffmpeg audio mux failed (exit "
            f"{result.returncode}): {result.stderr.strip()}"
        )


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
    `mode`) → apply static zones → write frame. OCR (detect text → classify)
    runs only on sampled frames (every `ocr_sample_rate`-th frame); between
    samples the last PII detections are persisted and re-applied.

    Args:
        input_path: path to the source video file.
        output_path: path to write the final redacted video. Frames are first
            written to a temporary video-only intermediate, then ffmpeg re-muxes
            the original audio from `input_path` into `output_path` (D8).
        mode: "blur" (PII regions blurred) or "fake_data" (PII regions covered
            and overwritten with a generated placeholder). Faces are always
            blurred regardless of mode.
        zones: optional list of static zone ``(x, y, w, h)`` bboxes, applied to
            every frame via ZoneManager.
        ocr_sample_rate: run OCR only every Nth frame (frames 0, N, 2N, ...);
            persist the last PII detections for the frames in between
            (architecture.md 6.4/6.5, 7). Must be a positive integer; ``1``
            means OCR on every frame. Face detection and static zones are
            unaffected — they run on every frame.
        progress_callback: optional callable(event: dict) invoked once per
            frame with {"frame", "total", "faces", "pii"} for the test harness.

    Returns:
        A summary dict: frames_processed, faces_blurred, pii_by_type (counts
        per PII type, counted per frame a region is redacted — persisted
        regions count on each frame they apply), zones_applied.

    Raises:
        ValueError: if `mode` is invalid, `ocr_sample_rate` is not a positive
            integer, or the input video cannot be opened.
        RuntimeError: if the ffmpeg audio-mux step fails.
    """
    if mode not in ("blur", "fake_data"):
        raise ValueError(f"mode must be 'blur' or 'fake_data', got {mode!r}")

    if isinstance(ocr_sample_rate, bool) or not isinstance(ocr_sample_rate, int) \
            or ocr_sample_rate < 1:
        raise ValueError(
            f"ocr_sample_rate must be a positive integer, got {ocr_sample_rate!r}"
        )

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
    intermediate_path = None
    try:
        # Processed frames go to a temporary video-only file next to the final
        # output (same filesystem); ffmpeg later muxes the original audio into
        # `output_path`. Created after the input opened so a bad input never
        # leaves a stray temp file behind.
        out_dir = os.path.dirname(os.path.abspath(output_path))
        fd, intermediate_path = tempfile.mkstemp(
            prefix="pixelveil_", suffix=".mp4", dir=out_dir
        )
        os.close(fd)

        fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        if fps <= 0:
            # Some containers report 0 fps; fall back to a sane default so the
            # writer still produces a playable file.
            fps = 25.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        # mp4v is broadly compatible for the OpenCV intermediate; the final
        # container is produced by the ffmpeg mux step (D8), which copies this
        # video stream unchanged and attaches the original audio.
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")

        # PII regions carried over from the most recent OCR sample. Each entry
        # is (pii_type, bbox, replacement) where replacement is the pre-
        # generated fake-data string (fake_data mode) or None (blur mode).
        # Persisting the generated string — not just the bbox — keeps the
        # synthetic value stable between samples instead of flickering every
        # frame (architecture.md 6.5/7).
        persisted_pii = []
        frame_index = 0

        while True:
            ok, frame = cap.read()
            if not ok:
                break

            height, width = frame.shape[:2]
            if writer is None:
                writer = cv2.VideoWriter(
                    intermediate_path, fourcc, fps, (width, height)
                )
                if not writer.isOpened():
                    raise ValueError(
                        "could not open intermediate video for writing: "
                        f"{intermediate_path!r}"
                    )

            # 1. faces — detected on every frame (existing pipeline behavior)
            face_boxes = face_detector.detect_faces(frame)

            # 2/3. text + classify — only on sampled frames (every Nth). Between
            # samples the previous detections in `persisted_pii` are reused.
            if frame_index % ocr_sample_rate == 0:
                detections = ocr_detector.detect_text(frame)
                persisted_pii = []
                for text, bbox in detections:
                    pii_type = _classify_pii(text)
                    if pii_type is None:
                        continue
                    # Generate the fake-data replacement once, at sample time,
                    # so it stays fixed until the next sample (no flicker).
                    replacement = (
                        fake_data.generate(pii_type)
                        if mode == "fake_data"
                        else None
                    )
                    persisted_pii.append((pii_type, bbox, replacement))

            # 4. redact faces — always blurred, regardless of mode
            for fbox in face_boxes:
                redactor.blur_region(frame, fbox)
            summary["faces_blurred"] += len(face_boxes)

            # 5. redact matched PII (fresh or persisted), per mode
            for pii_type, bbox, replacement in persisted_pii:
                if mode == "blur":
                    redactor.blur_region(frame, bbox)
                else:  # fake_data — reuse the persisted replacement string
                    redactor.fake_data_region(frame, bbox, replacement)
                summary["pii_by_type"][pii_type] += 1

            # 6. static zones — every frame, via ZoneManager
            zone_manager.apply_zones(frame, mode="blur")
            summary["zones_applied"] += len(zone_manager.get_zones())

            # 7. write frame
            writer.write(frame)
            summary["frames_processed"] += 1
            frame_index += 1

            if progress_callback is not None:
                progress_callback(
                    {
                        "frame": summary["frames_processed"],
                        "total": total_frames,
                        "faces": len(face_boxes),
                        "pii": len(persisted_pii),
                    }
                )

        # Finalize the intermediate (flush + close) before ffmpeg reads it.
        if writer is not None:
            writer.release()
            writer = None

        # Mux only if frames were actually written; an empty intermediate is
        # not a valid input for ffmpeg and yields no output.
        if summary["frames_processed"] > 0:
            _mux_audio(intermediate_path, input_path, output_path)
    finally:
        cap.release()
        if writer is not None:
            writer.release()
        # Remove the intermediate on every path — success, mux failure, or an
        # error mid-processing — so no temp file is ever left behind.
        if intermediate_path is not None and os.path.exists(intermediate_path):
            os.remove(intermediate_path)

    return summary
