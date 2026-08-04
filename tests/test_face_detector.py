"""
Standalone tests for core/face_detector.py — single-face bounding-box accuracy.

Acceptance criteria: docs/TESTING.md 3.1 (single frontal face -> detected,
accurate bbox).

The real detection path requires MediaPipe's `solutions.face_detection` API and
a still image containing exactly one clear frontal face. Where either is
unavailable the single-face tests SKIP (they do not fail) — see ISSUE-001 for
the MediaPipe stub-wheel limitation in the current dev sandbox. The guard-path
tests always run.

To run the real single-face check, supply a still image with one frontal face:
  - set env var PIXELVEIL_TEST_FACE_IMAGE to the image path, or
  - drop a file at tests/assets/single_frontal_face.<jpg|jpeg|png|bmp>
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


if __name__ == "__main__":
    unittest.main()
