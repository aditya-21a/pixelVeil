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

### ISSUE-004 — Audio not copyable into MP4 fails the mux (no re-encode fallback)
- **Status:** Open (accepted v1 limitation)
- **Severity:** Minor
- **Affected files:** `core/video_pipeline.py`
- **Description:** The ffmpeg mux step copies the original audio stream unchanged (`-c:a copy`) to preserve it without reprocessing (D8, "where practical"). If the source audio is in a codec the MP4 container can't hold via stream copy (uncommon for screen recorders, which use AAC/MP4), ffmpeg exits non-zero and `process_video()` raises `RuntimeError`; there is intentionally **no automatic re-encode fallback** in v1. The processed video work is not lost silently — the failure is explicit and the temp intermediate is cleaned up — but no output file is produced in that case.
- **Reproduction:** feed a source whose audio codec is incompatible with MP4 stream-copy (e.g. some PCM/vorbis-in-mkv inputs) and observe the `RuntimeError` from the mux.
- **Workaround:** none automatic in v1. A future `-c:a aac` fallback (re-encode only when copy fails) is the obvious fix; deferred until Phase 2 shows it's actually hit with real recordings. Target inputs (OBS/Loom/QuickTime MP4) are AAC and copy cleanly.
- **Notes:** Deliberately not implemented now to keep the mux path simple and avoid re-encoding audio unnecessarily (quality/time cost) for the common case. Revisit if Phase 2 validation surfaces real inputs that trip it.

### ISSUE-003 — PII moving/scrolling between OCR samples can be missed or mis-placed
- **Status:** Open (accepted v1 tradeoff, by design)
- **Severity:** Minor
- **Affected files:** `core/video_pipeline.py`
- **Description:** OCR now runs only every `ocr_sample_rate`-th frame (D18 / architecture.md 6.4–6.5, 7); between samples the last PII detections are persisted and re-applied at their **last known bbox**. For static on-screen text this is exact. For text that moves or scrolls between samples, the persisted box can lag the text's real position, and PII that appears *and disappears* entirely within a single sample interval may never be redacted. This is the expected frame-sampling tradeoff called out in TESTING.md 3.2 ("Scrolling/moving text containing PII — may be missed between OCR samples"), not a code defect.
- **Reproduction:** process a clip where a PII string scrolls quickly with `ocr_sample_rate` set high (e.g. 10); the redaction box trails the moving text between samples.
- **Workaround:** lower `ocr_sample_rate` (down to `1` = OCR every frame, no persistence gap) to trade speed for coverage. Faces are detected every frame and static user zones apply every frame, so neither is affected by this.
- **Notes:** Quantify the miss rate during Phase 2 pipeline validation before choosing a default sample rate (TESTING.md acceptance criteria). Do not "fix" by forcing OCR every frame — that discards the performance benefit sampling exists for; the right lever is the sample-rate default, decided against real test videos.

### ISSUE-002 — Angled/partial faces may be missed by the face detector
- **Status:** Open (accepted v1 limitation)
- **Severity:** Minor
- **Affected files:** `core/face_detector.py`
- **Description:** MediaPipe's `solutions.face_detection` is tuned for frontal faces and can miss faces at a strong angle or partially occluded. Observed 2026-08-04: `detect_faces()` returned **0 boxes** for `tests/assets/angled_face.jpg` (face missed). This matches the documented weak point in TESTING.md 3.1 and is an accepted v1 limitation, not a code bug — the detector otherwise behaves correctly (returns a list; frontal/multi-face detection works).
- **Reproduction:** `detect_faces(cv2.imread("tests/assets/angled_face.jpg"))` → `[]` on MediaPipe 0.10.21.
- **Workaround:** none for v1. TESTING.md 3.1 says not to block v1 ship on this; bias-toward-blur and user-drawn static zones mitigate in the full pipeline. `tests/test_face_detector.py::TestFaceDetectorAngledFace` is a characterization test that records the behavior without forcing a detection.
- **Notes:** Do not "fix" by lowering thresholds or swapping the model to force this single image to pass — that risks false positives elsewhere. Revisit only if angled-miss rate proves unacceptable during Phase 2 pipeline validation.

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