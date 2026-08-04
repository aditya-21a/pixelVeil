# current-state.md

**This file describes what actually works right now — not what's planned, not what's in progress. If it's not implemented and tested, it's not listed here as working.** Read this before `TASKS.md` to know where the project actually stands.

Last updated: 2026-08-04

---

## Overall Status

`v1 — not yet started / Phase 0 (environment setup)`
*(update this line as phases in TASKS.md complete: Phase 0 → Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5)*

---

## Component Status

| Component | Status | Notes |
|---|---|---|
| `core/face_detector.py` | Implemented, not yet validated | `detect_faces(frame) -> list[(x,y,w,h)]` via MediaPipe `solutions.face_detection`. Compiles/imports; detection path unvalidated in this env — see ISSUE-001 |
| `core/ocr_detector.py` | Not implemented | Stub only |
| `core/pii_matcher.py` | Not implemented | EMAIL regex stubbed in, PHONE/CARD/IP not yet written |
| `core/redactor.py` | Not implemented | Stub only |
| `core/zone_manager.py` | Not implemented | Stub only |
| `core/video_pipeline.py` | Not implemented | Stub only |
| `utils/fake_data.py` | Not implemented | Stub only |
| `webtest/server.py` | Skeleton working | Flask routes serve empty template pages, not wired to pipeline yet |
| `gui/app.py` | Not started | Blocked on core pipeline validation (see TASKS.md Phase 2 gate) |
| Packaging (PyInstaller) | Not started | Blocked on GUI |

---

## What's Been Validated (per TESTING.md)

*(Nothing yet — fill in as Phase 2 test cases pass. Format: test case name, pass/fail, miss rate if applicable, date.)*

---

## Known Limitations Currently Accepted

*(Mirror the high-level summary here; full detail lives in known-issues.md. Keep this list short — just enough to orient a new session.)*

- Installed `mediapipe` in this environment is an anomalous 1.0.0 exposing only the Tasks API (no `mp.solutions`), so the `face_detector` detection path cannot execute here. Code targets standard MediaPipe 0.10.x per D5. See ISSUE-001.

---

## How to Update This File

- After implementing/testing any component, update its row in the table above.
- Keep descriptions to one line — detail belongs in `development-log.md` (what changed) or `known-issues.md` (what's broken), not here.
- This file should always be readable in under a minute and give an accurate snapshot — if it takes longer than that to read, it's gotten too detailed and needs trimming.