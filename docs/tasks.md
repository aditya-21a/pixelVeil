# PixelVeil — TASKS.md

Status legend: `[ ]` todo · `[~]` in progress · `[x]` done

---

## Phase 0 — Environment Setup
- [ ] Install Python (confirm version, pin it in README)
- [ ] Set up virtual environment
- [ ] Install core deps: `opencv-python`, `mediapipe`, `rapidocr`, `onnxruntime`, `pillow`, `imageio-ffmpeg`
- [ ] ~~Install Tesseract OCR binary~~ — **no longer required.** OCR backend is RapidOCR on ONNX Runtime (DECISIONS.md D17, supersedes D6); its ONNX models ship inside the `rapidocr` wheel, so `pip install rapidocr onnxruntime` is the whole OCR setup (fully offline, no separate binary).
- [ ] Confirm ffmpeg is accessible (via `imageio-ffmpeg` or system install)

## Phase 1 — Core Pipeline (plain scripts, no GUI yet)
- [x] `core/face_detector.py` — `detect_faces(frame) -> list[bbox]` using MediaPipe
- [x] Test face detector standalone on a still image with 1 face, confirm bbox accuracy
  - Validated: `tests/test_face_detector.py` (encodes TESTING.md 3.1) — `5 passed` with MediaPipe 0.10.21 + `tests/assets/single_frontal_face.jpg`. See ISSUE-001 (resolved).
- [x] Test face detector on a still image with multiple faces
  - Validated: `tests/test_face_detector.py::TestFaceDetectorMultipleFaces` (encodes TESTING.md 3.1 "multiple faces") — `9 passed` with MediaPipe 0.10.21 against `tests/assets/multiple_faces.jpg` (3 faces detected, all bboxes within bounds; requires majority >= 2). Env override: `PIXELVEIL_TEST_MULTI_FACE_IMAGE`.
- [x] Test face detector on an angled/partial face — confirm known limitation, log behavior
  - Validated: `tests/test_face_detector.py::TestFaceDetectorAngledFace` — characterization test against `tests/assets/angled_face.jpg`. Observed: **0 faces detected (angled face missed)** on MediaPipe 0.10.21; asserts invariants only (returns list, boxes within bounds), does not force a detection. Logged as accepted v1 limitation ISSUE-002.
- [x] `core/ocr_detector.py` — `detect_text(frame) -> list[(text, bbox)]` using RapidOCR (ONNX Runtime)
  - Backend swapped from the originally planned Tesseract/pytesseract to RapidOCR on ONNX Runtime (DECISIONS.md D17, supersedes D6). Public interface unchanged; RapidOCR-specific objects normalized to `(text, (x,y,w,h))` inside the module, nothing leaks to callers. `rapidocr` 3.9.2 / `onnxruntime` 1.28.0, bundled PP-OCRv6 models, fully offline.
- [x] Test OCR detector standalone on a still frame with a visible email/phone/card number
  - Validated: `tests/test_ocr_detector.py` — `10 passed`. Covers normal UI text, email, phone, IPv4, credit card, small text, plus None/empty/blank-frame guards and a no-text graphics frame. All returned bboxes asserted in-bounds. Text checked leniently (key token present). Frames synthesized with OpenCV at test time (no fixtures, no network).
- [x] Validate OCR detector against a realistic application screenshot
  - Validated: `tests/test_ocr_detector.py::TestOCRDetectorRealScreenshot` against `tests/assets/ocr_real_screen.png` (1536×1024 mock PixelVeil dashboard). `17 passed` total. All 5 planted values recognized exactly, each in its own in-bounds box (labels split from values — the label/value split is expected and accounted for): Name `John Doe`, Email `john.doe@example.com`, Phone `9876543210`, IPv4 `192.168.1.105`, Card `4111 1111 1111 1111`. Representative UI subset (`PixelVeil Test Account`, `Account Information`, `Account Settings`, `Privacy Configuration`) also detected. `core/ocr_detector.py` unchanged — no implementation bug found.
- [x] `core/pii_matcher.py` — regex patterns for email, phone, credit card, IP
  - Implemented: `is_email()`, `is_phone()` (US 10-digit), `is_card()` (13-19 digits), `is_ipv4()`. Built on Python's `re` module per D7. Deliberately permissive (bias toward recall) — false positive only sends an extra box to the redactor; false negative is a privacy failure.
- [x] Unit test each regex pattern against valid + invalid sample strings
  - Validated: `tests/test_pii_matcher.py` — `16 passed, 45 subtests`. Each pattern tested against known-good PII formats (multiple variants) and clearly-invalid strings. Covers embedded text (e.g. "Email: user@example.com"), None input, and edge cases. Fast, deterministic, offline (no OCR machinery, just string matching).
- [x] `core/redactor.py` — draw blur, solid box, and fake-data text onto a frame given bboxes
  - Implemented as a **rendering-only** layer: `blur_region(frame, bbox)`, `box_region(frame, bbox, color)`, `fake_data_region(frame, bbox, text, ...)`. Operates on a supplied bbox; for fake-data the caller supplies the already-generated replacement string (redactor does NOT generate fake data, detect faces, run OCR, match PII, or process video — those belong to fake_data.py / video_pipeline.py). Boxes clamped to frame; edge/partial/zero-area/off-frame boxes handled safely (no-op or clamp). Frames modified in place. Note: the old stub docstring described an orchestration signature (`redact(frame, face_boxes, pii_matches, zones, mode)`) — that orchestration belongs to video_pipeline.py, which knows a bbox's source and the active mode; the rendering layer only draws.
  - Validated: `tests/test_redactor.py` — `14 passed, 3 subtests`. Blur obscures + reduces variance; solid box covers; fake-data covers original and draws supplied text; outside pixels unchanged; boundary / partial-out-of-frame / negative-origin / zero-area / fully-off-frame / None/empty-frame cases handled without crashing.
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
- [ ] ~~Bundle Tesseract binary into `assets/`~~ — **not needed.** RapidOCR's ONNX models ship inside the `rapidocr` wheel; PyInstaller just needs to collect the `rapidocr` package data (no external OCR binary). See DECISIONS.md D17.
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