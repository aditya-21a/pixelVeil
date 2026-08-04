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