# current-state.md

**This file describes what actually works right now — not what's planned, not what's in progress. If it's not implemented and tested, it's not listed here as working.** Read this before `TASKS.md` to know where the project actually stands.

Last updated: 2026-08-04

---

## Overall Status

`v1 — Phase 1 (Core Pipeline)`
*(update this line as phases in TASKS.md complete: Phase 0 → Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5)*

---

## Component Status

| Component | Status | Notes |
|---|---|---|
| `core/face_detector.py` | Implemented & validated (single + multiple faces; angled = known miss) | `detect_faces(frame) -> list[(x,y,w,h)]` via MediaPipe `solutions.face_detection`. `tests/test_face_detector.py` passes on MediaPipe 0.10.21 (single + multi + guards + angled characterization). Angled/partial faces may be missed — accepted v1 limitation, see ISSUE-002 |
| `core/ocr_detector.py` | Implemented & validated (synthetic + real screenshot) | `detect_text(frame) -> list[(text, (x,y,w,h))]` via **RapidOCR on ONNX Runtime** (D17, supersedes the planned Tesseract/D6). Backend isolated in-module; callers see only normalized `(text, bbox)`. `tests/test_ocr_detector.py` — `17 passed`: synthetic UI/email/phone/IPv4/card/small-text + guards, **plus a real-screenshot integration test** (`tests/assets/ocr_real_screen.png`) that reads all 5 planted values cleanly. Not yet wired into the video pipeline. |
| `core/pii_matcher.py` | Implemented & tested | Four regex functions: `is_email()`, `is_phone()`, `is_card()`, `is_ipv4()` (D7). `tests/test_pii_matcher.py` — `16 passed` covering valid/invalid samples + edge cases. Not yet wired into the pipeline. |
| `core/redactor.py` | Implemented & tested (rendering only) | `blur_region()`, `box_region()`, `fake_data_region()` draw a redaction treatment onto a supplied bbox. Rendering-only — caller supplies bbox + (for fake-data) the replacement string; no detection/matching/fake-data generation here. `tests/test_redactor.py` — `14 passed`. Not yet wired into the pipeline. |
| `core/zone_manager.py` | Not implemented | Stub only |
| `core/video_pipeline.py` | Not implemented | Stub only |
| `utils/fake_data.py` | Not implemented | Stub only |
| `webtest/server.py` | Skeleton working | Flask routes serve empty template pages, not wired to pipeline yet |
| `gui/app.py` | Not started | Blocked on core pipeline validation (see TASKS.md Phase 2 gate) |
| Packaging (PyInstaller) | Not started | Blocked on GUI |

---

## What's Been Validated (per TESTING.md)

- TESTING.md 3.1 — face detector, single frontal face: **PASS** (`tests/test_face_detector.py`, MediaPipe 0.10.21, 2026-08-04).
- TESTING.md 3.1 — face detector, multiple faces: **PASS** (`tests/test_face_detector.py`, `9 passed`, MediaPipe 0.10.21, 2026-08-04) — 3 faces detected in `tests/assets/multiple_faces.jpg`.
- TESTING.md 3.1 — face detector, angled/partial face: **CHARACTERIZED** — angled face in `tests/assets/angled_face.jpg` was **missed (0 detected)**, the documented, accepted v1 limitation (ISSUE-002).
- TESTING.md 3.2 — OCR detector, static text (email/phone/card/IP + UI text): **PASS** (`tests/test_ocr_detector.py`, `17 passed`, RapidOCR 3.9.2 / ONNX Runtime 1.28.0, 2026-08-04). OCR only — PII regex matching is pii_matcher.py's job, tested separately.
- TESTING.md 3.2 — OCR detector, **realistic application screenshot**: **PASS** (`tests/test_ocr_detector.py::TestOCRDetectorRealScreenshot`, `tests/assets/ocr_real_screen.png`, 2026-08-04). All 5 planted values read exactly and in-bounds — Name `John Doe`, Email `john.doe@example.com`, Phone `9876543210`, IPv4 `192.168.1.105`, Card `4111 1111 1111 1111` — each in its own box (labels split from values, as expected). Representative UI text also detected. `core/ocr_detector.py` unchanged.

---

## Known Limitations Currently Accepted

*(Mirror the high-level summary here; full detail lives in known-issues.md. Keep this list short — just enough to orient a new session.)*

- MediaPipe is pinned to `mediapipe==0.10.21` in `requirements.txt` because 1.0.0 (and 0.10.35 here) removed the legacy `solutions.face_detection` API that `core/face_detector.py` uses per D5. See ISSUE-001 (resolved).
- Angled/partial faces may be missed by the face detector (observed: 0 detected on `tests/assets/angled_face.jpg`). Accepted v1 limitation per TESTING.md 3.1 — see ISSUE-002.

---

## How to Update This File

- After implementing/testing any component, update its row in the table above.
- Keep descriptions to one line — detail belongs in `development-log.md` (what changed) or `known-issues.md` (what's broken), not here.
- This file should always be readable in under a minute and give an accurate snapshot — if it takes longer than that to read, it's gotten too detailed and needs trimming.