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

### ISSUE-001 — Dev sandbox ships stub MediaPipe wheels (Tasks API only, no `solutions`)
- **Status:** Open (environment limitation, not a code defect)
- **Severity:** Major
- **Affected files:** `core/face_detector.py`, `requirements.txt`
- **Description:** `core/face_detector.py` uses MediaPipe's `mp.solutions.face_detection` API, per D5 (pure-pip, no bundled model file, fully local). The current dev sandbox's MediaPipe wheels are stubs that expose only the Tasks API (`mp.tasks.vision.FaceDetector`) and contain **no `mp.solutions` module at any version** — confirmed by installing `mediapipe==0.10.35` (a 10.9 MB `py3-none` wheel vs the ~50 MB real Windows wheel) which still lacks `solutions`. Calling the detection path here raises `AttributeError: module 'mediapipe' has no attribute 'solutions'`. Real PyPI MediaPipe 0.10.x provides `solutions.face_detection`, so the code is correct on the real target machine.
- **Reproduction:** `python -c "import mediapipe as mp; print(hasattr(mp,'solutions'))"` → `False` in this sandbox.
- **Workaround:** Guard paths (None/empty frame) return `[]` without touching MediaPipe and are verified here. The true-positive detection path must be validated on the real Windows dev machine after `pip install -r requirements.txt` (which now pins `mediapipe==0.10.*`). The Tasks API was deliberately not adopted: it requires downloading + bundling a `.tflite` model asset (new asset + network fetch) and deviates from D5, and would still run against stub libs in this sandbox.
- **Notes:** Related to D5. Blocks the three "Test face detector standalone…" tasks in TASKS.md Phase 1 until validated on a real MediaPipe install. `requirements.txt` pin added so an unpinned `pip install mediapipe` (which now resolves to 1.0.0, where Google removed `solutions`) doesn't reproduce this on the real machine. `tests/test_face_detector.py` encodes the TESTING.md 3.1 single-face check and auto-skips while this limitation holds (guard-path tests still run); it needs a `tests/assets/single_frontal_face.jpg` fixture (see `tests/assets/README.md`) to actually confirm bbox accuracy.

*(add further entries here as they're found)*

---

## Resolved Issues

*(move resolved entries here, keep the ID and add a "Resolved in commit: <hash>" line — don't delete history)*