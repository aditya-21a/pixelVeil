# PixelVeil — TASKS.md

Status legend: `[ ]` todo · `[~]` in progress · `[x]` done


## PHASE P0 — BASELINE & EVALUATION
- [ ] TASK-P0-01: Evaluation Harness
  - DEPENDENCIES: None
  - FILES TO MODIFY: None
  - FILES TO CREATE: `tools/evaluate.py`, `tests/evaluation_corpus/`
  - IMPLEMENTATION DETAILS: Build the evaluation harness *before* changing architecture. It must establish GROUND TRUTH (Face existence / bbox / visibility) against System output. Must measure BOTH detection performance and privacy coverage. Metrics: bbox IoU, face-center error (normalized by face size), coverage rate, privacy leakage frames, false positive area, false redaction duration. Metrics must be bucketed by: face-size, edge-distance, occlusion, motion, source of detection, source of recovered protection. Record longest unprotected run and first-visible-frame leakage.
  - TESTS: Unit tests for evaluation metrics.
  - BENCHMARK: N/A
  - ACCEPTANCE CRITERIA: Harness can output quantitative privacy and performance metrics, explicitly distinguishing "Was the face detected?" from "Was the actual face region protected?".
- [ ] TASK-P0-02: Baseline Pipeline Profile
  - DEPENDENCIES: TASK-P0-01
  - FILES TO MODIFY: None
  - FILES TO CREATE: None
  - IMPLEMENTATION DETAILS: Run the evaluation harness on the current pipeline to establish the baseline for recall, precision, and processing speed. Do this before any optimization.
  - TESTS: N/A
  - BENCHMARK: Baseline metrics recorded.
  - ACCEPTANCE CRITERIA: Baseline established.
- [ ] TASK-P0-03: Hungarian Association Optimization
  - DEPENDENCIES: TASK-P0-02
  - FILES TO MODIFY: `core/face_tracker.py`
  - FILES TO CREATE: None
  - IMPLEMENTATION DETAILS: The current `_linear_sum_assignment` is O(N!) recursive brute force. Replace with scipy's O(N^3) Hungarian implementation.
  - TESTS: All existing tracker tests must pass.
  - BENCHMARK: Measure association time with 1, 5, 10, 15 faces.
  - ACCEPTANCE CRITERIA: All tests pass, O(N^3) performance, identical results for <5 faces.
- [ ] TASK-P0-04: Candidate Validation Instrumentation
  - DEPENDENCIES: TASK-P0-02
  - FILES TO MODIFY: `core/candidate_validator.py`
  - FILES TO CREATE: None
  - IMPLEMENTATION DETAILS: Add recall-biased geometric validation (e.g. marking <20px as UNCERTAIN rather than REJECT) and log validation outcomes.
  - TESTS: Unit tests for validation states.
  - BENCHMARK: False positive reduction rate vs recall.
  - ACCEPTANCE CRITERIA: Tiny faces are not blindly rejected; validation states are logged.
- [ ] TASK-P0-05: Single-Pass H.264 Encoding
  - DEPENDENCIES: TASK-P0-02
  - FILES TO MODIFY: `core/video_pipeline.py`
  - FILES TO CREATE: None
  - IMPLEMENTATION DETAILS: Current pipeline writes mp4v via OpenCV then re-encodes to H.264 via ffmpeg. Instead, pipe raw frames directly to ffmpeg subprocess stdin. Expected benefit: reduce encoding overhead. Measured benefit: determined by benchmark.
  - TESTS: All video pipeline tests must pass. Output must be playable H.264/yuv420p.
  - BENCHMARK: Measure encoding time reduction against baseline profile.
  - ACCEPTANCE CRITERIA: Single encode pass, identical output quality.

## PHASE P1 — TRACKING
- [ ] TASK-P1-01: Linear Kalman Filter
  - DEPENDENCIES: TASK-P0-04
  - FILES TO MODIFY: `core/face_tracker.py`
  - FILES TO CREATE: `core/kalman_tracker.py` (optional)
  - IMPLEMENTATION DETAILS: Replace current constant-velocity + damping model with proper Linear Kalman Filter. State vector: `[x, y, w, h, vx, vy, vw, vh]`. Constant velocity model. Process noise Q and measurement noise R as tunable parameters. Track covariance matrix P for uncertainty estimation. Critical: The tracker MUST expose covariance P for downstream uncertainty-aware expansion.
  - TESTS: Unit tests for predict/update cycle. Test convergence. Test uncertainty growth during coasting.
  - BENCHMARK: Compare tracking quality vs current tracker on test videos.
  - ACCEPTANCE CRITERIA: Smooth tracking, proper uncertainty growth, all existing tests adapted.
- [ ] TASK-P1-02: Mahalanobis Gating
  - DEPENDENCIES: TASK-P1-01
  - FILES TO MODIFY: `core/face_tracker.py`
  - FILES TO CREATE: None
  - IMPLEMENTATION DETAILS: Replace current hard-gate association (distance + IoU) with Mahalanobis distance gating using tracker covariance. Initial threshold: 9.48 (status: starting value, must sweep to find optimal threshold for our specific state/measurement dimensionality). Keep IoU as secondary cost metric.
  - TESTS: Association tests with various scenarios. Crossing faces test.
  - BENCHMARK: Track switches and fragmentations vs current.
  - ACCEPTANCE CRITERIA: Fewer track switches, proper gating of impossible associations.
- [ ] TASK-P1-03: Canonical Spatial-Kinematic Association
  - DEPENDENCIES: TASK-P1-02
  - FILES TO MODIFY: `core/face_tracker.py`
  - FILES TO CREATE: None
  - IMPLEMENTATION DETAILS: Implement canonical association combining Linear Kalman prediction, Mahalanobis gating, IoU cost, and Hungarian assignment. Optionally, split by confidence thresholds to recover partially visible faces.

## PHASE P2 — DETECTION RECOVERY
- [ ] TASK-P2-01: Boundary Recovery Policy
  - DEPENDENCIES: TASK-P1-03
  - FILES TO MODIFY: `core/video_pipeline.py`
  - FILES TO CREATE: `core/boundary_scanner.py`
  - IMPLEMENTATION DETAILS: Implement configurable boundary scanning policies (e.g., 4 strips, 2 horizontal, 2 vertical, sampled). Frame -> Boundary Recovery Policy -> [scan / skip / alternate / sample]. Benchmark compute cost vs edge-entry recall.
  - TESTS: Test with faces entering from each edge.
  - BENCHMARK: Compute cost vs Edge-entry face recall.
  - ACCEPTANCE CRITERIA: Selected policy detects edge entries without blowing compute budget.
- [ ] TASK-P2-02: Suspicion Classification
  - DEPENDENCIES: TASK-P2-01
  - FILES TO MODIFY: `core/video_pipeline.py`
  - FILES TO CREATE: `core/suspicion_detector.py`
  - IMPLEMENTATION DETAILS: Classify frames/regions as suspicious based on: track entering COASTING, boundary proximity, low confidence detection, rapid scale change. Queue suspicious regions for targeted ROI recovery.
  - TESTS: Unit tests for each suspicion trigger.
  - BENCHMARK: Suspicion detection accuracy.
  - ACCEPTANCE CRITERIA: All genuine detection dropouts flagged as suspicious.
- [ ] TASK-P2-03: Targeted ROI SCRFD
  - DEPENDENCIES: TASK-P2-02
  - FILES TO MODIFY: `core/face_detector.py`
  - FILES TO CREATE: None
  - IMPLEMENTATION DETAILS: Support extracting specific high-resolution crops from the frame and running inference only on those crops, re-mapping coordinates back to the full frame.

## PHASE P3 — OFFLINE GAP RECOVERY
- [ ] TASK-P3-01: Gap Detection
  - DEPENDENCIES: TASK-P2-03
  - FILES TO MODIFY: `core/gap_resolver.py`
  - FILES TO CREATE: None
  - IMPLEMENTATION DETAILS: After Pass 1 completes, detect temporal gaps in the tracking timeline where a track was lost and then re-acquired. Prepare endpoints for recovery.
- [ ] TASK-P3-02: GSI Mid-Track Recovery
  - DEPENDENCIES: TASK-P3-01
  - FILES TO MODIFY: `core/gap_resolver.py`
  - FILES TO CREATE: None
  - IMPLEMENTATION DETAILS: Apply Gaussian-Smoothed Interpolation (GSI) for remaining unresolved mid-track gaps. Track uncertainty using hourglass profile. Must measurably outperform linear interpolation.
- [ ] TASK-P3-03: Track-Start Backward Recovery
  - DEPENDENCIES: TASK-P3-02
  - FILES TO MODIFY: `core/gap_resolver.py`
  - FILES TO CREATE: None
  - IMPLEMENTATION DETAILS: When a track's first confirmed frame is not frame 0, search backward up to a configurable budget. Generate search ROI from forward-projected position + adaptive padding. Validate with cycle consistency.

## PHASE P4 — PRIVACY SAFETY
- [ ] TASK-P4-01: Evidence/Action Finalization
  - DEPENDENCIES: TASK-P3-03
  - FILES TO MODIFY: `core/video_pipeline.py`
  - FILES TO CREATE: None
  - IMPLEMENTATION DETAILS: Ensure strict translation from tracking state (`evidence_state` + `provenance`) to rendering intent (`privacy_action`).
- [ ] TASK-P4-02: Covariance-Based Expansion
  - DEPENDENCIES: TASK-P4-01
  - FILES TO MODIFY: `core/redactor.py`
  - FILES TO CREATE: None
  - IMPLEMENTATION DETAILS: Compute covariance-derived confidence region -> convert ellipse to axis-aligned margin -> apply configurable confidence level -> clamp using experimentally derived expansion policy.
- [ ] TASK-P4-03: Bounded Protection
  - DEPENDENCIES: TASK-P4-02
  - FILES TO MODIFY: `core/redactor.py`
  - FILES TO CREATE: None
  - IMPLEMENTATION DETAILS: Limit indefinite ghost redactions. Protect with uncertainty-expanded region up to configurable limits (initial exp: 30 frames, 1.5x spatial expansion).

## PHASE P5 — REDACTION
- [ ] TASK-P5-01: Adaptive Pixelation
  - DEPENDENCIES: TASK-P4-03
  - FILES TO MODIFY: `core/redactor.py`
  - FILES TO CREATE: None
  - IMPLEMENTATION DETAILS: Dynamically calculate pixelation block size per frame per face based on bounding box width (e.g., max(4, int(0.08 * face_width))).
- [ ] TASK-P5-02: Noise/Disruption Experiment
  - DEPENDENCIES: TASK-P5-01
  - FILES TO MODIFY: `core/redactor.py`
  - FILES TO CREATE: None
  - IMPLEMENTATION DETAILS: Implement and benchmark additive noise (e.g., Gaussian overlay) to disrupt AI reconstruction models (CodeFormer/Revelio).
- [ ] TASK-P5-03: Feathering
  - DEPENDENCIES: TASK-P5-02
  - FILES TO MODIFY: `core/redactor.py`
  - FILES TO CREATE: None
  - IMPLEMENTATION DETAILS: Alpha-blend redaction edges (configured width, e.g. 16px) to avoid H.264 macroblock ringing.

## PHASE P6 — PERFORMANCE
- [ ] TASK-P6-01: End-to-End Profiling
  - DEPENDENCIES: TASK-P5-03
  - FILES TO MODIFY: None
  - FILES TO CREATE: None
  - IMPLEMENTATION DETAILS: Profile the full locked architecture to identify processing bottlenecks.
- [ ] TASK-P6-02: ROI Batching
  - DEPENDENCIES: TASK-P6-01
  - FILES TO MODIFY: `core/face_detector.py`
  - FILES TO CREATE: None
  - IMPLEMENTATION DETAILS: Implement batch inference for targeted ROIs during Pass 2 to saturate the GPU.
- [ ] TASK-P6-03: Pipeline Parallelism
  - DEPENDENCIES: TASK-P6-02
  - FILES TO MODIFY: `core/video_pipeline.py`
  - FILES TO CREATE: None
  - IMPLEMENTATION DETAILS: Separate I/O, tracking, and rendering into parallel threads/processes if sequential execution misses target FPS.
- [ ] TASK-P6-04: TensorRT Decision
  - DEPENDENCIES: TASK-P6-03
  - FILES TO MODIFY: `core/face_detector.py`
  - FILES TO CREATE: None
  - IMPLEMENTATION DETAILS: If pipeline parallelism doesn't achieve performance targets, validate TensorRT implementation for the SCRFD models.

## PHASE P7 — FINAL VALIDATION
- [ ] TASK-P7-01: Ablation
  - DEPENDENCIES: TASK-P6-04
  - FILES TO MODIFY: None
  - FILES TO CREATE: None
  - IMPLEMENTATION DETAILS: Systematically disable components (e.g., backward recovery, GSI) to validate their contribution to privacy vs compute cost.
- [ ] TASK-P7-02: Hard-Case Evaluation
  - DEPENDENCIES: TASK-P7-01
  - FILES TO MODIFY: None
  - FILES TO CREATE: None
  - IMPLEMENTATION DETAILS: Test against the most severe test cases (motion blur, low light, heavy occlusion) to establish the operational bounds.
- [ ] TASK-P7-03: Privacy Attack Evaluation
  - DEPENDENCIES: TASK-P7-02
  - FILES TO MODIFY: None
  - FILES TO CREATE: None
  - IMPLEMENTATION DETAILS: Run facial recognition models against the redacted outputs to confirm the redaction guarantees hold.
- [ ] TASK-P7-04: Regression Suite
  - DEPENDENCIES: TASK-P7-03
  - FILES TO MODIFY: `tests/`
  - FILES TO CREATE: None
  - IMPLEMENTATION DETAILS: Ensure the continuous integration suite properly asserts the privacy-critical rules (e.g., min_hits=1) to prevent future regression.


---

## OLD ARCHITECTURE TASKS (Archived)

﻿# PixelVeil ΓÇö TASKS.md

Status legend: `[ ]` todo ┬╖ `[~]` in progress ┬╖ `[x]` done

---

## Phase 0 ΓÇö Environment Setup
- [ ] Install Python (confirm version, pin it in README)
- [ ] Set up virtual environment
- [ ] Install core deps: `opencv-python`, `mediapipe`, `rapidocr`, `onnxruntime`, `pillow`, `imageio-ffmpeg`
- [ ] ~~Install Tesseract OCR binary~~ ΓÇö **no longer required.** OCR backend is RapidOCR on ONNX Runtime (DECISIONS.md D17, supersedes D6); its ONNX models ship inside the `rapidocr` wheel, so `pip install rapidocr onnxruntime` is the whole OCR setup (fully offline, no separate binary).
- [ ] Confirm ffmpeg is accessible (via `imageio-ffmpeg` or system install)

## Phase 1 ΓÇö Core Pipeline (plain scripts, no GUI yet)
- [x] `core/face_detector.py` ΓÇö `detect_faces(frame) -> list[bbox]` using MediaPipe
- [x] Test face detector standalone on a still image with 1 face, confirm bbox accuracy
  - Validated: `tests/test_face_detector.py` (encodes TESTING.md 3.1) ΓÇö `5 passed` with MediaPipe 0.10.21 + `tests/assets/single_frontal_face.jpg`. See ISSUE-001 (resolved).
- [x] Test face detector on a still image with multiple faces
  - Validated: `tests/test_face_detector.py::TestFaceDetectorMultipleFaces` (encodes TESTING.md 3.1 "multiple faces") ΓÇö `9 passed` with MediaPipe 0.10.21 against `tests/assets/multiple_faces.jpg` (3 faces detected, all bboxes within bounds; requires majority >= 2). Env override: `PIXELVEIL_TEST_MULTI_FACE_IMAGE`.
- [x] Test face detector on an angled/partial face ΓÇö confirm known limitation, log behavior
  - Validated: `tests/test_face_detector.py::TestFaceDetectorAngledFace` ΓÇö characterization test against `tests/assets/angled_face.jpg`. Observed: **0 faces detected (angled face missed)** on MediaPipe 0.10.21; asserts invariants only (returns list, boxes within bounds), does not force a detection. Logged as accepted v1 limitation ISSUE-002.
- [x] `core/ocr_detector.py` ΓÇö `detect_text(frame) -> list[(text, bbox)]` using RapidOCR (ONNX Runtime)
  - Backend swapped from the originally planned Tesseract/pytesseract to RapidOCR on ONNX Runtime (DECISIONS.md D17, supersedes D6). Public interface unchanged; RapidOCR-specific objects normalized to `(text, (x,y,w,h))` inside the module, nothing leaks to callers. `rapidocr` 3.9.2 / `onnxruntime` 1.28.0, bundled PP-OCRv6 models, fully offline.
- [x] Test OCR detector standalone on a still frame with a visible email/phone/card number
  - Validated: `tests/test_ocr_detector.py` ΓÇö `10 passed`. Covers normal UI text, email, phone, IPv4, credit card, small text, plus None/empty/blank-frame guards and a no-text graphics frame. All returned bboxes asserted in-bounds. Text checked leniently (key token present). Frames synthesized with OpenCV at test time (no fixtures, no network).
- [x] Validate OCR detector against a realistic application screenshot
  - Validated: `tests/test_ocr_detector.py::TestOCRDetectorRealScreenshot` against `tests/assets/ocr_real_screen.png` (1536├ù1024 mock PixelVeil dashboard). `17 passed` total. All 5 planted values recognized exactly, each in its own in-bounds box (labels split from values ΓÇö the label/value split is expected and accounted for): Name `John Doe`, Email `john.doe@example.com`, Phone `9876543210`, IPv4 `192.168.1.105`, Card `4111 1111 1111 1111`. Representative UI subset (`PixelVeil Test Account`, `Account Information`, `Account Settings`, `Privacy Configuration`) also detected. `core/ocr_detector.py` unchanged ΓÇö no implementation bug found.
- [x] `core/pii_matcher.py` ΓÇö regex patterns for email, phone, credit card, IP
  - Implemented: `is_email()`, `is_phone()` (US 10-digit), `is_card()` (13-19 digits), `is_ipv4()`. Built on Python's `re` module per D7. Deliberately permissive (bias toward recall) ΓÇö false positive only sends an extra box to the redactor; false negative is a privacy failure.
- [x] Unit test each regex pattern against valid + invalid sample strings
  - Validated: `tests/test_pii_matcher.py` ΓÇö `16 passed, 45 subtests`. Each pattern tested against known-good PII formats (multiple variants) and clearly-invalid strings. Covers embedded text (e.g. "Email: user@example.com"), None input, and edge cases. Fast, deterministic, offline (no OCR machinery, just string matching).
- [x] `core/redactor.py` ΓÇö draw blur, solid box, and fake-data text onto a frame given bboxes
  - Implemented as a **rendering-only** layer: `blur_region(frame, bbox)`, `box_region(frame, bbox, color)`, `fake_data_region(frame, bbox, text, ...)`. Operates on a supplied bbox; for fake-data the caller supplies the already-generated replacement string (redactor does NOT generate fake data, detect faces, run OCR, match PII, or process video ΓÇö those belong to fake_data.py / video_pipeline.py). Boxes clamped to frame; edge/partial/zero-area/off-frame boxes handled safely (no-op or clamp). Frames modified in place. Note: the old stub docstring described an orchestration signature (`redact(frame, face_boxes, pii_matches, zones, mode)`) ΓÇö that orchestration belongs to video_pipeline.py, which knows a bbox's source and the active mode; the rendering layer only draws.
  - Validated: `tests/test_redactor.py` ΓÇö `14 passed, 3 subtests`. Blur obscures + reduces variance; solid box covers; fake-data covers original and draws supplied text; outside pixels unchanged; boundary / partial-out-of-frame / negative-origin / zero-area / fully-off-frame / None/empty-frame cases handled without crashing.
- [x] `utils/fake_data.py` ΓÇö generate placeholder text per PII type (fake name, fake email, etc.)
  - Implemented: `generate(pii_type)` for the four types pii_matcher.py detects ΓÇö "EMAIL", "PHONE", "CARD", "IP" (case-insensitive). Generation-only (no OCR/matching/rendering); output feeds redactor.fake_data_region() as the replacement string. Uses stdlib `random` (no new dep). Values are clearly synthetic yet natural-looking: `example.com` emails (RFC 2606), `192.0.2.x` IPs (RFC 5737 TEST-NET-1), `555-01xx` phones (fictional block), non-Luhn `4000 ...` cards. Unsupported/invalid types raise `ValueError`. **Name is intentionally not a supported type** ΓÇö pii_matcher.py has no name detection and D7 defers names/NER to v2, so nothing upstream flags a name region; the redactor's "Test User 1" was illustrative only.
  - Validated: `tests/test_fake_data.py` ΓÇö `11 passed, 16 subtests`. Each type non-empty + correct shape (cross-checked against pii_matcher's is_* functions), synthetic-safety markers, invalid/non-string type raises, repeated generation stays valid and varies.
- [x] `core/zone_manager.py` ΓÇö store/apply user-defined static zones to a frame
  - Implemented `ZoneManager`: `add_zone(bbox)` (validates 4-tuple + positive area, coerces to int, returns index), `remove_zone(index)`, `get_zones()`, `clear()`, and `apply_zones(frame, mode="blur"|"box", color)`. Zones are `(x,y,w,h)` in video-frame pixel coords (canvasΓåÆpixel mapping is the caller/GUI's job, not this module's). Application **reuses core.redactor** (`blur_region`/`box_region`) ΓÇö no duplicated redaction logic ΓÇö so edge/partial/off-frame clamping is inherited. fake-data mode intentionally not offered for zones (a zone is a region, not a typed PII value). No detection/OCR/matching/fake-data/video/GUI logic added.
  - Validated: `tests/test_zone_manager.py` ΓÇö `19 passed, 4 subtests`. Storage (add/remove/get/clear/validation), box + blur application, exact coordinate bounds (no off-by-one bleed), multiple zones, boundary/partial-out-of-frame/fully-off-frame/no-zones, invalid mode, and same-zones-applied-consistently-across-frames. Redactor suite still `14 passed` (no regression from the new import).
- [x] `core/video_pipeline.py` ΓÇö orchestrate: read frame ΓåÆ detect (face + OCR sampled) ΓåÆ match PII ΓåÆ redact ΓåÆ write frame
  - Implemented `process_video(input_path, output_path, mode="blur"|"fake_data", zones=None, ocr_sample_rate=1, progress_callback=None) -> summary dict`. **Orchestration only** ΓÇö reuses each component's existing public API (face_detector, ocr_detector, pii_matcher, redactor, ZoneManager, fake_data) with zero duplicated detection/OCR/matching/drawing/generation logic. Per-frame sequence: detect faces ΓåÆ detect text ΓåÆ classify PII ΓåÆ **blur faces (always, regardless of mode)** ΓåÆ redact matched PII (blur, or fake_data.generate() ΓåÆ redactor.fake_data_region()) ΓåÆ apply static zones ΓåÆ write frame. Reads/writes via OpenCV, preserves dimensions + FPS (0-fps containers fall back to 25). Invalid mode / unopenable input raise ValueError; cap + writer released in a `finally`. Returns counts (frames_processed, faces_blurred, pii_by_type, zones_applied).
  - Validated: `tests/test_video_pipeline.py` ΓÇö `10 passed`. Round-trip on tiny synthetic mp4s (frame count, dimensions/FPS preserved, invalid-input raises + no output, invalid-mode raises, progress callback per frame) + mock-wiring tests (faces always blurred even in fake_data mode, fake_data routes EMAILΓåÆgenerate("EMAIL")ΓåÆfake_data_region, blur mode blurs PII, non-PII text ignored, static zones applied every frame). No component logic duplicated (asserted via mocks).
  - **Deferred (next two TASKS.md items, intentionally not implemented here):** OCR every-N-frame sampling + bbox persistence, and ffmpeg audio mux. `ocr_sample_rate` is accepted for API stability but not yet honored (OCR runs every frame); output is the OpenCV video-only intermediate.
- [x] Implement frame-sampling logic for OCR (every N frames) with bbox persistence between samples
  - Implemented in `core/video_pipeline.py`: `ocr_sample_rate` is now functional. OCR (`ocr_detector.detect_text` ΓåÆ `pii_matcher` classify) runs only on frames where `frame_index % ocr_sample_rate == 0` (frames 0, N, 2N, ...). Between samples the last PII detections are persisted as `(pii_type, bbox, replacement)` and re-applied every frame (architecture.md 6.4ΓÇô6.5, 7). `ocr_sample_rate=1` is the previous every-frame behavior (backwards compatible). Face detection and static zones still run **every** frame. In fake-data mode the generated replacement string is produced once at sample time and persisted (D18) to avoid per-frame flicker. `ocr_sample_rate` is validated as a positive integer (bool/float/str/None/<1 ΓåÆ ValueError) before the video is opened, so no output is written on bad input. `process_video()` API and summary/progress keys unchanged.
  - Validated: `tests/test_video_pipeline.py` ΓÇö `20 passed, 12 subtests` (10 new sampling tests: rate-1-every-frame, rate-N-only-on-sampled-frames, bbox persists between samples, persisted PII stops on empty sample, persisted PII updates on changed sample, fake-data value persisted/generated-once, faces every frame, zones every frame, summary+progress reflect persistence, invalid-rate rejection). Regression: redactor/zone_manager/fake_data/pii_matcher suites still `60 passed`.
  - Between-samples miss for moving/scrolling text recorded as accepted v1 tradeoff ISSUE-003 (TESTING.md 3.2).
- [x] Implement intermediate video write (OpenCV) ΓåÆ ffmpeg mux with original audio
  - Implemented in `core/video_pipeline.py` (D8): processed frames are written to a temporary video-only intermediate (`pixelveil_*.mp4`, created next to the final output via `tempfile.mkstemp`), then a private `_mux_audio()` invokes the ffmpeg binary bundled with **imageio-ffmpeg** (`imageio_ffmpeg.get_ffmpeg_exe()`, already a project dep ΓÇö no new dependency) to mux the processed video with the **original** input's audio into `output_path`. ffmpeg is called via a `subprocess.run` **argument list** (no shell string, no `shell=True`); streams are copied (`-c:v copy -c:a copy`, original audio not reprocessed); audio mapping is optional (`-map 1:a:0?`) so a source with **no audio** still yields a valid video-only output; `-shortest` guards against audio outlasting video. Non-zero ffmpeg exit ΓåÆ `RuntimeError` carrying ffmpeg's stderr. The intermediate is removed in a `finally` on **every** path (success, mux failure, or mid-processing error). `process_video()` API, OCR sampling/persistence, face/PII redaction, zones, summary, and progress are unchanged.
  - Validated: `tests/test_video_pipeline.py::TestProcessVideoAudioMux` ΓÇö `27 passed, 12 subtests` total. Covers: source-with-audio ΓåÆ output has audio (real ffmpeg, synthesized sine+color fixture); source-without-audio ΓåÆ valid playable video-only output; processed video stream intact (dims/fps/frame-count survive write+copy); temp cleaned up on success; ffmpeg failure ΓåÆ RuntimeError + temp cleaned; temp cleaned on mid-processing error; ffmpeg called with a safe arg list (no shell). Regression: existing 20 pipeline tests + redactor/zone_manager/fake_data/pii_matcher `60 passed` all still green.
  - Limitation: audio in a codec that can't be stream-copied into MP4 fails the mux (no re-encode fallback in v1) ΓÇö ISSUE-004.

## Phase 2 ΓÇö Pipeline Validation (before touching any UI)
- [x] Build 2-3 test videos with planted PII (see TESTING.md for exact cases)
  - Built all 5 TESTING.md ┬º2 fixtures under `tests/sample_videos/` via a single deterministic OpenCV generator, `tests/make_sample_videos.py` (no randomness/network/downloads; regenerate rather than commit ΓÇö the MP4s are already git-ignored by `tests/sample_videos/*.mp4`). All 960├ù540, 10 fps, 60 frames (6.0 s), 167ΓÇô393 KB. Frames drawn with OpenCV; audio is a deterministic sine tone muxed via the existing imageio-ffmpeg dep on the two fixtures that need it.
    - `test_faces_basic.mp4` ΓÇö `single_frontal_face.jpg` fit to frame, static. Ground truth: **1 frontal face** (sanity-checked: `detect_faces` ΓåÆ 1). No audio.
    - `test_faces_multi.mp4` ΓÇö `multiple_faces.jpg` fit to frame, static. Ground truth: **3 faces** (sanity-checked: `detect_faces` ΓåÆ 3). No audio.
    - `test_pii_text.mp4` ΓÇö mock "Acme Admin" dashboard. Ground truth PII (all reserved/doc values): EMAIL `john.doe@example.com`, PHONE `9876543210`, IP `192.168.1.105`, CARD `4111 1111 1111 1111` (sanity-checked: OCR reads all four exactly). **Audio: yes** (440 Hz sine).
    - `test_mixed.mp4` ΓÇö `single_frontal_face.jpg` (1 face) + static PII panel (EMAIL `john.doe@example.com`, PHONE `9876543210`) + a **scrolling** bottom ticker carrying CARD `4111 1111 1111 1111` / IP `192.168.1.105` that moves each frame ΓÇö the intended repro for ISSUE-003 (moving PII between OCR samples). **Audio: yes** (330 Hz sine).
    - `test_zones.mp4` ΓÇö mock "CRM Workspace" whose left sidebar panel sits at **fixed pixel coords `(x=20, y=70, w=260, h=430)` on every frame** (a moving ticket counter + circle elsewhere prove the panel is static while the rest changes). No PII, no audio ΓÇö isolates static-zone behavior.
  - Not run yet (next Phase 2 items): full end-to-end pipeline / acceptance scoring, blur-vs-fake-data confirmation, audio-in-sync check.
- [x] Run full pipeline end-to-end on each test video
  - Validated via `tests/phase2_validate.py` (reporting harness ΓÇö runs the **real** `process_video()`, no mocked detectors/redactors; inspects OUTPUT videos). Ran all 5 fixtures 2026-08-04. Regression suite `python -m pytest tests/test_*.py` ΓåÆ `113 passed`.
- [x] Confirm: all planted faces blurred
  - basic: 1/1 face blurred every frame; multi: 3/3 every frame. Face-region Laplacian variance collapses inΓåÆout (basic 250ΓåÆ14, multi 235ΓåÆ14, mixed 736ΓåÆ38 Γëê ΓêÆ94%), i.e. heavy blur. NOTE: MediaPipe still *localizes* a blurred face-blob in 60/60 output frames ΓÇö that is the detector firing on the blur, not an unredacted face (region variance confirms it is blurred). Not a miss/bug; recorded for transparency.
- [x] Confirm: all planted PII detected and handled (both blur mode and fake-data mode)
  - `test_pii_text.mp4`: all four planted values (EMAIL/PHONE/IP/CARD) OCR-readable in **0/60** output frames in **both** blur and fake_data modes; pipeline `pii_by_type` = 60 each. Ordinary text ("Acme Admin", "Name: John Doe") was NOT mis-flagged ΓÇö no false positives on non-PII text.
- [x] Confirm: output video plays correctly with audio intact
  - All outputs open in OpenCV; resolution/fps/frame-count/duration preserved (960├ù540 / 10 fps / 60 f / 6.0 s). Audio present in `test_pii_text`/`test_mixed` outputs, absent for the no-audio sources (correct). Equal source/output duration ΓåÆ sync reasonable (full A/V-sync spot-check is a manual VLC/WMP step per TESTING.md ┬º3.5).
- [x] Log and review any false negatives/positives ΓÇö do not proceed to UI until miss rate is understood and acceptable (see TESTING.md acceptance criteria)
  - **Static content passes at ~100%** (faces, static PII both modes, static zone). **Moving-ticker miss quantified** (ISSUE-003, expected model/sampling limitation, NOT tuned around): moving CARD redacted on 27/60 frames (rate 1) ΓåÆ 25/60 (rate 5); moving IP on 3/60 (rate 1) ΓåÆ 0/60 (rate 5) ΓÇö fast-scrolling text is only OCR-readable on a subset of frames, so it is only detected/redacted on those frames. Static zone: interior variance 633ΓåÆ0.7 (fully blurred) with adjacent strip 219ΓåÆ221 (untouched), applied 60/60 frames. See known-issues ISSUE-003 (updated with these numbers) and the measurement caveat there.

## Phase 3 ΓÇö Test Harness UI (Flask + HTML, per design.md)
- [x] Minimal Flask app skeleton, serves 4 screens (Upload / Processing / Results / Settings)
  - Built on the existing `tools/webtest/` skeleton (no second app). Added `templates/base.html` with a simple top nav (4 tabs + active-state highlight, single-column layout per design.md ┬º3); rewrote `upload/processing/results/settings.html` to extend it with **static placeholder content** matching each screen's purpose (design.md ┬º2). Expanded `static/css/style.css` to the design.md ┬º1 light theme (system font, one blue accent `#2563EB`, thin `#E5E5E5` borders, generous whitespace, mono log panel only). `server.py` routes now pass an `active` tab var for nav highlighting; four routes unchanged in path (`/`ΓåÆUpload, `/processing`, `/results`, `/settings`). Flask + Jinja + plain CSS only ΓÇö **no new dependencies**, `static/js/app.js` left as the existing stub.
  - Validated: Flask test client ΓÇö all 4 routes return **HTTP 200**, each renders the nav with its own active tab, cross-page links resolve. Core suite `python -m pytest tests/test_*.py` ΓåÆ `113 passed` (no `core/` files touched; module boundary respected).
  - Deliberately NOT done here (later Phase 3 items): upload/drag-drop, mode toggle wiring, zone drawing, `video_pipeline.py` wiring, progress streaming, live log, frame preview, results playback/download, issue logging, settings persistence. All controls are rendered `disabled` as placeholders.
- [x] Upload screen: file picker/drag-drop, mode toggle, zone-drawing canvas on first frame
  - Built on the existing `tools/webtest/` harness. Upload accepts a local video via **file picker and drag/drop**; two-stage validation ΓÇö extension allowlist (`.mp4/.mov/.mkv/.avi/.webm/.m4v`) then a **real OpenCV decode of frame 0** (rejects a non-video file that merely has a video extension, with a clear message). On success the first frame is extracted server-side and shown on a `<canvas>`; the user **click-drags rectangular static zones**, each listed below the canvas with an individual **Delete** button. The Blur / "Replace with fake data" mode toggle is preserved and pushed to the server on change. **Process Video** is disabled until a valid video is loaded and then hits a controlled **HTTP 501 placeholder** ΓÇö `process_video()` is deliberately not called (that is the next task). Selected video path, mode, and zones are held per-upload in a process-local `_STATE` dict, ready for the pipeline-wiring task.
  - **Coordinate mapping (the important part):** the displayΓåÆ**original-video-pixel** conversion is done **server-side** in `/zone` (D19), where the true video dimensions are known, so a resized/scaled canvas can never desync the mapping. Per-axis scale is computed independently (handles non-uniform resize), edges are scaled then clamped to the frame, and the result is stored as an `[x,y,w,h]` list in video pixels ΓÇö exactly `ZoneManager.add_zone()`'s expected format (proven by a test that feeds a stored zone straight into `ZoneManager`). New pure module `tools/webtest/upload_support.py` holds the validation + coordinate math with **no Flask import** so it is unit-testable in isolation. No new dependencies; `core/` untouched.
  - Validated: `tests/test_webtest_upload.py` ΓÇö **26 passed** (extension allowlist, rect normalization, displayΓåÆvideo conversion incl. identity / uniform 2├ù / non-uniform per-axis / clamp / zero-dim raise / full-frame resize roundtrip; Flask routes via `test_client()` with real tiny mp4s: valid upload, first-frame extracted+served PNG at right size, invalid-extension 400, non-decodable-mp4 400, missing-field 400, mode persist + invalid-mode 400, Process guarded-before-upload 400 / 501-placeholder-after, zone create+delete with coordinate doubling, direct `ZoneManager` consumption, invalid delete index, zero-area zone 400, plus a real-`test_zones.mp4` fixture test mapping a half-canvas draw back to the documented `(20,70,260,430)`). Full suite `python -m pytest tests/test_*.py` ΓåÆ **139 passed, 80 subtests** (was 113; +26). `core/` untouched ΓÇö module boundary respected.
  - Deliberately NOT done here (later Phase 3 items): calling `process_video()` / pipeline wiring, Processing screen, progress/log/preview, Results, issue logging, Settings persistence.
- [x] Wire "Process Video" button to trigger `video_pipeline.py` via a Flask route
  - `/process` (POST) starts `core.video_pipeline.process_video()` in a background daemon thread (`tools/webtest/job.py` `ProcessingJob`) and returns **HTTP 202** immediately ΓÇö the request never blocks on encoding (D20). It reuses the existing Upload `_STATE` (`video_path`, `mode`, zones as `[x,y,w,h]`ΓåÆpassed as `(x,y,w,h)` tuples, exactly `ZoneManager`'s form) and reaches the pipeline **only** through its public API ΓÇö no duplicated pipeline logic in Flask. Uploaded source (`uploads/<uid>/`) and processed output (`outputs/<uid>/redacted_<name>`) are separate dirs. Guards: unknown/absent upload ΓåÆ 400; a second start while a job is active ΓåÆ **409** (one job at a time). Pipeline exceptions become a controlled error state; the returned summary is stored for the later Results task. Fully local/offline ΓÇö no Celery/Redis/DB/new dependency (D10/D20).
- [x] Processing screen: progress bar + per-stage status panel (per design.md)
  - `templates/processing.html` + `static/js/app.js` render an overall progress bar (percent / frame X of Y / elapsed / status) and a per-stage status table (face_detector, ocr_detector, pii_matcher, zone_manager, redactor, video-writer/ffmpeg-mux). Stage states and counts are derived **only** from the pipeline's `progress_callback` (`{frame,total,faces,pii}`) and returned summary ΓÇö no fabricated per-stage internals (design.md ┬º2.2 honesty; `ProcessingJob.stages()`).
- [x] Processing screen: live scrolling technical log (SSE or polling)
  - Polling (chosen over SSE per D20): `static/js/app.js` polls `/job/<uid>` ~every 500 ms and updates the progress bar, stage table, and a monospace scrolling technical log (auto-scroll with scroll-up lock to inspect a moment); polling stops on `complete`/`error` and shows the completion/error message. Log lines come from `ProcessingJob` (job-start, per-cadence frame lines, completion/error + traceback), capped at 500 lines.
  - Validated: `tests/test_webtest_processing.py` ΓÇö **15 tests** (ProcessingJob unit: arg wiring, cumulative counters, technical log, completion+summary, controlled error state, is_active-only-while-running; Flask routes with `process_video` mocked: reject-without-upload, 202 start, exact input/output/mode/zones/rate passed, non-blocking, `/job` polling of progress+log, error surface, duplicate-startΓåÆ409, restart-after-complete, unknown-id 404). `tests/test_webtest_upload.py` old 501-placeholder test rewritten to assert the 202 background-start (process_video mocked, no OCR); cleanup helper now clears `uploads/`+`outputs/` and resets `_STATE`/`_ACTIVE_JOB_UID`. Focused suites ΓåÆ **41 passed**; full suite `python -m pytest tests/test_*.py` ΓåÆ **154 passed, 80 subtests** (was 139; +15). No temp dirs left under `tools/webtest/uploads` or `outputs`. `core/` untouched ΓÇö module boundary respected.
- [x] Processing screen: live current-frame preview with detection boxes overlaid
  - `core/video_pipeline.py` gained an optional, backward-compatible `preview_callback` (a pure observability hook, no-op by default) fired **after** each `writer.write(frame)` with `{frame, frame_number, total, faces, pii, zones}` ΓÇö where `pii` is the list of `(type, bbox)` **actually applied** to that frame, i.e. freshly-sampled OR persisted between OCR samples (reported honestly either way). Because it fires post-write, a consumer drawing on the frame can never contaminate the redacted output (proven by a "vandal" test). No detection/OCR-sampling/redaction/audio-mux/summary behavior changed; no new dependency.
  - `tools/webtest/job.py`: `render_preview_jpeg()` copies the frame, downscales to Γëñ480px wide, overlays labeled boxes (green FACE / red PII-with-type EMAIL┬╖PHONE┬╖CARD┬╖IP / blue ZONE), and JPEG-encodes (quality 70). `ProcessingJob._on_preview` is throttled (every 6th frame + first + last), retains **only the latest** JPEG (never a frame history), and exposes `preview_jpeg() -> (bytes, seq)`; snapshot adds `has_preview` / `preview_seq`.
  - `tools/webtest/server.py`: `GET /job/<uid>/preview` returns 404 before a preview exists, else the latest JPEG (`image/jpeg`, `Cache-Control: no-store`). The image is **never** base64'd into the `/job/<uid>` poll JSON (D21).
  - `templates/processing.html` + `static/js/app.js`: static placeholder replaced with a preview `<img>` + placeholder; the poll reads `has_preview`/`preview_seq` and refreshes the image (from the separate endpoint, seq as cache-buster) **only when `preview_seq` changes**.
  - Validated: `tests/test_video_pipeline.py::TestProcessVideoPreviewCallback` (5) + `tests/test_webtest_processing.py::TestPreviewFeature` (5). Focused suites `test_video_pipeline.py`+`test_webtest_processing.py` ΓåÆ **52 passed**; upload regression `test_webtest_upload.py` ΓåÆ **26 passed**; full suite `tests/test_*.py` ΓåÆ **164 passed** (was 154; +10). `core/` change is the minimal preview hook only. See DECISIONS.md D21.
- [x] Results screen: before/after video preview, summary panel, download button
  - `tools/webtest/server.py`: reached via `GET /results?job=<uid>`; renders the real `pipeline_summary` stored on the completed `ProcessingJob`. Videos served through **controlled routes keyed by upload id** ΓÇö `GET /video/<uid>/original` and `GET /video/<uid>/processed` (paths come from server-owned `_STATE`, never from the request), plus `GET /download/<uid>` which streams the completed output as an attachment preserving its real filename. No arbitrary filesystem path is ever accepted from the client. States handled: unknown job / still running (409 on processed video, notice on page) / failed / completed-but-output-missing all render an error block instead of players. No new dependency; no `video_pipeline` logic duplicated (Flask only reads existing job state).
  - Validated: `tests/test_webtest_results.py` ΓÇö 14 passed (renders results, both video routes, download name/type, summary uses real job data, unknown/running/failed/missing-output handled, arbitrary path rejected). Full suite `tests/test_*.py` ΓåÆ **178 passed** (was 164; +14).
  - **Scope note:** the design.md "Flag an issue" logging control was intentionally dropped for this developer-only harness ΓÇö manual misses are recorded directly in `docs/known-issues.md`. See DECISIONS.md D22.
- [x] Settings screen: OCR sampling rate, face confidence threshold, editable regex list
  - **Functional, not just UI** ΓÇö a saved value actually changes what a newly started job does. Minimal, backward-compatible core-API extensions only (no detector/model/backend change, no new PII categories, no new dependency).
  - `core/pii_matcher.py`: added an active-patterns layer ΓÇö `get_patterns()`/`get_default_patterns()`/`set_patterns()`/`reset_patterns()` over a `_active_patterns` dict; the four `is_*()` functions now consult it. `set_patterns()` compiles **all-or-nothing** (a bad regex or unknown type raises `ValueError` and never touches the active patterns), so an invalid edit can't corrupt matching. Defaults unchanged until overridden.
  - `core/face_detector.py`: exposed `DEFAULT_MIN_CONFIDENCE` (public alias of the existing internal default); `detect_faces(min_confidence=ΓÇª)` already existed.
  - `core/video_pipeline.py`: `process_video()` gained optional `face_min_confidence=None` (validated to `[0.0, 1.0]`); when `None` the detector's own default applies (unchanged behavior), else it is forwarded to `face_detector.detect_faces(min_confidence=ΓÇª)`. OCR sample rate already flowed through.
  - `tools/webtest/settings_store.py` (new): process-local settings (threading.Lock-guarded module dict, D10 ΓÇö no DB/accounts/Redis/config-service/dependency). Validates OCR rate (positive int) + face confidence ([0,1]) all-or-nothing; PII patterns pushed into `pii_matcher`. `processing_kwargs()` feeds a new job; `reset_settings()` restores defaults (incl. `pii_matcher.reset_patterns()`).
  - `tools/webtest/job.py` + `server.py`: `ProcessingJob` gained `face_min_confidence`; `/process` reads `settings_store.processing_kwargs()` at start so a job always uses the latest saved tuning. Routes: `GET /settings` (renders current+default), `GET /settings/values` (JSON), `POST /settings` (validate+apply, 400 on invalid, last-valid config kept), `POST /settings/reset`.
  - `templates/settings.html` + `static/js/app.js` + `static/css/style.css`: functional controls (OCR number input, confidence slider, four PII regex inputs), Save/Reset, inline success/error feedback ΓÇö existing design language, no redesign.
  - Validated: `tests/test_webtest_settings.py` (new, 11 tests: page renders current/default, valid save, invalid OCR/confidence/regex rejected without corrupting current, reset restores defaults, saved OCR+confidence reach `process_video`, default job uses pipeline defaults, saved regex changes `pii_matcher` matching), `tests/test_pii_matcher.py::TestConfigurablePatterns` (+9: get/set/reset, all-or-nothing, unknown-type/empty rejected), `tests/test_video_pipeline.py::TestFaceMinConfidence` (+3: default passes no override, custom reaches `detect_faces`, invalid rejected). All tests restore process-global settings in tearDown (no leak across files). Focused ΓåÆ **37 passed, 60 subtests**; full `python -m pytest tests/test_*.py` ΓåÆ **199 passed, 95 subtests** (was 178; +21).

- [x] Phase 3 polish / bug-fix pass ΓÇö blank Results videos, duplicate button, nav loses job
  - **Blank Results videos (root cause = codec).** The Results `<video>` players showed controls + duration but a blank image; download played fine externally and the `/video/<uid>/*` routes returned 206. Cause: the pipeline's OpenCV intermediate is `mp4v` (MPEG-4 Part 2) and `_mux_audio` copied that stream (`-c:v copy`), so the final MP4 carried an mp4v video track ΓÇö which HTML5 `<video>` in Chrome/Edge/Firefox cannot decode (VLC/QuickTime can, hence "download plays"). Fix in `core/video_pipeline.py::_mux_audio`: the ffmpeg step that already runs now transcodes video to **H.264** (`-c:v libx264 -pix_fmt yuv420p -movflags +faststart`); audio still stream-copied (`-c:a copy`). No detection/OCR/redaction change ΓÇö identical pixels, browser-decodable codec. **Residual:** the *original* preview is the user's uploaded file served as-is, so it renders only if the source codec is browser-supported; the OpenCV-written `mp4v` sample fixtures (e.g. `tests/sample_videos/*.mp4`) still show blank-but-controls in-browser though they download/play externally ΓÇö real H.264 screen recordings render fine. Not hidden with CSS; reported as ISSUE-005.
  - **Duplicate "View results".** `templates/processing.html` rendered a static fallback `<a>View results</a>` (no job id) in addition to the primary one `static/js/app.js` injects into `#processingDone` on completion. Removed the static anchor ΓÇö one clear completion action remains (JS-injected, `/results?job=<uid>`).
  - **Navigation lost the active job.** The top-nav Processing/Results links were bare (`/processing`, `/results`), so clicking them mid-job dropped the job id ΓåÆ idle/"Unknown job", forcing a re-upload. The background `ProcessingJob` was never actually affected (it runs on a daemon thread off the request), so this was purely a link-context bug. Fix: `server.py` `_current_job_uid()` (prefers the page's `?job=` param, else `_ACTIVE_JOB_UID`, only if state+job exist) + an `@app.context_processor` injecting `active_job_uid`; `templates/base.html` Processing/Results tabs now carry `?job=<uid>` when a job exists (Upload/Settings stay bare). Merely GETting a page never starts/stops/replaces a job; `process_video()` still runs exactly once per started job. No UID hardcoded in HTML/JS.
  - Validated: `tests/test_webtest_navigation.py` (new, 12 tests: nav carries job while running / after completion, job survives visiting Upload & Settings, returning to Processing reuses the same job object, navigation doesn't restart `process_video` (1 call), no-job links stay bare, completed job reachable via Results nav, Results-before-completion shows "still running" + back link, video/download routes still serve after navigating, completed job not cleared when polling stops, no static View-results anchor, app.js has exactly one). `core/video_pipeline.py` (+2 codec tests: output is H.264 with/without audio; mux args assert `libx264`). Focused webtest suites ΓåÆ **82 passed**; full `python -m pytest tests/test_*.py` ΓåÆ **213 passed, 95 subtests** (was 199; +14). See ISSUE-005.

- [x] Face anonymization upgrade (Shape, Method, and Intensity)
  - **What changed:** Upgraded face redaction to an oval, face-oriented privacy mask that fully covers the forehead, cheeks, and chin. Added support for `method="blur"` and `method="pixelate"`. Blur has configurable `intensity` (`low`, `medium`, `high`) scaled dynamically to face size. Pixelation has low/medium/high options removed and is pinned to a single standard divisor of 17 (`w // 17`). Exposed new controls on the Upload screen (Method, Blur Intensity, Standard Pixelate Intensity) with auto-save on change and click-time override of job settings, keeping settings clean and accurate. For multi-pass comparison jobs, `frames_processed` is aggregated by summing the count from all passes (240 total for a 120-frame video), while unique detection counts (faces, PII, zones) are kept single-pass to prevent duplication.
  - Validated: Added `tests/test_redactor.py::TestRedactFace` to verify mask geometry, blur application, and pixelate application. Updated `tests/test_video_pipeline.py` to assert `redact_face` usage for face detections. Added a parameter sweep utility `tests/pixelate_sweep.py` to tune the pixelation progression. Full test suite passed without regressions.
- [x] Bug fix ΓÇö label+value in one OCR box redacted the whole box (only redact the PII value)
  - **Root cause.** `ocr_detector.detect_text()` returns one `(text, bbox)` per recognized line, so a box can hold a label + value ("Email: john.doe@example.com"). `video_pipeline._classify_pii()` only returned the PII **type** (the `pii_matcher.is_*()` functions use `.search()` and throw the match position away), and the pipeline then sent the **full OCR bbox** to `redactor`, blurring/covering the label too. Verified from code ΓÇö the match span existed inside `pii_matcher` but never escaped.
  - **Fix (minimal, additive).** `core/pii_matcher.py`: new `find_pii(text) -> list[(pii_type, start, end, value)]` built on `finditer()` match spans, with overlap resolved by a documented precedence (EMAIL, IP, CARD, PHONE ΓÇö same order the pipeline classified in before) so a value-only box still classifies identically. The `is_*()` functions are unchanged. `core/video_pipeline.py`: new `_span_to_bbox(ocr_bbox, text, start, end)` maps a character span to a tighter horizontal sub-region of the OCR box by proportional character position (deterministic, bounded by the box, y/h preserved); the OCR-sampling loop now iterates `find_pii()` and redacts each value's tightened bbox. A value-only box (`span == [0, len]`) yields the original bbox integer-exact, so all prior behavior/tests hold. Multiple values in one box each get their own region (req 8); label/value in **separate** boxes still works (label box has no PII ΓåÆ untouched, req 9); the tightened bbox is what persists between OCR samples and what fake-data mode covers (reqs 10ΓÇô11). `_classify_pii`/`_PII_CLASSIFIERS` removed (superseded by `find_pii`).
  - **Documented limitation.** RapidOCR gives per-line boxes, not per-glyph, so `_span_to_bbox` approximates character width uniformly ΓÇö value edge can be a few px off with proportional fonts, but always stays inside the box and covers the value. Recorded as ISSUE-006 (not hidden with permissive tests).
  - Validated: `tests/test_pii_matcher.py::TestFindPii` (+10) and `tests/test_video_pipeline.py::TestValueOnlyRedaction` (+11). Focused `test_pii_matcher.py`+`test_video_pipeline.py` ΓåÆ **82 passed, 70 subtests**; full `python -m pytest tests/test_*.py` ΓåÆ **234 passed, 100 subtests** (was 213; +21), no regressions. **Real-video validation** (`test_mixed.mp4`, which draws `"Email: " + value` as one string ΓåÆ single OCR box `(445,98,345,32)`): blur mode ΓåÆ label region sharpness retained **100%**, value region **0%**; fake-data mode ΓåÆ label region mean|╬ö| **3.23** (untouched) / value **57.75** (replaced), and OCR of the output label crop reads `Email:`.

- [x] Fake-data quality ΓÇö style-aware, background-reconstructing replacement (D14 USP), replacing solid-white-fill + fixed black text
  - **What changed.** In fake_data mode the pipeline now (1) estimates the source value's style **before** destroying it, (2) removes it by classical inpainting instead of a flat fill, and (3) redraws the synthetic value in the estimated colour/size. `core/redactor.py`: new `estimate_text_style(frame, bbox)` (k-means k=2 fg/bg colour; Otsu + minority-polarity external-contour trace for glyph height; baseline/width) and `inpaint_region(frame, mask, method)` (OpenCV `cv2.inpaint`, `"telea"` **or** `"ns"`, radius 3); `fake_data_region()` gained optional `inpaint_method` + `style` and now inpaints (or solid-fills when neither given ΓÇö backward-compatible) then draws the replacement in the style's fg colour on the reconstructed bg, sized to the estimated height (`FONT_HERSHEY_SIMPLEX` cap Γëê `height/22`, width-fitted). `core/video_pipeline.py`: `process_video(inpaint_method="telea")`; the fake_data branch estimates style at sample time and persists `(pii_type, value_bbox, replacement, style)` (extends D18), forwarding `inpaint_method`+`style` to `fake_data_region`. `utils/fake_data.py`: `generate(pii_type, original=None)` ΓÇö phone/card mirror the source separator/grouping; email/IP accept `original` for API parity. See DECISIONS.md **D24**.
  - **Two genuine defects fixed while landing this (bug fixes, not behaviour changes).** (1) `estimate_text_style` chose contour polarity by cluster-centre brightness, which traced the **background** blob so `text_height` collapsed to the full box height ΓÇö replaced with the polarity-agnostic minority-pixel rule (scale 0.6 ΓåÆ ~10 px, 0.4 ΓåÆ ~7 px, was ~28 px box height). (2) Replacement scale used `target_height/40`, ~40 % too small for Hershey's real cap height ΓÇö corrected to `target_height/22` (measured via `cv2.getTextSize`).
  - **Both inpainting methods kept, no winner chosen.** TELEA and Navier-Stokes are both surfaced via `inpaint_method` (default `"telea"`) for manual quality comparison. Two comparison renders produced from `tests/sample_videos/test_mixed.mp4` in fake_data mode ΓÇö `tests/sample_videos/test_mixed_fake_telea.mp4` and `..._fake_ns.mp4` (git-ignored, kept on disk for human review). Both: 60 f / 960├ù540 / H.264+yuv420p; Email/Phone labels OCR-visible; originals `john.doe@example.com`/`9876543210` removed; replacement present and dark-on-light preserved; inpainted panel background Γëê 248 (source panel Γëê white). Source has no audio ΓåÆ video-only output (correct).
  - **Honest limitations (not "seamless").** Colour/height are heuristic; the replacement is always Hershey, not the source font (no font-family reconstruction attempted); classical inpainting can smear on textured backgrounds; at `ocr_sample_rate=1` the randomized value regenerates per frame (flicker) ΓÇö persistence (D18) only stabilizes it between samples when rate > 1. Recorded as **ISSUE-007**. No GAN/diffusion/LaMa (out of scope).
  - Validated: `tests/test_fake_data_quality.py` (new, **26 passed**), `tests/test_redactor.py` (**14 passed**), `tests/test_fake_data.py` (**11 passed**), `tests/test_video_pipeline.py` incl. new `TestFakeDataStylePersistence` (**50 passed**). Full `python -m pytest tests/test_*.py` ΓåÆ **262 passed, 100 subtests** (was 234; +28), no regressions. Also fixed a missing `import shutil` in `tests/test_video_pipeline.py` (used by the new tearDown).

- [x] Test-harness dual-output ΓÇö process fake_data twice (TELEA + NS) for manual comparison (D25)

### 4. GPU Acceleration (Production-Ready)
- [x] Determine safe method to discover CUDA on Windows without crashing ORT.
- [x] Configure ORT `InferenceSession` for `CUDAExecutionProvider` with `CPUExecutionProvider` fallback.
- [x] Implement robust PyTorch CUDA DLL loading module-level configuration to prevent deadlocks.
- [x] Implement graceful fallback logic if CUDA fails at runtime.
- [x] Verify actual GPU inference speedup against CPU.

### 5. Local SCRFD Evaluation (Research Only)
- [x] Ensure we NEVER package or distribute InsightFace weights.
- [x] Implement local script to download SCRFD-500M safely (`tools/download_scrfd.py`).
- [x] Integrate SCRFD-500M backend into `face_detector.py`.
- [x] Run comprehensive latency and recall benchmarks (`tools/benchmark_face_detectors.py`).
- [x] Compare MediaPipe, YuNet, and SCRFD metrics and document findings.

## Phase 4 ΓÇö Packaging (Windows .exe)
- [ ] Set up PyInstaller build config
- [ ] ~~Bundle Tesseract binary into `assets/`~~ ΓÇö **not needed.** RapidOCR's ONNX models ship inside the `rapidocr` wheel; PyInstaller just needs to collect the `rapidocr` package data (no external OCR binary). See DECISIONS.md D17.
- [ ] Test packaged .exe on a clean Windows machine (not your dev machine)
- [ ] Check for antivirus/Defender false-positive flagging ΓÇö plan mitigation (code signing / vendor allowlisting) if it occurs

## Phase 5 ΓÇö Pre-Launch
- [ ] Post concept/demo clip in target communities (r/QualityAssurance, r/CustomerSuccess, r/sysadmin, Indie Hackers) ΓÇö gauge real interest
- [ ] Set up Stripe Checkout + license-key validation for Pro tier
- [ ] Write README.md (setup, usage, screenshots)
- [ ] Product Hunt launch prep

## v2 Backlog (not v1, tracked so it's not forgotten)
- [ ] Age-estimation pass for "Blur children only" mode (see DECISIONS.md + roadmap.md 9b for design principle)
- [ ] Batch processing (multiple files at once)
- [ ] EasyOCR as a heavier/more-accurate fallback mode
