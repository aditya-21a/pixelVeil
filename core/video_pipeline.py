"""
Orchestrator — ties together face_detector, ocr_detector, pii_matcher,
zone_manager, and redactor to process a full video file.

See docs/architecture.md section 6 (Data Flow) for the exact per-frame
sequence, and docs/DECISIONS.md D8 for why ffmpeg muxing is used for the
final output rather than OpenCV's VideoWriter alone.

Public API:
    process_video(input_path, output_path, mode="blur", zones=None,
                  ocr_sample_rate=1, face_min_confidence=None,
                  progress_callback=None, preview_callback=None) -> dict

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
`imageio-ffmpeg`) muxes that video with the **original** audio track into the
final `output_path`. The video is transcoded from the intermediate's `mp4v` to
browser-playable **H.264** in that step (so HTML5 `<video>` can render it); the
audio is copied, not re-encoded. The intermediate is always removed, on success
and on failure. A source with no audio still produces a valid video-only output.
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

# OCR text is matched to PII values by pii_matcher.find_pii(), which returns
# each value's type *and its character span* within the OCR string, resolving
# overlapping/ambiguous matches by its own documented precedence. The span lets
# this module redact only the value's sub-region of the OCR box, leaving any
# label ("Email:", "CARD", ...) in the same box visible. The type string is what
# utils.fake_data.generate() expects.


def _span_to_bbox(ocr_bbox, text, start, end):
    """Map a character span ``[start, end)`` of an OCR string to a tighter bbox
    inside `ocr_bbox`.

    RapidOCR returns one box per recognized *line*, not per glyph, so exact
    per-character coordinates are unavailable. This approximates each character's
    horizontal extent as a uniform fraction of the line width and carves out the
    sub-range covering the matched value — a deterministic mapping bounded by the
    original box. This is the documented approximation (see known-issues
    ISSUE-006): it assumes roughly uniform character width, so with proportional
    fonts the value edge can be off by a few pixels, but the region always stays
    inside the OCR box and always covers the value.

    Vertical extent (`y`, `h`) is preserved — a value sits on the same line as
    its label. When the whole string is the value (``start == 0`` and
    ``end == len(text)``) the result is exactly `ocr_bbox` (integer-exact), so a
    value-only OCR box redacts precisely as before this tightening existed.

    Returns an ``(x, y, w, h)`` tuple, never narrower than 1px.
    """
    x, y, w, h = ocr_bbox
    n = len(text)
    if n <= 0 or w <= 0:
        return ocr_bbox
    # Defensive clamp of the span into the string bounds.
    start = max(0, min(start, n))
    end = max(start, min(end, n))
    x0 = x + int(round(w * start / n))
    x1 = x + int(round(w * end / n))
    # Keep both edges inside the original box, and guarantee positive width.
    x0 = max(x, min(x0, x + w))
    x1 = max(x, min(x1, x + w))
    if x1 <= x0:
        x1 = min(x0 + 1, x + w)
        x0 = x1 - 1
    return (x0, y, x1 - x0, h)


def _mux_audio(processed_video_path, source_path, output_path):
    """Combine the processed (video-only) stream with the source's audio.

    Muxes the video stream from `processed_video_path` (the OpenCV-written
    intermediate) with the audio stream from the original `source_path` into
    `output_path`, using the ffmpeg binary bundled with `imageio-ffmpeg`
    (DECISIONS.md D8). The video is transcoded to **H.264 / yuv420p** here: the
    OpenCV intermediate is MPEG-4 Part 2 (`mp4v`), which VLC/QuickTime play but
    HTML5 `<video>` in Chrome/Edge/Firefox cannot decode (controls + duration
    show, image stays blank). Re-encoding to H.264 in this step — which already
    runs for every output — makes the redacted result universally playable,
    including in the harness's Results screen, without touching any
    detection/OCR/redaction logic (the pixels are identical, only the codec
    changes). The original audio is still stream-copied (`-c:a copy`, no
    re-encode). The audio mapping is optional (``1:a:0?``) so a source with no
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
        "-c:v", "libx264",            # transcode mp4v -> H.264 for browsers
        "-pix_fmt", "yuv420p",        # 4:2:0 so browsers/QuickTime can decode
        "-movflags", "+faststart",    # moov atom up front for progressive play
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
    face_min_confidence=None,
    progress_callback=None,
    preview_callback=None,
):
    """Process `input_path` frame by frame and write the redacted result to
    `output_path`.

    Per-frame sequence (architecture.md 6): detect faces → detect text →
    classify PII → redact faces (always blurred) → redact matched PII (per
    `mode`) → apply static zones → write frame. OCR (detect text → classify)
    runs only on sampled frames (every `ocr_sample_rate`-th frame); between
    samples the last PII detections are persisted and re-applied. When an OCR
    box holds a label plus a value (e.g. "Email: a@b.com"), only the matched
    value's sub-region is redacted (via pii_matcher.find_pii spans mapped by
    `_span_to_bbox`); the label stays visible.

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
        face_min_confidence: optional minimum face-detection confidence in
            [0.0, 1.0], forwarded to face_detector.detect_faces(). ``None``
            (the default) uses the detector's own default confidence, so
            existing behavior is unchanged; a lower value blurs when less
            certain (bias toward catching faces, per TESTING.md).
        progress_callback: optional callable(event: dict) invoked once per
            frame with {"frame", "total", "faces", "pii"} for the test harness.
        preview_callback: optional callable(event: dict) invoked once per frame,
            **after the frame has been written**, for a diagnostic live preview
            (test harness only). The event carries the just-written, post-
            redaction frame plus the detections actually applied to it:
            ``{"frame", "frame_number", "total", "faces", "pii", "zones"}`` where
            `faces` is a list of ``(x, y, w, h)`` face boxes, `pii` is a list of
            ``(pii_type, (x, y, w, h))`` for the PII regions redacted on this
            frame (freshly sampled *or* persisted between OCR samples — reported
            honestly either way), and `zones` is the static-zone list. The frame
            is passed by reference for cheap observation; consumers that draw on
            it MUST copy first (the pipeline has already written the output, so
            mutating the frame here cannot affect the redacted video). This is a
            pure observation hook: it changes no detection, redaction, OCR-
            sampling, audio-mux, or summary behavior, and defaults to a no-op.

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

    if face_min_confidence is not None:
        if isinstance(face_min_confidence, bool) \
                or not isinstance(face_min_confidence, (int, float)) \
                or not (0.0 <= face_min_confidence <= 1.0):
            raise ValueError(
                "face_min_confidence must be a number in [0.0, 1.0] or None, "
                f"got {face_min_confidence!r}"
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
        # container is produced by the ffmpeg mux step (D8), which transcodes
        # this video stream to browser-playable H.264 and attaches the original
        # audio.
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

            # 1. faces — detected on every frame (existing pipeline behavior).
            # Forward a custom confidence only when supplied, so the detector's
            # own default is used otherwise (unchanged behavior).
            if face_min_confidence is None:
                face_boxes = face_detector.detect_faces(frame)
            else:
                face_boxes = face_detector.detect_faces(
                    frame, min_confidence=face_min_confidence
                )

            # 2/3. text + classify — only on sampled frames (every Nth). Between
            # samples the previous detections in `persisted_pii` are reused.
            if frame_index % ocr_sample_rate == 0:
                detections = ocr_detector.detect_text(frame)
                persisted_pii = []
                for text, bbox in detections:
                    # find_pii reports each PII value's type AND its character
                    # span within `text`, so we redact only the value region of
                    # the OCR box (a label like "Email:" in the same box stays
                    # visible). Multiple values in one box each get their own
                    # region. A value-only box yields the full bbox unchanged.
                    for pii_type, start, end, _value in pii_matcher.find_pii(text):
                        value_bbox = _span_to_bbox(bbox, text, start, end)
                        # Generate the fake-data replacement once, at sample
                        # time, so it stays fixed until the next sample (no
                        # flicker), per value.
                        replacement = (
                            fake_data.generate(pii_type)
                            if mode == "fake_data"
                            else None
                        )
                        persisted_pii.append((pii_type, value_bbox, replacement))

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

            # 8. preview observation (optional diagnostic hook, after write)
            if preview_callback is not None:
                # Pass the frame by reference (cheap), plus the detections actually
                # applied to it. The frame was just written, so mutating it here
                # cannot affect the output video. The consumer MUST copy if it
                # intends to draw on the frame.
                preview_callback(
                    {
                        "frame": frame,
                        "frame_number": summary["frames_processed"],
                        "total": total_frames,
                        "faces": face_boxes,  # list of (x, y, w, h)
                        "pii": [
                            (pii_type, bbox) for pii_type, bbox, _ in persisted_pii
                        ],  # list of (type, (x,y,w,h)); drop the replacement string
                        "zones": zone_manager.get_zones(),  # list of (x, y, w, h)
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
