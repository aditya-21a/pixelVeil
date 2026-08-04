# PixelVeil — TASKS.md

Status legend: `[ ]` todo · `[~]` in progress · `[x]` done

---

## Phase 0 — Environment Setup
- [ ] Install Python (confirm version, pin it in README)
- [ ] Set up virtual environment
- [ ] Install core deps: `opencv-python`, `mediapipe`, `pytesseract`, `pillow`, `imageio-ffmpeg`
- [ ] Install Tesseract OCR binary (Windows installer), confirm `pytesseract` can find it
- [ ] Confirm ffmpeg is accessible (via `imageio-ffmpeg` or system install)

## Phase 1 — Core Pipeline (plain scripts, no GUI yet)
- [x] `core/face_detector.py` — `detect_faces(frame) -> list[bbox]` using MediaPipe
- [ ] Test face detector standalone on a still image with 1 face, confirm bbox accuracy
- [ ] Test face detector on a still image with multiple faces
- [ ] Test face detector on an angled/partial face — confirm known limitation, log behavior
- [ ] `core/ocr_detector.py` — `detect_text(frame) -> list[(text, bbox)]` using Tesseract
- [ ] Test OCR detector standalone on a still frame with a visible email/phone/card number
- [ ] `core/pii_matcher.py` — regex patterns for email, phone, credit card, IP
- [ ] Unit test each regex pattern against valid + invalid sample strings
- [ ] `core/redactor.py` — draw blur, solid box, and fake-data text onto a frame given bboxes
- [ ] `utils/fake_data.py` — generate placeholder text per PII type (fake name, fake email, etc.)
- [ ] `core/zone_manager.py` — store/apply user-defined static zones to a frame
- [ ] `core/video_pipeline.py` — orchestrate: read frame → detect (face + OCR sampled) → match PII → redact → write frame
- [ ] Implement frame-sampling logic for OCR (every N frames) with bbox persistence between samples
- [ ] Implement intermediate video write (OpenCV) → ffmpeg mux with original audio

## Phase 2 — Pipeline Validation (before touching any UI)
- [ ] Build 2-3 test videos with planted PII (see TESTING.md for exact cases)
- [ ] Run full pipeline end-to-end on each test video
- [ ] Confirm: all planted faces blurred
- [ ] Confirm: all planted PII detected and handled (both blur mode and fake-data mode)
- [ ] Confirm: output video plays correctly with audio intact
- [ ] Log and review any false negatives/positives — do not proceed to UI until miss rate is understood and acceptable (see TESTING.md acceptance criteria)

## Phase 3 — Test Harness UI (Flask + HTML, per design.md)
- [ ] Minimal Flask app skeleton, serves 4 screens (Upload / Processing / Results / Settings)
- [ ] Upload screen: file picker/drag-drop, mode toggle, zone-drawing canvas on first frame
- [ ] Wire "Process Video" button to trigger `video_pipeline.py` via a Flask route
- [ ] Processing screen: progress bar + per-stage status panel (per design.md)
- [ ] Processing screen: live scrolling technical log (SSE or polling)
- [ ] Processing screen: live current-frame preview with detection boxes overlaid
- [ ] Results screen: before/after video preview, summary panel, download button
- [ ] Results screen: "Flag an issue" logging feature
- [ ] Settings screen: OCR sampling rate, face confidence threshold, editable regex list

## Phase 4 — Packaging (Windows .exe)
- [ ] Set up PyInstaller build config
- [ ] Bundle Tesseract binary into `assets/`
- [ ] Test packaged .exe on a clean Windows machine (not your dev machine)
- [ ] Check for antivirus/Defender false-positive flagging — plan mitigation (code signing / vendor allowlisting) if it occurs

## Phase 5 — Pre-Launch
- [ ] Post concept/demo clip in target communities (r/QualityAssurance, r/CustomerSuccess, r/sysadmin, Indie Hackers) — gauge real interest
- [ ] Set up Stripe Checkout + license-key validation for Pro tier
- [ ] Write README.md (setup, usage, screenshots)
- [ ] Product Hunt launch prep

## v2 Backlog (not v1, tracked so it's not forgotten)
- [ ] Age-estimation pass for "Blur children only" mode (see DECISIONS.md + roadmap.md 9b for design principle)
- [ ] Batch processing (multiple files at once)
- [ ] EasyOCR as a heavier/more-accurate fallback mode