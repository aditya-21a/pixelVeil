# development-log.md

Internal, chronological, short. One entry per session/significant change. This is breadcrumbs for future agents/sessions, not a narrative — a few lines per entry, not paragraphs. If you're writing more than 4-5 lines for one entry, it belongs in `docs/DECISIONS.md` (if it's a reasoned decision) or `docs/known-issues.md` (if it's a problem), not here.

---

## Format

```
## YYYY-MM-DD — <one-line summary>
- Changed: <file(s)>
- Why: <one line>
- Commit: <git hash or "uncommitted">
```

---

## Log

*(entries go here, most recent at the top)*

## 2026-08-04 — OpenCV intermediate → ffmpeg audio mux in video_pipeline.py
- Changed: core/video_pipeline.py, tests/test_video_pipeline.py; docs/current-state.md, tasks.md, known-issues.md, development-log.md
- Why: TASKS.md Phase 1 (final core-pipeline task) — attach the original audio to the redacted output per D8
- Result: frames now write to a temp video-only intermediate (`tempfile.mkstemp` next to output), then `_mux_audio()` runs bundled ffmpeg (`imageio_ffmpeg.get_ffmpeg_exe()`, existing dep) via a `subprocess.run` arg list (no shell) to mux processed video + original audio into `output_path`. `-c:v copy -c:a copy` (no re-encode), `-map 1:a:0?` (optional audio → no-audio sources still valid), `-shortest`. ffmpeg non-zero exit → RuntimeError(stderr); intermediate removed in `finally` on all paths. API/sampling/persistence/redaction/zones/summary/progress unchanged. `tests/test_video_pipeline.py` — `27 passed, 12 subtests`; regression `60 passed`.
- Note: added ISSUE-004 (no audio re-encode fallback — copy-into-mp4 only in v1). No new dependency (imageio-ffmpeg already in requirements). Approach follows D8; no new decision. This completes Phase 1 core-pipeline implementation; Phase 2 validation not started.
- Commit: uncommitted

## 2026-08-04 — OCR frame-sampling + PII bbox persistence in video_pipeline.py
- Changed: core/video_pipeline.py, tests/test_video_pipeline.py; docs/current-state.md, tasks.md, known-issues.md, DECISIONS.md, development-log.md
- Why: TASKS.md Phase 1 — make `ocr_sample_rate` functional; run OCR every Nth frame, persist PII detections between samples (architecture.md 6.4–6.5, 7)
- Result: OCR (detect_text→classify) runs only when `frame_index % ocr_sample_rate == 0`; between samples the last detections persist as `(pii_type, bbox, replacement)` and re-apply every frame. Faces + static zones still every frame. Fake-data string generated once per sample and persisted to avoid flicker (D18). `ocr_sample_rate` validated as positive int before opening the video. API/summary/progress keys unchanged; `rate=1` == prior every-frame behavior. `tests/test_video_pipeline.py` — `20 passed, 12 subtests`; redactor/zone_manager/fake_data/pii_matcher regression `60 passed`.
- Note: added ISSUE-003 (moving/scrolling text may be missed between samples — accepted tradeoff, TESTING.md 3.2) and D18 (persist rendered fake value, not just bbox). ffmpeg audio mux still deferred to the next TASKS.md item. No new deps, no architecture change.
- Commit: uncommitted

## 2026-08-04 — Implement video_pipeline.py orchestrator + tests
- Changed: core/video_pipeline.py, tests/test_video_pipeline.py (new); docs/current-state.md, tasks.md, development-log.md
- Why: TASKS.md Phase 1 — orchestrate read frame → detect faces+OCR → match PII → redact → write frame
- Result: `process_video(input, output, mode="blur"|"fake_data", zones, ocr_sample_rate, progress_callback) -> summary`. Orchestration only — reuses face_detector/ocr_detector/pii_matcher/redactor/ZoneManager/fake_data public APIs, no duplicated logic (asserted via mocks). Faces ALWAYS blurred; PII per mode (blur, or fake_data.generate()→fake_data_region()); static zones every frame. Preserves dims/FPS; cap+writer released in `finally`. `tests/test_video_pipeline.py` — `10 passed`.
- Note: OCR N-frame sampling/bbox persistence + ffmpeg audio mux deliberately deferred to the next two TASKS.md items — `ocr_sample_rate` accepted but not honored (OCR every frame), output is OpenCV video-only intermediate (D8 mux is the follow-on). No new deps, no architecture change.
- Commit: uncommitted

## 2026-08-04 — Implement zone_manager.py static zones + unit tests
- Changed: core/zone_manager.py, tests/test_zone_manager.py (new); docs/current-state.md, tasks.md, development-log.md
- Why: TASKS.md Phase 1 — store/apply user-defined static redaction zones
- Result: `ZoneManager` with add/remove/get/clear + `apply_zones(frame, mode="blur"|"box")`. Zones are `(x,y,w,h)` pixel coords; application delegates to core.redactor (no duplicated drawing/clamping). add_zone rejects invalid/zero-area (ValueError). `tests/test_zone_manager.py` — `19 passed, 4 subtests` (0.30s); redactor suite still `14 passed`.
- Note: canvas→pixel coordinate mapping is deliberately left to the caller/GUI (out of scope per task); fake-data mode not offered for zones (region, not a typed PII value).
- Commit: uncommitted

## 2026-08-04 — Implement utils/fake_data.py placeholder generation + unit tests
- Changed: utils/fake_data.py, tests/test_fake_data.py (new); docs/current-state.md, tasks.md, development-log.md
- Why: TASKS.md Phase 1 — generate replacement strings for fake-data redaction mode
- Result: `generate(pii_type)` for EMAIL/PHONE/CARD/IP (matches pii_matcher). stdlib `random` only (no new dep). Values use reserved/documentation ranges (example.com, 192.0.2.x, 555-01xx, non-Luhn 4000-cards) — natural-looking but clearly synthetic. Invalid type → ValueError. `tests/test_fake_data.py` — `11 passed, 16 subtests` (0.09s).
- Note: "name" deliberately NOT supported — pii_matcher has no name detection and D7 defers names to v2, so nothing upstream would flag a name region. Followed the stub's documented `pii_type`-only contract (no original-value arg), so the "don't reproduce original" requirement was N/A.
- Commit: uncommitted

## 2026-08-04 — Implement redactor.py rendering layer + unit tests
- Changed: core/redactor.py, tests/test_redactor.py (new); docs/current-state.md, tasks.md, development-log.md
- Why: TASKS.md Phase 1 — draw blur / solid box / fake-data text onto a frame given bboxes
- Result: Rendering-only module — `blur_region`, `box_region`, `fake_data_region`. Caller supplies bbox + (fake-data) replacement string; no detection/OCR/PII-match/fake-data-generation here. Boxes clamped to frame; edge/partial/zero-area/off-frame safe. `tests/test_redactor.py` — `14 passed, 3 subtests` (0.33s).
- Note: old stub docstring described an orchestration signature (face_boxes/pii_matches/zones/mode) — that orchestration is video_pipeline.py's job (it knows bbox source + mode), not the rendering layer's. Flagged, not silently overridden.
- Commit: uncommitted

## 2026-08-04 — Implement pii_matcher.py regex patterns + unit tests
- Changed: core/pii_matcher.py, tests/test_pii_matcher.py; docs/current-state.md, tasks.md, development-log.md
- Why: TASKS.md Phase 1 — regex PII matching (email/phone/card/IPv4) per D7
- Result: Four functions (`is_email`, `is_phone`, `is_card`, `is_ipv4`) using Python `re` module. Deliberately permissive (bias toward recall). `tests/test_pii_matcher.py` — `16 passed, 45 subtests` covering valid PII formats (multiple variants per type), invalid strings, embedded text, None handling. Fast (0.10s), deterministic, offline.
- Commit: uncommitted

## 2026-08-04 — Validate OCR detector against a real application screenshot
- Changed: tests/test_ocr_detector.py (added TestOCRDetectorRealScreenshot + os import); docs/current-state.md, tasks.md
- Why: OCR was only validated on synthetic cv2.putText frames; needed validation against a realistic UI screenshot (tests/assets/ocr_real_screen.png) before moving on
- Result: `17 passed` (was 10). All 5 planted values read exactly and in-bounds (Name/Email/Phone/IPv4/Card), each in its own box with labels split from values. Representative UI text also detected. Face suite still `9 passed` (no regression). core/ocr_detector.py UNCHANGED — no implementation bug; RapidOCR handled the real screenshot without any threshold/behavior tweaks.
- Commit: uncommitted

## 2026-08-04 — OCR backend → RapidOCR (ONNX Runtime); implement + test ocr_detector
- Changed: core/ocr_detector.py, tests/test_ocr_detector.py (new), requirements.txt (pytesseract→rapidocr+onnxruntime, already staged); docs/decisions.md (D6 superseded, D17 added), architecture.md (§3.2 + diagram + structure + deps), current-state.md, tasks.md
- Why: TASKS.md Phase 1 OCR detector; backend swapped from planned Tesseract to RapidOCR/ONNX per developer request — pure-pip, offline, bundled ONNX models, good CPU perf for repeated frame OCR (D17)
- Result: `10 passed` (tests/test_ocr_detector.py) on rapidocr 3.9.2 / onnxruntime 1.28.0; face suite still `9 passed` (no regression). Public `detect_text(frame) -> list[(text,(x,y,w,h))]` preserved; RapidOCR objects normalized in-module, no leak. Fully offline (models load from wheel, no runtime download — verified).
- Commit: uncommitted

## 2026-08-04 — Multi-face (real image) + angled-face characterization tests
- Changed: tests/test_face_detector.py, tests/assets/README.md; docs/current-state.md, tasks.md, known-issues.md
- Why: TASKS.md Phase 1 "multiple faces" + "angled/partial face" — TESTING.md 3.1
- Result: `9 passed` on MediaPipe 0.10.21. multiple_faces.jpg → 3 faces detected (all in bounds); angled_face.jpg → 0 detected (missed) — recorded as accepted v1 limitation ISSUE-002 (characterization test asserts invariants only, does not force detection). face_detector.py unchanged.
- Commit: uncommitted

## 2026-08-04 — Add multi-face detector test
- Changed: tests/test_face_detector.py, tests/assets/README.md; docs/current-state.md, tasks.md
- Why: TASKS.md Phase 1 "Test face detector on a still image with multiple faces" — TESTING.md 3.1
- Result: `7 passed` on MediaPipe 0.10.21; multi-face uses multi_face.* fixture (or PIXELVEIL_TEST_MULTI_FACE_IMAGE), else synthesizes one by tiling single_frontal_face.jpg; requires majority (>= 2) detected
- Commit: uncommitted

## 2026-08-04 — Add standalone single-face detector test
- Changed: tests/test_face_detector.py (new), tests/assets/README.md (new); docs/current-state.md, tasks.md, known-issues.md
- Why: TASKS.md Phase 1 "Test face detector standalone on a still image with 1 face" — encodes TESTING.md 3.1
- Result: guard-path tests pass; single-face tests SKIP in sandbox (ISSUE-001), need real MediaPipe 0.10.x + a face fixture
- Commit: uncommitted

## 2026-08-04 — Implement face_detector.detect_faces (MediaPipe)
- Changed: core/face_detector.py, requirements.txt; docs/current-state.md, tasks.md, known-issues.md
- Why: First Phase 1 task — `detect_faces(frame) -> list[(x,y,w,h)]` via MediaPipe solutions API (D5)
- Also: pinned `mediapipe==0.10.*` (1.0.0 dropped `solutions`); added numpy + pytest to requirements.txt
- Note: Detection path unrunnable in this sandbox (stub MediaPipe wheels, Tasks API only) — see ISSUE-001
- Commit: uncommitted