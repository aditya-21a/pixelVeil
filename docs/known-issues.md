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

### ISSUE-007 — Fake-data replacement is a heuristic approximation, not a seamless/font-exact reproduction
- **Status:** Open (accepted v1 limitation, by design)
- **Severity:** Minor
- **Affected files:** `core/redactor.py` (`estimate_text_style`, `inpaint_region`, `fake_data_region`), `core/video_pipeline.py` (fake_data path)
- **Description:** In fake_data mode the pipeline now removes the original PII value by classical inpainting (OpenCV `cv2.inpaint`, TELEA or NS) and re-draws a synthetic value in a colour/size estimated from the source region (D24). Every part of this is a deliberate approximation, not a reconstruction: (1) **text colour** and **background colour** come from a k-means (k=2) split, and **glyph height** from an Otsu+contour trace — both are heuristics that can misfire on low-contrast, multi-colour, or very short values; (2) the replacement is always rendered in `FONT_HERSHEY_SIMPLEX`, which is **not** the source font — stroke shape/weight/kerning will differ (no exact font-family reconstruction is attempted, and none is claimed); (3) classical inpainting reconstructs cleanly over flat/near-flat panels but can **smear or ghost** over textured, gradient, or high-frequency backgrounds; (4) at the default `ocr_sample_rate=1`, OCR reruns every frame, so the *randomized* fake value is regenerated per frame and **visibly flickers** (e.g. `gan.smith@…` → `pr.example@…` frame to frame). The result is intended to *look plausibly like redacted-and-substituted text*, not to be indistinguishable from the original — do not describe it as "seamless".
- **Reproduction:** Process `tests/sample_videos/test_mixed.mp4` in fake_data mode (`inpaint_method="telea"` or `"ns"`) and inspect the email/phone panel: the replacement value is dark-on-light like the source and sits in the right place, but the font differs and the value changes each frame at rate 1. For inpaint smear, run over a source with a textured background behind the PII.
- **Workaround:** For the per-frame flicker, raise `ocr_sample_rate` above 1 — the fake value + estimated style are persisted between samples (D18), so the value only changes once per sample interval (this trades moving-text coverage per ISSUE-003). No workaround is needed for the font/colour approximation — it is the intended, honest behaviour of a local/offline/CPU-only substitution. Exact glyph reproduction would require font identification + heavy generative inpainting (GAN/diffusion/LaMa), explicitly out of scope for v1.
- **Notes:** Do **not** "fix" by claiming seamlessness, hardcoding a single font/colour, or forcing OCR every frame to hide the flicker (that discards the D18 sampling benefit). Both TELEA and NS are kept available intentionally (D24) for manual quality comparison — do not remove one. Two manual comparison renders live at `tests/sample_videos/test_mixed_fake_telea.mp4` and `tests/sample_videos/test_mixed_fake_ns.mp4` (git-ignored). The **web harness** also produces both fills side by side automatically: a fake_data job runs the pipeline twice (TELEA + NS) and the Results screen shows Original + TELEA + NS with per-method downloads + a "Download Both" ZIP, so the TELEA-vs-NS quality call can be made on any uploaded clip, not just the two committed renders (D25 — temporary manual comparison, no winner chosen here). Related: D24 (architecture), D25 (harness dual-output), D18 (persistence), ISSUE-003 (sampling), ISSUE-006 (value bbox approximation).

### ISSUE-006 — Value redaction bbox is a proportional (per-line, not per-glyph) approximation
- **Status:** Open (accepted v1 limitation, by design)
- **Severity:** Minor
- **Affected files:** `core/video_pipeline.py` (`_span_to_bbox`), `core/pii_matcher.py` (`find_pii`)
- **Description:** When one OCR box holds a label plus a PII value ("Email: john.doe@example.com"), the pipeline now redacts only the value's sub-region, derived from the regex match's **character span** (`pii_matcher.find_pii`). RapidOCR returns one bounding box per recognized **line**, not per glyph, so exact per-character pixel coordinates are unavailable. `_span_to_bbox` therefore approximates each character's horizontal extent as a uniform fraction of the line width (`x + w * index / len(text)`). With a proportional/variable-width font this is not pixel-exact: the value region's left/right edge can be off by a few pixels versus the true glyph boundary. The mapping is deterministic and always bounded by the original OCR box, and is intentionally biased to still fully cover the value (the redaction never leaks the value); the only visible effect is that a few pixels of an adjacent space or the last label character may be covered, or a few pixels of padding may remain beside the value.
- **Reproduction:** Process a frame whose OCR box mixes a label and a value in a proportional font; compare the redaction edge to the exact glyph boundary. In the deterministic `test_mixed.mp4` fixture (Hershey font, roughly even width) the split is visually clean — label "Email:" fully retained, value fully blurred (validated 2026-08-05: label sharpness retained 100%, value 0%).
- **Workaround:** none needed for redaction safety — the value is always covered. Per-glyph precision would require either a per-character OCR mode or a heavier OCR engine exposing glyph boxes; deliberately **not** adopted (D17 keeps the ONNX RapidOCR backend, no new OCR dependency for coordinates). If a future engine exposes glyph geometry, `_span_to_bbox` is the single seam to tighten.
- **Notes:** Do not "fix" by hardcoding known label widths or shrinking every OCR box by a fixed percentage — the region must derive from the actual match position (that was the explicit accuracy rule for this fix). The uniform-width approximation is the documented, deliberate tradeoff.

### ISSUE-005 — Results "Original" preview blank for mp4v source files (browser codec limitation)
- **Status:** Open (accepted v1 limitation)
- **Severity:** Minor
- **Affected files:** `tools/webtest/server.py` (`/video/<uid>/original`), `tests/sample_videos/*.mp4`
- **Description:** The Results screen serves the original uploaded file byte-for-byte via `/video/<uid>/original`. When the source is encoded with mp4v (MPEG-4 Part 2) — as all `tests/sample_videos/*.mp4` fixtures are, produced by OpenCV `VideoWriter_fourcc(*"mp4v")` — HTML5 `<video>` in Chrome/Edge/Firefox shows duration and controls but a blank image. VLC, QuickTime, Windows Media Player, and direct download all play it correctly. The **processed output** is always browser-playable H.264 (fixed this session). The original preview is a cosmetic read-only convenience; it does not affect the redacted output, the download, or any core pipeline behaviour.
- **Reproduction:** Run the harness with any `tests/sample_videos/*.mp4` fixture and open the Results screen; the "Original" `<video>` control shows duration but a blank image. Real H.264 screen recordings (OBS/Loom/QuickTime) render correctly in both panes.
- **Workaround:** Download the original from its URL and play externally, or use an H.264 source for the harness. Transcoding the source on ingest (at upload time) would fix the in-browser preview but was out of scope for this pass (user constraint: "do not reprocess videos from the Results page" / "do not change unrelated pipeline logic").
- **Notes:** The sample video generator (`tests/make_sample_videos.py`) uses OpenCV `VideoWriter_fourcc(*"mp4v")` for its fixtures — intentional for portability, but mp4v is not browser-decodable. To fix the fixture preview without changing the generator, a one-time ffmpeg re-encode of the sample files to H.264 would suffice; deferred. Not hidden with CSS per user instruction: "inspect/report the exact codec/MIME/browser incompatibility rather than hiding it with CSS."

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
- **Quantified (Phase 2, 2026-08-04, `tests/phase2_validate.py` on `test_mixed.mp4`, ticker scrolling 12 px/frame @ 10 fps):** the moving CARD `4111 1111 1111 1111` was detected & redacted on **27/60** frames at `ocr_sample_rate=1` and **25/60** at rate 5; the moving IP `192.168.1.105` on **3/60** at rate 1 and **0/60** at rate 5. Static PII on the same clip (email/phone) redacted on all frames. So even at rate 1 (OCR every frame) fast-scrolling text is only OCR-readable — and therefore only detected/redacted — on a subset of frames; raising the sample rate makes it worse, as expected. **Measurement caveat:** the harness's "PII still readable in output" OCR check returned 0/60 for the moving values, but that *under-reports* the leak — the same motion that stops the pipeline from reading the text also stops the verification OCR from reading it, so 0/60-readable is NOT proof the moving PII is fully redacted. The honest denominator is the detect/redact rate above (27/60, 3/60), with the remaining frames being a potential paused-frame leak.
- **Workaround:** lower `ocr_sample_rate` (down to `1` = OCR every frame, no persistence gap) to trade speed for coverage. Faces are detected every frame and static user zones apply every frame, so neither is affected by this.
- **Notes:** Quantify the miss rate during Phase 2 pipeline validation before choosing a default sample rate (TESTING.md acceptance criteria). Do not "fix" by forcing OCR every frame — that discards the performance benefit sampling exists for; the right lever is the sample-rate default, decided against real test videos. A dedicated repro fixture now exists: `tests/sample_videos/test_mixed.mp4` carries a scrolling PII ticker (CARD/IP) that moves each frame — use it to measure the between-samples miss rate.

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