# PixelVeil — Technical Architecture

## 1. Overview

PixelVeil is a Windows desktop app, built in Python, that takes a video file and outputs a locally-redacted copy — faces blurred, on-screen PII text detected and blurred/replaced — with zero cloud calls. This document covers every library choice, the alternatives considered, why each was picked or rejected, the file/module structure, and the data flow.

**Guiding principle for every choice below:** favor libraries that are (a) reliably installable on Windows without painful native compilation, (b) well-documented enough that an AI coding agent can implement against them correctly, and (c) accurate enough that the product's core promise — "you don't need to manually check the output" — actually holds.

---

## 2. High-Level Architecture

```
                    ┌─────────────────┐
                    │   Tkinter GUI    │
                    │ (file picker,    │
                    │  mode toggle,    │
                    │  zone drawing,   │
                    │  progress bar)   │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │  Video Pipeline  │
                    │  (orchestrator)  │
                    └────────┬─────────┘
                             │
        ┌────────────────────┼────────────────────┐
        ▼                    ▼                     ▼
┌───────────────┐   ┌────────────────┐   ┌──────────────────┐
│ Face Detector  │   │  OCR Detector   │   │  Zone Manager     │
│ (MediaPipe)    │   │ (Tesseract)     │   │ (user-drawn boxes)│
└───────┬────────┘   └────────┬────────┘   └─────────┬─────────┘
        │                     │                       │
        │            ┌────────▼────────┐              │
        │            │  PII Matcher     │              │
        │            │  (regex)         │              │
        │            └────────┬────────┘              │
        │                     │                       │
        └─────────────┬───────┴───────────────────────┘
                       ▼
              ┌─────────────────┐
              │    Redactor      │
              │ (blur / box /    │
              │  fake-data draw) │
              └────────┬─────────┘
                       ▼
              ┌─────────────────┐
              │  Video Writer    │
              │ (OpenCV + ffmpeg │
              │  mux for output) │
              └─────────────────┘
```

---

## 3. Core Library Choices — With Reasoning

### 3.1 Face Detection

| Option | Verdict | Why |
|---|---|---|
| **MediaPipe Face Detection** | **CHOSEN** | Pure pip install, prebuilt wheels — no C++ compiler or CMake needed on the dev machine, which matters a lot given you're building this Windows-only and want an AI agent to set it up reliably. Fast enough for near-real-time frame processing. Good accuracy for frontal/near-frontal faces, which covers the vast majority of screen-recording use cases (people on video calls, webcam overlays). |
| OpenCV Haar Cascades | Rejected | Built into OpenCV already, but accuracy is genuinely poor — high false-negative rate on angled or partially-occluded faces. In a redaction tool, a missed face is a real privacy failure, not a minor bug. Not worth the "free" convenience. |
| dlib / `face_recognition` library | Rejected for v1 | Better accuracy than Haar Cascades and very well documented (tons of tutorials, easy for an agent to implement against). But `dlib` typically needs to be compiled from source on Windows unless you find a prebuilt wheel matching your exact Python version — CMake + Visual Studio Build Tools required. This is a real setup headache and a common failure point when an AI agent tries to get a dev environment running. Worth revisiting for v2 if MediaPipe's accuracy proves insufficient. |
| YOLO-face / RetinaFace | Rejected for v1 | More accurate on small/angled/crowd faces, but heavier (larger model, GPU-friendly but slower on CPU-only Windows machines), and overkill — screen recordings are not crowd scenes. Save this for a "pro accuracy mode" later if ever needed. |

### 3.2 OCR (Text Detection for PII)

| Option | Verdict | Why |
|---|---|---|
| **Tesseract (via `pytesseract`)** | **CHOSEN** | Free, extremely well documented, fast enough when run on sampled frames rather than every frame. The one real cost: Tesseract is a separate binary (not pure Python), so it must be installed on the dev machine and later bundled with the packaged app — this is a known, well-documented packaging step, not a blocker. |
| EasyOCR | Rejected for v1 | Pure Python, no external binary — simpler to install. But it's PyTorch-based, meaning a much heavier dependency footprint (hundreds of MB), slower per-frame inference, and a larger final installer size. Better accuracy on stylized/rotated text, but not worth the weight for v1 where most on-screen text (dashboards, forms, CRMs) is clean and horizontal. |
| PaddleOCR | Rejected | Comparable accuracy to EasyOCR, but historically finicky to install cleanly on Windows, more dependency conflicts reported. Not worth the setup risk for v1. |

**v2 note:** if Tesseract's accuracy on real-world dashboard/CRM screenshots proves insufficient, swap in EasyOCR as a heavier-but-more-accurate mode, not a full replacement — keep Tesseract as the fast default.

### 3.3 PII Pattern Matching

| Option | Verdict | Why |
|---|---|---|
| **Python `re` (built-in regex)** | **CHOSEN** | Structured PII — emails, phone numbers, credit card numbers, IP addresses — follow predictable formats. No ML model needed, no added dependency, no added failure mode. This is the cheapest, most reliable part of the whole pipeline — keep it that way. |
| NER model (spaCy, transformers) | Rejected for v1 | Needed only for unstructured PII like arbitrary names, which isn't in v1 scope. Adds real weight (model downloads, slower inference) for a feature you haven't built yet. Revisit only if/when name detection becomes a planned feature. |

### 3.4 Video Read/Write

| Option | Verdict | Why |
|---|---|---|
| **OpenCV (`cv2`) for frame read/write** | **CHOSEN** | Standard, extremely well documented, directly integrates with the face-detection and drawing steps since MediaPipe and OpenCV both operate on the same frame format (numpy arrays). |
| **ffmpeg (via `imageio-ffmpeg` or subprocess) for final muxing** | **CHOSEN, alongside OpenCV** | OpenCV's built-in `VideoWriter` often produces poorly-compatible MP4 files (codec/container issues, no audio track preserved). The reliable pattern is: process frames with OpenCV → write a raw intermediate video → mux the final output (with original audio re-attached) using ffmpeg. This avoids a common, frustrating failure mode where the "redacted" file plays wrong or has no sound. |
| MoviePy | Rejected | Convenient high-level wrapper around ffmpeg, but adds an extra abstraction layer that makes frame-by-frame pixel manipulation (which you need, for drawing blur boxes) more awkward than working with OpenCV directly. |

### 3.5 GUI

| Option | Verdict | Why |
|---|---|---|
| **Tkinter** | **CHOSEN for v1** | Built into Python — zero extra dependency, zero install friction, simplest possible path for an AI agent to build against, and sufficient for what v1 needs: a file picker, a mode toggle, a zone-drawing canvas, a progress bar, a "Process" button. |
| PyQt5 / PySide6 | Rejected for v1 | More polished, modern-looking widgets — but adds licensing considerations (PyQt5 is GPL or requires a commercial license for closed-source distribution; PySide6 is LGPL and cleaner on that front) and a heavier dependency. Worth revisiting once the core pipeline works and you want a genuinely polished interface — CustomTkinter is a good middle-ground worth considering then, since it gives a modern look while staying simple and MIT-licensed. |

### 3.6 Packaging (Turning the Script into a Distributable .exe)

| Option | Verdict | Why |
|---|---|---|
| **PyInstaller** | **CHOSEN** | The standard, most-documented tool for turning a Python script into a Windows `.exe`. Widely used, lots of troubleshooting resources available (important for AI-agent-assisted debugging). |
| **Known risk to flag now, not later:** | — | PyInstaller-built executables are frequently flagged as "suspicious" by Windows Defender and other antivirus software, because the packaging pattern (self-extracting bundled Python + DLLs) resembles how malware droppers work. This is a real, common problem for indie Windows apps — expect to deal with false-positive AV flags before public launch (options include code-signing the executable, which costs money, or submitting to Microsoft/AV vendors for allowlisting). Don't treat this as a surprise blocker later — budget time for it. |
| Nuitka | Alternative worth knowing about | Compiles Python to actual C code, producing an executable less likely to trigger AV false positives and often better runtime performance. Slower build iteration during development though. Consider switching to this closer to public launch if PyInstaller's AV-flagging becomes a real adoption blocker. |

---

## 4. Why Python Overall (Recap)

The two hardest parts of this product — face detection and OCR — are Python-native ecosystems with the deepest documentation, most tutorials, and best AI-coding-agent support of any language for these specific tasks. Building this in Electron/Node or native C# would mean either reimplementing CV logic in a less-supported ecosystem, or bridging out to a Python subprocess anyway — adding complexity for no benefit given you're targeting Windows-only.

---

## 5. Proposed File/Module Structure

```
pixelveil/
├── main.py                  # GUI entry point, launches the app
├── core/
│   ├── face_detector.py     # MediaPipe wrapper — detect_faces(frame) -> list of bounding boxes
│   ├── ocr_detector.py      # Tesseract wrapper — detect_text(frame) -> list of (text, bbox)
│   ├── pii_matcher.py       # Regex patterns — match_pii(text) -> PII type or None
│   ├── redactor.py          # Draws blur / solid box / fake-data text onto a frame given bboxes
│   ├── zone_manager.py      # Stores and applies user-marked static redaction zones
│   └── video_pipeline.py    # Orchestrates: read frame -> detect -> redact -> write frame
├── gui/
│   └── app.py                # Tkinter interface: file picker, mode toggle, zone canvas, progress bar
├── utils/
│   └── fake_data.py          # Generates placeholder text ("Test User 1", fake emails, etc.)
├── assets/
│   └── tesseract/             # Bundled Tesseract binary for distribution (added at packaging stage)
├── tests/
│   └── sample_videos/         # Test videos with planted fake PII for validation
├── requirements.txt
└── README.md
```

---

## 6. Data Flow (Per Video)

1. User selects video file + mode (blur vs. fake-data) + optionally draws static zones.
2. `video_pipeline.py` opens the file with OpenCV, reads frame by frame.
3. Every frame (or every 2nd, for speed): `face_detector.py` returns face bounding boxes.
4. Every Nth frame (OCR is expensive — sample rather than run on every frame): `ocr_detector.py` returns detected text + bounding boxes; `pii_matcher.py` filters for actual PII matches.
5. For frames between OCR samples, persist the last known text bounding boxes rather than re-detecting — avoids both wasted computation and visual flicker in the output.
6. `zone_manager.py` bounding boxes are applied to every frame, no detection needed (user-defined, fixed).
7. `redactor.py` draws the appropriate treatment (blur, solid box, or fake-data text) onto each frame for every flagged region.
8. Processed frames are written to an intermediate video file via OpenCV.
9. ffmpeg re-muxes the intermediate video with the original audio track into the final output file.
10. GUI shows progress throughout, then a "Done — output saved to [path]" message.

---

## 7. Performance Notes

- Running OCR on every single frame is unnecessarily expensive and unnecessary for accuracy — sample every 5-10 frames (roughly 3-6 times per second at typical frame rates) and persist bounding boxes between samples.
- Face detection is cheap enough with MediaPipe to run more frequently than OCR, but still consider every-2nd-frame sampling with box persistence if processing speed becomes a bottleneck on longer videos.
- All of this is CPU-bound by default (no GPU dependency required for v1) — acceptable for a first version, but if processing a 10-minute video takes several minutes, that's worth surfacing honestly in the UI via a progress bar rather than pretending it's instant.

---

## 8. Dependencies (Initial requirements.txt)

```
opencv-python
mediapipe
pytesseract
pillow
imageio-ffmpeg
```

(Tesseract itself is a separate binary install during development — download from the official Tesseract-OCR Windows installer — then bundled into the `assets/` folder for the packaged app.)
