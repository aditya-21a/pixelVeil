# PixelVeil — Project Structure

```text
pixelVeil/
├── main.py                         # Entry point — launches the Tkinter product GUI
├── requirements.txt                # Python dependencies
├── README.md                       # Project overview, setup, and usage
├── AGENTS.md                       # Persistent instructions and protocols for AI coding agents
├── CHANGELOG.md                    # Version/release history
├── .gitignore
│
├── core/                           # Redaction pipeline — no UI code
│   ├── __init__.py
│   ├── face_detector.py            # Face detection wrapper
│   ├── ocr_detector.py             # Tesseract OCR wrapper
│   ├── pii_matcher.py              # PII detection and matching
│   ├── redactor.py                 # Blur, box, and fake-data redaction
│   ├── zone_manager.py             # User-defined persistent redaction zones
│   └── video_pipeline.py           # Pipeline orchestrator
│
├── gui/                            # Shipped desktop product UI
│   ├── __init__.py
│   └── app.py
│
├── utils/                          # Shared supporting utilities
│   ├── __init__.py
│   └── fake_data.py                # Realistic placeholder-data generator
│
├── tools/                          # Development-only tools
│   └── webtest/                    # Flask development/test harness — NOT shipped product
│       ├── __init__.py
│       ├── server.py               # Flask test server and routes
│       ├── templates/
│       │   ├── upload.html
│       │   ├── processing.html
│       │   ├── results.html
│       │   └── settings.html
│       └── static/
│           ├── css/
│           │   └── style.css
│           └── js/
│               └── app.js
│
├── assets/
│   └── tesseract/                  # Bundled Tesseract files go here at packaging time
│       └── .gitkeep
│
├── tests/
│   ├── test_pii_matcher.py         # Unit tests, starting with PII matching
│   └── sample_videos/              # Planted-PII test videos
│       └── .gitkeep
│
└── docs/                           # Project knowledge and development documentation
    ├── architecture.md             # System architecture and component relationships
    ├── current-state.md            # Current implementation status
    ├── decisions.md                # Technical/architectural decisions and reasoning
    ├── design.md                   # Product and UI/UX design
    ├── development-log.md          # Chronological development-session history
    ├── known-issues.md             # Known bugs, limitations, and attempted fixes
    ├── roadmap.md                  # Long-term development phases and direction
    ├── structure.md                # Project/file structure documentation
    ├── tasks.md                    # Current, upcoming, and completed tasks
    └── testing.md                  # Testing strategy, cases, and requirements
```

## Why This Layout

- **`core/` has zero UI dependencies.** The processing pipeline remains independent from both the temporary web interface and the final desktop GUI. The same processing code can therefore be called from `tools/webtest/server.py`, `gui/app.py`, tests, or future interfaces without duplicating the core implementation.

- **`gui/` contains only the shipped desktop interface.** The final Windows application UI remains separate from processing logic.

- **`tools/webtest/` is explicitly development-only.** The Flask interface exists as a convenient development and testing harness. Moving it under `tools/` prevents it from being confused with a second production frontend.

- **`utils/` contains shared supporting functionality.** Code such as realistic fake-data generation can be reused by the redaction pipeline without being tied to a particular detector or interface.

- **`assets/` contains external runtime assets.** Tesseract binaries and related files required for packaged builds can be placed here without mixing them with application source code.

- **`tests/` mirrors the functionality of the core pipeline as testing expands.** `test_pii_matcher.py` is the starting point. Additional test modules can be added for OCR, face detection, redaction, zones, and the complete video pipeline as those components are implemented.

- **`docs/` acts as persistent project memory.** It records not only what PixelVeil is supposed to become, but also what currently works, what is broken, what should be built next, what changed recently, and why important technical decisions were made.

- **`AGENTS.md` stays at the repository root.** AI coding agents can use it as the primary entry point for project rules, context-loading instructions, Git discipline, and the Session End Protocol.

- **`current-state.md` prevents unnecessary codebase rediscovery.** A new development session can quickly determine the current implementation state without reading the entire repository.

- **`decisions.md` preserves reasoning.** Important choices such as local-only processing, OCR technology, dependencies, or architectural boundaries are recorded so future agents do not unknowingly reverse earlier decisions.

- **`known-issues.md` records both problems and failed approaches.** This prevents future agents from repeatedly attempting fixes that have already been tested and rejected.

- **`development-log.md` provides lightweight session history.** It records what changed recently without requiring an agent to reconstruct everything from conversations or Git history.

- **`roadmap.md` and `tasks.md` serve different purposes.** The roadmap describes where PixelVeil is going over the long term, while the task list describes the concrete work that should be done next.

- **Git remains the authoritative code history.** Documentation explains project state and reasoning, while meaningful Git commits preserve the exact implementation history.

## AI Agent Context Strategy

An AI agent should not read every document before every task.

The normal context flow is:

```text
AGENTS.md
    ↓
current-state.md
    ↓
specific task
    ↓
only relevant source files/docs
```

Additional documentation should be loaded only when required:

```text
Bug
→ known-issues.md

Architecture question
→ decisions.md + architecture.md

UI work
→ design.md

Testing work
→ testing.md

Project planning
→ roadmap.md + tasks.md

Historical investigation
→ development-log.md + Git history
```

This keeps agent context focused and reduces unnecessary token usage.

## Development Principle

PixelVeil should maintain the following separation:

```text
UI
 │
 ▼
video_pipeline.py
 │
 ├── face_detector.py
 ├── ocr_detector.py
 ├── pii_matcher.py
 ├── zone_manager.py
 │
 ▼
redactor.py
 │
 ▼
Output Video
```

The core pipeline should remain usable independently of the GUI.

PixelVeil's fundamental product constraint is that video processing remains local. Face detection, OCR, PII detection, fake-data generation, redaction, and video reconstruction should therefore not depend on cloud processing services.