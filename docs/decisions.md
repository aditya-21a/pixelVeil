# PixelVeil — DECISIONS.md

Record of significant decisions and why they were made — so reasoning doesn't get relitigated mid-build or forgotten later.

---

### D1 — Build a post-processing tool, not a live/in-recording redactor
**Decision:** User records with their existing tool (OBS/Loom/QuickTime), then runs the finished file through PixelVeil.
**Why:** A live/real-time redaction extension would require competing with entrenched recording tools (OBS, Loom) for the recording step itself — high adoption friction for no benefit, since most target users won't switch recorders just for a blur feature. Post-processing meets users where they already are.
**Rejected alternative:** Chrome extension that records live and redacts during capture. Rejected because it only captures browser tabs (not full desktop), and asks users to change their entire recording workflow.

### D2 — Desktop app, not web app
**Decision:** Local Windows desktop app, all processing on-device.
**Why:** The product's core promise is privacy — "your recording never leaves your machine" is a stronger, more honest claim than "we promise to delete your upload after processing." A web app would make PixelVeil itself a server that (even briefly) stores other people's sensitive screen recordings, which contradicts its entire purpose.

### D3 — Windows only for v1
**Decision:** Target Windows exclusively, not cross-platform.
**Why:** Reduces build complexity significantly (single OS to test/package/support) and matches the primary target buyer's likely environment (QA/support teams on corporate Windows machines). Mac/Linux can be considered later if demand justifies it.

### D4 — Python as the core language
**Decision:** Build in Python, not Electron/Node or native C#/.NET.
**Why:** The two hardest technical problems — face detection and OCR — are Python-native ecosystems with the deepest documentation and best AI-coding-agent support of any language for these tasks. Building in Electron/Node or C# would mean either weaker library support or bridging out to a Python subprocess anyway, adding complexity for no benefit.

### D5 — MediaPipe over dlib/face_recognition for face detection
**Decision:** Use MediaPipe Face Detection.
**Why:** Pure pip install with prebuilt wheels — no CMake/Visual Studio Build Tools needed, which matters given an AI agent is doing much of the environment setup. Fast enough for frame-by-frame processing, good accuracy on frontal/near-frontal faces (the common case for screen recordings).
**Rejected alternative:** `dlib`/`face_recognition` — better documented in tutorials, slightly more accurate, but typically requires compiling from source on Windows unless an exact-matching prebuilt wheel is found. Real setup risk. Revisit for v2 if MediaPipe's accuracy proves insufficient in real testing.
**Also rejected:** OpenCV Haar Cascades (too many false negatives — unacceptable in a redaction tool), YOLO-face/RetinaFace (overkill weight for non-crowd screen recordings).

### D6 — Tesseract over EasyOCR/PaddleOCR for OCR
**Decision:** Use Tesseract via `pytesseract`.
**Why:** Fast enough on sampled frames, extremely well documented, free. Accepted cost: it's a separate binary that must be bundled at packaging time (known, well-documented step).
**Rejected alternative:** EasyOCR — no external binary, but PyTorch-based, meaning a much heavier dependency footprint and slower per-frame inference. Better on stylized/rotated text, but most on-screen text in the target use case (dashboards, CRMs) is clean and horizontal, so the extra weight isn't justified for v1.
**v2 note:** if real-world testing shows Tesseract's accuracy on dashboard/CRM screenshots is insufficient, add EasyOCR as an optional heavier/slower "high accuracy" mode — not a full replacement.

### D7 — Regex over NER/ML for PII pattern matching
**Decision:** Use Python's built-in `re` module for email/phone/card/IP detection.
**Why:** These are structured, predictable formats — no ML model needed, no added dependency, no added failure mode. The cheapest and most reliable part of the pipeline; keep it that way.
**Deferred:** NER-based detection (spaCy/transformers) for unstructured PII like arbitrary names — not in v1 scope at all, so no need to carry the weight yet.

### D8 — OpenCV + ffmpeg mux, not MoviePy, for video I/O
**Decision:** Use OpenCV for frame read/write, ffmpeg for final audio muxing.
**Why:** OpenCV's own `VideoWriter` frequently produces poorly-compatible MP4s (codec issues, dropped audio). The reliable pattern is: process frames in OpenCV → write intermediate file → mux final output with original audio via ffmpeg.
**Rejected alternative:** MoviePy — convenient wrapper, but its abstraction layer makes the frame-by-frame pixel manipulation PixelVeil needs (drawing blur boxes) more awkward than working with OpenCV directly.

### D9 — Tkinter over PyQt for v1 GUI (superseded — see D10)
**Original decision:** Tkinter for the eventual product GUI — zero extra dependency, simplest for an AI agent to build against.
**Rejected alternative:** PyQt5/PySide6 — more polished, but PyQt5 has licensing complications for closed-source distribution (GPL/commercial license required); heavier dependency than needed for v1.
**Status:** Superseded for the *testing* phase by D10 (Flask/HTML test harness), but Tkinter (or CustomTkinter later) remains the plan for the actual shipped product GUI.

### D10 — Flask + local HTML test harness for development/testing
**Decision:** Build a local Flask-served HTML UI to run and observe the pipeline during development, instead of running scripts from the terminal repeatedly.
**Why:** Makes it far easier to visually inspect what each pipeline stage is doing (live frame preview with detection boxes, per-stage status, technical log) than parsing terminal output. This is a development/QA tool, not the final shipped product interface.

### D11 — PyInstaller over Nuitka for packaging (for now)
**Decision:** Use PyInstaller to build the distributable Windows `.exe`.
**Why:** Most standard, most documented tool for this, easiest for AI-agent-assisted debugging given wide community troubleshooting resources.
**Known accepted risk:** PyInstaller executables are commonly flagged by Windows Defender/antivirus as suspicious (the bundled-binary pattern resembles malware droppers). Mitigation (code signing or vendor allowlisting) is budgeted as a pre-launch task, not treated as a surprise blocker.
**Revisit trigger:** switch to Nuitka (compiles to actual C, less AV-flagging, better runtime performance, slower build iteration) if AV false-positives become a real adoption blocker closer to public launch.

### D12 — Freemium pricing model
**Decision:** Free tier (limited videos/length, blur mode only) + Pro tier ($12-15/mo, unlimited, fake-data mode, saved zone presets).
**Why:** Matches self-serve, no-sales-calls distribution goal; low enough price point for individual/small-team credit-card signup without procurement friction.

### D13 — Target buyer: QA/support teams, not general creators
**Decision:** Primary v1 marketing target is QA engineers and customer support teams recording bug-report/demo videos with real customer data on screen.
**Why:** This persona has proven willingness to pay for adjacent tools (e.g., BlurShot's screenshot tool explicitly targets QA/support), a clear recurring pain (dashboards/CRMs full of scrolling PII text, not just faces), and isn't the same crowded pool of YouTubers/journalists already well-served by existing face-blur-only tools.

### D14 — USP is PII text detection + fake-data replacement, not face blur
**Decision:** Lead all marketing with "we catch emails/phones/cards on screen, and replace them with realistic fake data" — face blur is included as table stakes, not the headline.
**Why:** Research confirmed face-blur-in-video is already commoditized (multiple free/open-source tools). No competitor found combines OCR-based PII detection with face blur on video, and none offer fake-data replacement (vs. blur/box only) for video. This is the actual unclaimed, defensible-enough ground.

### D15 — Child-only face detection deferred to v2, female/gender filtering dropped entirely
**Decision:** "Blur children only" mode is a defined v2 milestone, not v1. Gender-based face filtering is cut from scope permanently.
**Why:** Age-estimation accuracy is genuinely weak at the child/teen boundary — shipping this in v1 would risk a serious failure mode (an actual child left unblurred) before the base pipeline is even proven. When built in v2, the model must default to blurring on low confidence (over-blurring is acceptable; missing a child is not). Gender filtering was dropped because it adds real bias/accuracy risk with no clear safety justification, unlike the child-protection use case.

### D16 — Batch processing excluded from v1
**Decision:** Single file at a time only.
**Why:** Keeps v1 scope minimal and focused on proving the core detection pipeline works correctly before adding convenience features. Revisit once base product has paying users requesting it.