# tests/assets/ — still-image fixtures for detector unit tests

Drop test images here for the standalone detector tests (`tests/test_face_detector.py`).

## Single-face fixture (for TESTING.md 3.1)

**Filename:** `single_frontal_face.jpg` (or `.jpeg`, `.png`, `.bmp`)
**Location:** this directory — `tests/assets/single_frontal_face.jpg`

**What the image must be:**
- Exactly **one** clear, **frontal**, well-lit human face (per TESTING.md 3.1 "single frontal face, static").
- A normal photo — a real photograph of a face, not a drawing/cartoon (MediaPipe is trained on real faces).
- The face should occupy a reasonable portion of the frame (roughly 5%–95% of the image area — a normal head-and-shoulders or webcam-style shot is ideal).
- Any common resolution works (e.g. 640x480 and up).

**Alternative:** instead of placing a file here, point the test at any image via
the `PIXELVEIL_TEST_FACE_IMAGE` environment variable:

```
setx PIXELVEIL_TEST_FACE_IMAGE "C:\path\to\your_face.jpg"    # Windows, new shells
$env:PIXELVEIL_TEST_FACE_IMAGE = "C:\path\to\your_face.jpg"  # current PowerShell session
```

If no fixture is found (and/or MediaPipe's `solutions` API is unavailable —
ISSUE-001), the single-face tests **skip** rather than fail.

## Multi-face fixture (for TESTING.md 3.1, "multiple faces")

**Filename:** `multiple_faces.jpg` (or `.jpeg`, `.png`, `.bmp`; `multi_face.*` also accepted)
**Location:** this directory — `tests/assets/multiple_faces.jpg`

**What the image must be:**
- **2–3** clear, mostly frontal, well-lit human faces in one photo (per TESTING.md 3.1).
- A real photograph, not a drawing/cartoon.
- Each face occupying a reasonable portion of the frame.

**Alternative:** point the test at any image via the
`PIXELVEIL_TEST_MULTI_FACE_IMAGE` environment variable (same syntax as above).

**Fallback:** if no multi-face fixture is present, the multi-face test
**synthesizes** one by tiling copies of `single_frontal_face.jpg`, so it still
runs with only the single-face fixture present. A real multi-face photo gives a
stronger, more realistic check and is preferred.

## Angled/partial-face fixture (for TESTING.md 3.1, "angled face")

**Filename:** `angled_face.jpg` (or `.jpeg`, `.png`, `.bmp`)
**Location:** this directory — `tests/assets/angled_face.jpg`

**What the image must be:**
- One human face at a strong angle (profile / three-quarter) or partially occluded.
- A real photograph.

**Alternative:** `PIXELVEIL_TEST_ANGLED_FACE_IMAGE` environment variable.

This is a **characterization** test, not a pass/fail detection test: MediaPipe
may miss angled faces (accepted v1 limitation — ISSUE-002). The test records the
observed behavior and only asserts invariants (a list is returned, any boxes are
within bounds). If the fixture is absent, the angled test **skips**.


