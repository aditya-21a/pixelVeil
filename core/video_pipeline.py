"""
Orchestrator — ties together face_detector, ocr_detector, pii_matcher,
zone_manager, and redactor to process a full video file.

See docs/architecture.md section 6 (Data Flow) for the exact per-frame
sequence, and docs/DECISIONS.md D8 for why ffmpeg muxing is used for the
final output rather than OpenCV's VideoWriter alone.
    Args:
        input_path: path to the source video file.
        output_path: path to write the redacted output video.
        mode: "blur" or "fake_data".
        zones: list of static zone bboxes.
        ocr_sample_rate: run OCR every N frames (see docs/architecture.md
            section 7, Performance Notes).
        progress_callback: optional callable(event: dict) for streaming
            progress/log data to the test harness UI (see docs/design.md
            Screen 2).

    Returns:
        summary dict: counts of faces blurred, PII matches by type, zones
        applied — used by the Results screen (docs/design.md Screen 3).
    """

