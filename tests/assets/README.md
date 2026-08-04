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

**Filename:** `multi_face.jpg` (or `.jpeg`, `.png`, `.bmp`)
**Location:** this directory — `tests/assets/multi_face.jpg`

**What the image must be:**
- **2–3** clear, mostly frontal, well-lit human faces in one photo (per TESTING.md 3.1).
- A real photograph, not a drawing/cartoon.
- Each face occupying a reasonable portion of the frame.

**Alternative:** point the test at any image via the
`PIXELVEIL_TEST_MULTI_FACE_IMAGE` environment variable (same syntax as above).

**Optional:** this fixture is not required. If it is absent, the multi-face test
**synthesizes** a multi-face image by tiling copies of `single_frontal_face.jpg`,
so it still runs with only the single-face fixture present. Supplying a real
multi-face photo gives a stronger, more realistic check.

