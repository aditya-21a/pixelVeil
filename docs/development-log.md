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

## 2026-08-04 — Implement face_detector.detect_faces (MediaPipe)
- Changed: core/face_detector.py; docs/current-state.md, tasks.md, known-issues.md
- Why: First Phase 1 task — `detect_faces(frame) -> list[(x,y,w,h)]` via MediaPipe solutions API (D5)
- Note: Detection path unrunnable in this env (anomalous mediapipe 1.0.0, no solutions) — see ISSUE-001
- Commit: uncommitted