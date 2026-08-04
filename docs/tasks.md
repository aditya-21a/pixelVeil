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
- [x] `utils/fake_data.py` — generate placeholder text per PII type (fake name, fake email, etc.)
  - Implemented: `generate(pii_type)` for the four types pii_matcher.py detects — "EMAIL", "PHONE", "CARD", "IP" (case-insensitive). Generation-only (no OCR/matching/rendering); output feeds redactor.fake_data_region() as the replacement string. Uses stdlib `random` (no new dep). Values are clearly synthetic yet natural-looking: `example.com` emails (RFC 2606), `192.0.2.x` IPs (RFC 5737 TEST-NET-1), `555-01xx` phones (fictional block), non-Luhn `4000 ...` cards. Unsupported/invalid types raise `ValueError`. **Name is intentionally not a supported type** — pii_matcher.py has no name detection and D7 defers names/NER to v2, so nothing upstream flags a name region; the redactor's "Test User 1" was illustrative only.
  - Validated: `tests/test_fake_data.py` — `11 passed, 16 subtests`. Each type non-empty + correct shape (cross-checked against pii_matcher's is_* functions), synthetic-safety markers, invalid/non-string type raises, repeated generation stays valid and varies.
- [x] `core/zone_manager.py` — store/apply user-defined static zones to a frame
  - Implemented `ZoneManager`: `add_zone(bbox)` (validates 4-tuple + positive area, coerces to int, returns index), `remove_zone(index)`, `get_zones()`, `clear()`, and `apply_zones(frame, mode="blur"|"box", color)`. Zones are `(x,y,w,h)` in video-frame pixel coords (canvas→pixel mapping is the caller/GUI's job, not this module's). Application **reuses core.redactor** (`blur_region`/`box_region`) — no duplicated redaction logic — so edge/partial/off-frame clamping is inherited. fake-data mode intentionally not offered for zones (a zone is a region, not a typed PII value). No detection/OCR/matching/fake-data/video/GUI logic added.
  - Validated: `tests/test_zone_manager.py` — `19 passed, 4 subtests`. Storage (add/remove/get/clear/validation), box + blur application, exact coordinate bounds (no off-by-one bleed), multiple zones, boundary/partial-out-of-frame/fully-off-frame/no-zones, invalid mode, and same-zones-applied-consistently-across-frames. Redactor suite still `14 passed` (no regression from the new import).
- [x] `core/video_pipeline.py` — orchestrate: read frame → detect (face + OCR sampled) → match PII → redact → write frame
  - Implemented `process_video(input_path, output_path, mode="blur"|"fake_data", zones=None, ocr_sample_rate=1, progress_callback=None) -> summary dict`. **Orchestration only** — reuses each component's existing public API (face_detector, ocr_detector, pii_matcher, redactor, ZoneManager, fake_data) with zero duplicated detection/OCR/matching/drawing/generation logic. Per-frame sequence: detect faces → detect text → classify PII → **blur faces (always, regardless of mode)** → redact matched PII (blur, or fake_data.generate() → redactor.fake_data_region()) → apply static zones → write frame. Reads/writes via OpenCV, preserves dimensions + FPS (0-fps containers fall back to 25). Invalid mode / unopenable input raise ValueError; cap + writer released in a `finally`. Returns counts (frames_processed, faces_blurred, pii_by_type, zones_applied).
  - Validated: `tests/test_video_pipeline.py` — `10 passed`. Round-trip on tiny synthetic mp4s (frame count, dimensions/FPS preserved, invalid-input raises + no output, invalid-mode raises, progress callback per frame) + mock-wiring tests (faces always blurred even in fake_data mode, fake_data routes EMAIL→generate("EMAIL")→fake_data_region, blur mode blurs PII, non-PII text ignored, static zones applied every frame). No component logic duplicated (asserted via mocks).
  - **Deferred (next two TASKS.md items, intentionally not implemented here):** OCR every-N-frame sampling + bbox persistence, and ffmpeg audio mux. `ocr_sample_rate` is accepted for API stability but not yet honored (OCR runs every frame); output is the OpenCV video-only intermediate.
- [x] Implement frame-sampling logic for OCR (every N frames) with bbox persistence between samples
  - Implemented in `core/video_pipeline.py`: `ocr_sample_rate` is now functional. OCR (`ocr_detector.detect_text` → `pii_matcher` classify) runs only on frames where `frame_index % ocr_sample_rate == 0` (frames 0, N, 2N, ...). Between samples the last PII detections are persisted as `(pii_type, bbox, replacement)` and re-applied every frame (architecture.md 6.4–6.5, 7). `ocr_sample_rate=1` is the previous every-frame behavior (backwards compatible). Face detection and static zones still run **every** frame. In fake-data mode the generated replacement string is produced once at sample time and persisted (D18) to avoid per-frame flicker. `ocr_sample_rate` is validated as a positive integer (bool/float/str/None/<1 → ValueError) before the video is opened, so no output is written on bad input. `process_video()` API and summary/progress keys unchanged.
  - Validated: `tests/test_video_pipeline.py` — `20 passed, 12 subtests` (10 new sampling tests: rate-1-every-frame, rate-N-only-on-sampled-frames, bbox persists between samples, persisted PII stops on empty sample, persisted PII updates on changed sample, fake-data value persisted/generated-once, faces every frame, zones every frame, summary+progress reflect persistence, invalid-rate rejection). Regression: redactor/zone_manager/fake_data/pii_matcher suites still `60 passed`.
  - Between-samples miss for moving/scrolling text recorded as accepted v1 tradeoff ISSUE-003 (TESTING.md 3.2).
- [x] Implement intermediate video write (OpenCV) → ffmpeg mux with original audio
  - Implemented in `core/video_pipeline.py` (D8): processed frames are written to a temporary video-only intermediate (`pixelveil_*.mp4`, created next to the final output via `tempfile.mkstemp`), then a private `_mux_audio()` invokes the ffmpeg binary bundled with **imageio-ffmpeg** (`imageio_ffmpeg.get_ffmpeg_exe()`, already a project dep — no new dependency) to mux the processed video with the **original** input's audio into `output_path`. ffmpeg is called via a `subprocess.run` **argument list** (no shell string, no `shell=True`); streams are copied (`-c:v copy -c:a copy`, original audio not reprocessed); audio mapping is optional (`-map 1:a:0?`) so a source with **no audio** still yields a valid video-only output; `-shortest` guards against audio outlasting video. Non-zero ffmpeg exit → `RuntimeError` carrying ffmpeg's stderr. The intermediate is removed in a `finally` on **every** path (success, mux failure, or mid-processing error). `process_video()` API, OCR sampling/persistence, face/PII redaction, zones, summary, and progress are unchanged.
  - Validated: `tests/test_video_pipeline.py::TestProcessVideoAudioMux` — `27 passed, 12 subtests` total. Covers: source-with-audio → output has audio (real ffmpeg, synthesized sine+color fixture); source-without-audio → valid playable video-only output; processed video stream intact (dims/fps/frame-count survive write+copy); temp cleaned up on success; ffmpeg failure → RuntimeError + temp cleaned; temp cleaned on mid-processing error; ffmpeg called with a safe arg list (no shell). Regression: existing 20 pipeline tests + redactor/zone_manager/fake_data/pii_matcher `60 passed` all still green.
  - Limitation: audio in a codec that can't be stream-copied into MP4 fails the mux (no re-encode fallback in v1) — ISSUE-004.

## Phase 2 — Pipeline Validation (before touching any UI)
- [x] Build 2-3 test videos with planted PII (see TESTING.md for exact cases)
  - Built all 5 TESTING.md §2 fixtures under `tests/sample_videos/` via a single deterministic OpenCV generator, `tests/make_sample_videos.py` (no randomness/network/downloads; regenerate rather than commit — the MP4s are already git-ignored by `tests/sample_videos/*.mp4`). All 960×540, 10 fps, 60 frames (6.0 s), 167–393 KB. Frames drawn with OpenCV; audio is a deterministic sine tone muxed via the existing imageio-ffmpeg dep on the two fixtures that need it.
    - `test_faces_basic.mp4` — `single_frontal_face.jpg` fit to frame, static. Ground truth: **1 frontal face** (sanity-checked: `detect_faces` → 1). No audio.
    - `test_faces_multi.mp4` — `multiple_faces.jpg` fit to frame, static. Ground truth: **3 faces** (sanity-checked: `detect_faces` → 3). No audio.
    - `test_pii_text.mp4` — mock "Acme Admin" dashboard. Ground truth PII (all reserved/doc values): EMAIL `john.doe@example.com`, PHONE `9876543210`, IP `192.168.1.105`, CARD `4111 1111 1111 1111` (sanity-checked: OCR reads all four exactly). **Audio: yes** (440 Hz sine).
    - `test_mixed.mp4` — `single_frontal_face.jpg` (1 face) + static PII panel (EMAIL `john.doe@example.com`, PHONE `9876543210`) + a **scrolling** bottom ticker carrying CARD `4111 1111 1111 1111` / IP `192.168.1.105` that moves each frame — the intended repro for ISSUE-003 (moving PII between OCR samples). **Audio: yes** (330 Hz sine).
    - `test_zones.mp4` — mock "CRM Workspace" whose left sidebar panel sits at **fixed pixel coords `(x=20, y=70, w=260, h=430)` on every frame** (a moving ticket counter + circle elsewhere prove the panel is static while the rest changes). No PII, no audio — isolates static-zone behavior.
  - Not run yet (next Phase 2 items): full end-to-end pipeline / acceptance scoring, blur-vs-fake-data confirmation, audio-in-sync check.
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