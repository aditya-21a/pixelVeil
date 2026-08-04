# known-issues.md

Every issue gets an ID (`ISSUE-001`, `ISSUE-002`, ...) so it can be referenced precisely — in commit messages, in agent prompts, in TASKS.md. Never reuse a number, even for closed issues — keep them below in a Resolved section for history.

---

## Format (copy this for every new entry)

```
### ISSUE-00X — <short title>
- **Status:** Open / In Progress / Resolved
- **Severity:** Critical / Major / Minor
- **Affected files:** <path(s)>
- **Description:** <what's wrong, observed behavior>
- **Reproduction:** <how to trigger it, if known>
- **Workaround:** <if any exists, else "none">
- **Notes:** <anything relevant — links to related decisions, git commits>
```

---

## Open Issues

*(none open)*

---

## Resolved Issues

### ISSUE-001 — MediaPipe version must be pinned to 0.10.21 for `solutions.face_detection`
- **Status:** Resolved (uncommitted)
- **Severity:** Major
- **Affected files:** `core/face_detector.py`, `requirements.txt`
- **Description:** `core/face_detector.py` uses MediaPipe's `mp.solutions.face_detection` API, per D5 (pure-pip, no bundled model file, fully local). MediaPipe 1.0.0 removed the legacy `solutions` API entirely, and 0.10.35 also did not expose `solutions.face_detection` in this environment — calling the detection path raised `AttributeError: module 'mediapipe' has no attribute 'solutions'`.
- **Resolution:** Pinned `mediapipe==0.10.21` in `requirements.txt` (a version that exposes `mp.solutions.face_detection`). Verified: `mediapipe 0.10.21`, `hasattr(mp.solutions, 'face_detection') == True`, and `tests/test_face_detector.py` reports `5 passed` against `tests/assets/single_frontal_face.jpg` on 2026-08-04.
- **Reproduction (historical):** `python -c "import mediapipe as mp; print(hasattr(mp,'solutions'))"` returned `False` on 1.0.0 / 0.10.35.
- **Notes:** Related to D5. The Tasks API (`mp.tasks.vision.FaceDetector`) was deliberately not adopted: it requires downloading + bundling a `.tflite` model asset and deviates from D5. Resolved in commit: uncommitted (pin change made outside a commit this session).