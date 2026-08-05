# PixelVeil — Test Harness UI Design

This is a **local HTML test tool**, not the final product UI — its only job is letting you upload a video, run it through the pipeline, and see results without touching the terminal repeatedly. Keep it functional, not fancy.

---

## 1. Visual Style

- **Theme:** Light only. White/off-white background (`#FAFAFA` or `#FFFFFF`), dark gray text (`#1A1A1A`), no pure black.
- **Accent color:** One neutral accent only — a plain blue or dark gray/black for buttons and active states (e.g. `#2563EB` if you want a touch of color, or just `#111111` for a fully monochrome look). No gradients, no neon, no purple.
- **Borders/dividers:** Thin, light gray (`#E5E5E5`), no heavy shadows.
- **Font:** System font stack — this is exactly what WhatsApp Desktop, Instagram, and most of Google's own products actually render with on most machines:
  ```css
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Helvetica Neue", Arial, sans-serif;
  ```
  On Windows (your target), this renders as **Segoe UI** — clean, familiar, zero setup, no font files to bundle.
- **Spacing:** Generous whitespace, no clutter. This is a tool you'll stare at repeatedly while testing — keep it calm.
- **Components:** Plain rectangular buttons/cards, slightly rounded corners (4-6px), no skeuomorphism, no icons unless functionally necessary (upload icon, play/pause icon).

---

## 2. Screens

### Screen 1 — Upload
- Drag-and-drop zone (or click to browse) for a video file.
- Mode toggle: **"Blur"** vs **"Replace with fake data"** (radio buttons or a simple switch).
- Static zone drawing tool: once a video is loaded, show the first frame as a still image; let the user click-drag rectangles on it to mark "always redact this region." List drawn zones below with a delete option per zone.
- A single **"Process Video"** button, disabled until a file is loaded.

### Screen 2 — Processing

This screen's entire purpose is to replace staring at a terminal, so it needs to show real internals, not just a spinner. Think of it as a live debug console for the pipeline, laid out like this:

- **Overall progress bar** (% complete, frame X of Y, elapsed time / estimated remaining).
- **Per-stage status panel** — one row per orchestrator step in `video_pipeline.py`, each showing its current state (idle / running / done) and a running count:
  - `face_detector` — faces detected so far, current frame's detection count
  - `ocr_detector` — frames sampled so far, last sampled frame number, raw text blocks found
  - `pii_matcher` — PII matches so far, broken down live by type (emails / phones / cards / IPs)
  - `zone_manager` — number of static zones applied per frame (constant, but show it's active)
  - `redactor` — redactions drawn so far (blur vs. fake-data count, if mixed)
  - `video writer / ffmpeg mux` — encoding status, current output file size growing
- **Live scrolling technical log** underneath the panel — the actual line-by-line detail, monospace font (`Consolas` or similar, this section only), e.g.:
  ```
  [00:00:12] Frame 118/3600 | face_detector: 1 face @ (240,80,320,160) conf=0.91
  [00:00:12] Frame 120/3600 | ocr_detector: sampled, 3 text blocks found
  [00:00:12] Frame 120/3600 | pii_matcher: EMAIL match "j***@***.com" @ (400,200,180,30)
  [00:00:12] Frame 120/3600 | redactor: fake-data mode, drew placeholder over EMAIL region
  [00:00:13] Frame 121/3600 | zone_manager: 2 static zones applied
  ```
  Timestamped, one line per meaningful event, auto-scroll to bottom, but let the user pause auto-scroll to inspect a moment (e.g. scroll-lock on manual scroll-up).
- **Current frame preview thumbnail** — show the actual frame currently being processed, with detection boxes overlaid live (face boxes, PII boxes, zone boxes in different colors) — this is the single most useful thing for catching false negatives/positives during testing, more valuable than the text log alone.
- Cancel button.

This level of detail is specifically so you can watch, in real time, exactly which stage is slow, which stage is producing false positives/negatives, and what each orchestrator step is actually doing at any given moment — not just "processing... 43%."

### Screen 3 — Results
- Side-by-side (or toggle) **before/after** video preview using plain HTML `<video>` elements.
- Summary panel: total faces blurred, total PII matches found (broken down by type: emails, phones, cards, IPs), total static zones applied.
- **Download output video** button.
- ~~**"Flag an issue"** button~~ — **dropped, not implemented (DECISIONS.md D22).** For this developer-only harness, manual misses ("missed this face", "false positive here") are recorded directly in `docs/known-issues.md` rather than through an in-app timestamped log. Do not implement this button.

### Screen 4 — Settings (for tuning during testing, not for end users)
- OCR sampling rate (every N frames) — number input.
- Face detection confidence threshold — slider.
- PII regex patterns — simple editable list (so you can tweak/add patterns without touching code every time).
- Save/reset to defaults.

---

## 3. Layout Principle

Single-column, top-to-bottom flow for each screen — no sidebars, no nav bar complexity. A simple top bar with 4 tabs (Upload / Processing / Results / Settings) is enough navigation. This is a tool for one user (you), not a product — don't over-design it.

---

## 4. Tech Note

Since the actual processing pipeline is Python, the simplest path is a minimal local Flask app: Flask serves these HTML pages, and a couple of routes trigger the existing `core/` pipeline functions and stream progress back (e.g. via a simple polling endpoint or `Server-Sent Events`) to update the progress bar/log live. No need for a heavy JS framework — plain HTML + a little vanilla JS for the drag-and-drop, zone drawing, and progress polling is enough.