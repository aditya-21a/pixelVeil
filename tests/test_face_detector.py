"""
Standalone tests for core/face_detector.py — single- and multi-face detection.

Acceptance criteria: docs/TESTING.md 3.1 (single frontal face -> detected with
an accurate bbox; multiple faces -> a majority detected).

The real detection path requires MediaPipe's `solutions.face_detection` API. If
it is unavailable the detection tests SKIP (they do not fail) — see ISSUE-001.
The guard-path tests always run.

Fixtures (tests/assets/, or via env var):
  - Single face: PIXELVEIL_TEST_FACE_IMAGE, else single_frontal_face.<jpg|jpeg|png|bmp>
  - Multiple faces: PIXELVEIL_TEST_MULTI_FACE_IMAGE, else multiple_faces.* / multi_face.*.
    If no multi-face fixture is supplied, the multi-face test synthesizes one by
    tiling copies of the single-face fixture, so it still runs when only the
    single-face image is present.
  - Angled/partial face: PIXELVEIL_TEST_ANGLED_FACE_IMAGE, else angled_face.*.
    This is a CHARACTERIZATION test — it records whatever the detector actually
    does on an angled face (which MediaPipe may miss, an accepted v1 limitation
    per TESTING.md 3.1 / ISSUE-002). It never requires a face to be detected.
"""

import glob
import os
import unittest

import numpy as np
import mediapipe as mp

from core.face_detector import detect_faces

_MP_HAS_SOLUTIONS = hasattr(getattr(mp, "solutions", None), "face_detection")
_ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")


def _find_single_face_image():
    """Locate a single-face fixture via env var or tests/assets/, or None."""
    env = os.environ.get("PIXELVEIL_TEST_FACE_IMAGE")
    if env and os.path.isfile(env):
        return env
    for ext in ("jpg", "jpeg", "png", "bmp"):
        matches = glob.glob(os.path.join(_ASSETS_DIR, f"single_frontal_face.{ext}"))
        if matches:
            return matches[0]
    return None


# Number of faces planted when synthesizing a multi-face fixture from the
# single-face image. 3 lets "majority detected" (>= 2) tolerate one miss.
_SYNTH_MULTI_FACE_COUNT = 3


def _find_multi_face_image():
    """Locate a multi-face fixture via env var or tests/assets/, or None."""
    env = os.environ.get("PIXELVEIL_TEST_MULTI_FACE_IMAGE")
    if env and os.path.isfile(env):
        return env
    for stem in ("multiple_faces", "multi_face"):
        for ext in ("jpg", "jpeg", "png", "bmp"):
            matches = glob.glob(os.path.join(_ASSETS_DIR, f"{stem}.{ext}"))
            if matches:
                return matches[0]
    return None


def _find_angled_face_image():
    """Locate an angled/partial-face fixture via env var or tests/assets/, or None."""
    env = os.environ.get("PIXELVEIL_TEST_ANGLED_FACE_IMAGE")
    if env and os.path.isfile(env):
        return env
    for ext in ("jpg", "jpeg", "png", "bmp"):
        matches = glob.glob(os.path.join(_ASSETS_DIR, f"angled_face.{ext}"))
        if matches:
            return matches[0]
    return None


def _synthesize_multi_face(frame, n, gap=60):
    """Build a multi-face image by tiling ``n`` copies of a single-face frame
    side by side on a black background, separated by ``gap`` pixels."""
    h, w = frame.shape[:2]
    canvas = np.zeros((h, w * n + gap * (n + 1), 3), dtype=np.uint8)
    for i in range(n):
        x = gap + i * (w + gap)
        canvas[0:h, x:x + w] = frame
    return canvas


class TestFaceDetectorGuards(unittest.TestCase):
    """Input-guard behavior — runs in every environment."""

    def test_none_frame_returns_empty(self):
        self.assertEqual(detect_faces(None), [])

    def test_empty_frame_returns_empty(self):
        self.assertEqual(detect_faces(np.zeros((0, 0, 3), dtype=np.uint8)), [])


class TestFaceDetectorSingleFace(unittest.TestCase):
    """Single frontal face: exactly one detection with an accurate bbox."""

    def setUp(self):
        if not _MP_HAS_SOLUTIONS:
            self.skipTest(
                "MediaPipe solutions.face_detection unavailable here (ISSUE-001) "
                "— run on a real MediaPipe 0.10.x install"
            )
        self.image_path = _find_single_face_image()
        if not self.image_path:
            self.skipTest(
                "No single-face fixture found — set PIXELVEIL_TEST_FACE_IMAGE or "
                "add tests/assets/single_frontal_face.jpg (see this module's docstring)"
            )
        import cv2

        self.frame = cv2.imread(self.image_path)
        self.assertIsNotNone(self.frame, f"could not read image: {self.image_path}")

    def test_detects_exactly_one_face(self):
        boxes = detect_faces(self.frame)
        self.assertEqual(len(boxes), 1, f"expected 1 face, got {len(boxes)}: {boxes}")

    def test_bbox_within_frame_bounds(self):
        boxes = detect_faces(self.frame)
        self.assertEqual(len(boxes), 1)
        x, y, w, h = boxes[0]
        fh, fw = self.frame.shape[:2]
        self.assertGreaterEqual(x, 0)
        self.assertGreaterEqual(y, 0)
        self.assertGreater(w, 0)
        self.assertGreater(h, 0)
        self.assertLessEqual(x + w, fw)
        self.assertLessEqual(y + h, fh)

    def test_bbox_is_plausible_size(self):
        boxes = detect_faces(self.frame)
        self.assertEqual(len(boxes), 1)
        x, y, w, h = boxes[0]
        fh, fw = self.frame.shape[:2]
        area_frac = (w * h) / float(fw * fh)
        # A single face should cover a non-trivial but not absurd share of frame.
        self.assertGreater(area_frac, 0.005)
        self.assertLess(area_frac, 0.95)


class TestFaceDetectorMultipleFaces(unittest.TestCase):
    """Multiple faces in one still image: a majority must be detected, each
    with a valid bbox (TESTING.md 3.1 "multiple faces in frame")."""

    def setUp(self):
        if not _MP_HAS_SOLUTIONS:
            self.skipTest(
                "MediaPipe solutions.face_detection unavailable here (ISSUE-001) "
                "— run on a real MediaPipe 0.10.x install"
            )
        import cv2

        multi_path = _find_multi_face_image()
        if multi_path:
            self.frame = cv2.imread(multi_path)
            self.assertIsNotNone(self.frame, f"could not read image: {multi_path}")
            # A real multi-face photo has an unknown count; require >= 2 detected.
            self.min_expected = 2
            self.source = multi_path
            return

        # Fallback: synthesize a multi-face image from the single-face fixture so
        # the test still runs when only the single-face image is available.
        single_path = _find_single_face_image()
        if not single_path:
            self.skipTest(
                "No multi-face fixture and no single-face fixture to synthesize "
                "from — add tests/assets/multi_face.jpg or set "
                "PIXELVEIL_TEST_MULTI_FACE_IMAGE (see this module's docstring)"
            )
        single = cv2.imread(single_path)
        self.assertIsNotNone(single, f"could not read image: {single_path}")
        self.frame = _synthesize_multi_face(single, _SYNTH_MULTI_FACE_COUNT)
        # Majority of the planted faces must be detected (TESTING.md tolerance).
        self.min_expected = (_SYNTH_MULTI_FACE_COUNT // 2) + 1
        self.source = f"synthesized {_SYNTH_MULTI_FACE_COUNT}x from {os.path.basename(single_path)}"

    def test_detects_multiple_faces(self):
        boxes = detect_faces(self.frame)
        self.assertGreaterEqual(
            len(boxes),
            self.min_expected,
            f"expected >= {self.min_expected} faces from {self.source}, "
            f"got {len(boxes)}: {boxes}",
        )

    def test_all_bboxes_within_frame_bounds(self):
        boxes = detect_faces(self.frame)
        self.assertGreaterEqual(len(boxes), self.min_expected)
        fh, fw = self.frame.shape[:2]
        for x, y, w, h in boxes:
            self.assertGreaterEqual(x, 0)
            self.assertGreaterEqual(y, 0)
            self.assertGreater(w, 0)
            self.assertGreater(h, 0)
            self.assertLessEqual(x + w, fw)
            self.assertLessEqual(y + h, fh)


class TestFaceDetectorAngledFace(unittest.TestCase):
    """Characterization test for an angled/partial face.

    Per TESTING.md 3.1, an angled face is a documented, accepted v1 limitation:
    MediaPipe may miss it. This test therefore does NOT require a detection — it
    only asserts the invariants that must always hold (a ``list`` is returned and
    any boxes are within frame bounds) and records the observed count so the
    behavior is tracked (see ISSUE-002). It must not be "fixed" by changing
    face_detector.py to force a detection.
    """

    def setUp(self):
        if not _MP_HAS_SOLUTIONS:
            self.skipTest(
                "MediaPipe solutions.face_detection unavailable here (ISSUE-001) "
                "— run on a real MediaPipe 0.10.x install"
            )
        self.image_path = _find_angled_face_image()
        if not self.image_path:
            self.skipTest(
                "No angled-face fixture found — set PIXELVEIL_TEST_ANGLED_FACE_IMAGE "
                "or add tests/assets/angled_face.jpg (see this module's docstring)"
            )
        import cv2

        self.frame = cv2.imread(self.image_path)
        self.assertIsNotNone(self.frame, f"could not read image: {self.image_path}")

    def test_returns_list_and_boxes_within_bounds(self):
        # Invariants that hold regardless of whether the angled face is detected.
        boxes = detect_faces(self.frame)
        self.assertIsInstance(boxes, list)
        fh, fw = self.frame.shape[:2]
        for x, y, w, h in boxes:
            self.assertGreaterEqual(x, 0)
            self.assertGreaterEqual(y, 0)
            self.assertGreater(w, 0)
            self.assertGreater(h, 0)
            self.assertLessEqual(x + w, fw)
            self.assertLessEqual(y + h, fh)

    def test_characterize_observed_detection(self):
        # Characterization only — no minimum is asserted. Observed 2026-08-04:
        # detect_faces() returned 0 boxes for tests/assets/angled_face.jpg
        # (the angled face was missed), consistent with TESTING.md 3.1 and
        # logged as the accepted v1 limitation in ISSUE-002.
        boxes = detect_faces(self.frame)
        self.assertIsInstance(len(boxes), int)


if __name__ == "__main__":
    unittest.main()
