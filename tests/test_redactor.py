"""
Unit tests for core/redactor.py — the rendering layer (blur / solid box /
fake-data text over a supplied bbox).

These tests use generated OpenCV/NumPy frames (no fixtures, no OCR, no face
detection). redactor.py is rendering-only, so tests verify pixel-level effects:
the target region is modified/obscured, pixels outside it are untouched, and
edge/invalid boxes are handled without crashing.
"""

import unittest

import numpy as np
import cv2

from core.redactor import blur_region, box_region, fake_data_region


def _noisy_frame(h=200, w=300):
    """A frame with high-frequency content, so blur has a measurable effect."""
    rng = np.random.RandomState(42)
    return rng.randint(0, 256, (h, w, 3), dtype=np.uint8)


def _mid_bbox():
    """A box well inside a 200x300 frame."""
    return (100, 60, 80, 50)


class TestBlurRegion(unittest.TestCase):
    def test_blur_modifies_target_region(self):
        frame = _noisy_frame()
        x, y, w, h = _mid_bbox()
        before = frame[y:y + h, x:x + w].copy()
        blur_region(frame, (x, y, w, h))
        after = frame[y:y + h, x:x + w]
        # Region changed, and blur reduces local variance vs. the noisy original.
        self.assertFalse(np.array_equal(before, after))
        self.assertLess(after.var(), before.var())

    def test_blur_leaves_outside_pixels_unchanged(self):
        frame = _noisy_frame()
        original = frame.copy()
        x, y, w, h = _mid_bbox()
        blur_region(frame, (x, y, w, h))
        # Mask out the affected region; everything else must be identical.
        mask = np.ones(frame.shape[:2], dtype=bool)
        mask[y:y + h, x:x + w] = False
        self.assertTrue(np.array_equal(frame[mask], original[mask]))


class TestBoxRegion(unittest.TestCase):
    def test_solid_box_covers_region(self):
        frame = _noisy_frame()
        x, y, w, h = _mid_bbox()
        box_region(frame, (x, y, w, h), color=(0, 0, 0))
        region = frame[y:y + h, x:x + w]
        self.assertTrue(np.all(region == 0))

    def test_solid_box_custom_color(self):
        frame = _noisy_frame()
        x, y, w, h = _mid_bbox()
        box_region(frame, (x, y, w, h), color=(255, 0, 0))
        region = frame[y:y + h, x:x + w]
        self.assertTrue(np.all(region == np.array([255, 0, 0])))

    def test_box_leaves_outside_pixels_unchanged(self):
        frame = _noisy_frame()
        original = frame.copy()
        x, y, w, h = _mid_bbox()
        box_region(frame, (x, y, w, h))
        mask = np.ones(frame.shape[:2], dtype=bool)
        mask[y:y + h, x:x + w] = False
        self.assertTrue(np.array_equal(frame[mask], original[mask]))


class TestFakeDataRegion(unittest.TestCase):
    def test_covers_original_and_draws_text(self):
        frame = _noisy_frame()
        x, y, w, h = _mid_bbox()
        before = frame[y:y + h, x:x + w].copy()
        fake_data_region(frame, (x, y, w, h), "Test User 1")
        region = frame[y:y + h, x:x + w]
        # Region no longer matches the original noisy content.
        self.assertFalse(np.array_equal(before, region))
        # White fill + black text => region contains both near-white and dark
        # pixels (the drawn glyphs), proving text was rendered over the cover.
        self.assertTrue((region > 200).any(), "expected light fill pixels")
        self.assertTrue((region < 60).any(), "expected dark text pixels")

    def test_empty_text_still_covers(self):
        frame = _noisy_frame()
        x, y, w, h = _mid_bbox()
        fake_data_region(frame, (x, y, w, h), "", fill_color=(255, 255, 255))
        region = frame[y:y + h, x:x + w]
        self.assertTrue(np.all(region == 255))

    def test_leaves_outside_pixels_unchanged(self):
        frame = _noisy_frame()
        original = frame.copy()
        x, y, w, h = _mid_bbox()
        fake_data_region(frame, (x, y, w, h), "REDACTED")
        mask = np.ones(frame.shape[:2], dtype=bool)
        mask[y:y + h, x:x + w] = False
        self.assertTrue(np.array_equal(frame[mask], original[mask]))


class TestEdgeAndInvalidBoxes(unittest.TestCase):
    def test_bbox_at_frame_boundary(self):
        # Box touching bottom-right corner exactly.
        frame = _noisy_frame(h=200, w=300)
        original = frame.copy()
        bbox = (250, 150, 50, 50)  # x+w == 300, y+h == 200
        box_region(frame, bbox, color=(0, 0, 0))
        self.assertTrue(np.all(frame[150:200, 250:300] == 0))
        # Nothing outside the box changed.
        mask = np.ones(frame.shape[:2], dtype=bool)
        mask[150:200, 250:300] = False
        self.assertTrue(np.array_equal(frame[mask], original[mask]))

    def test_partially_out_of_frame_bbox(self):
        # Box extends beyond the right/bottom edges; only the in-frame part is
        # affected, and no crash / no out-of-bounds write.
        frame = _noisy_frame(h=200, w=300)
        original = frame.copy()
        bbox = (280, 180, 100, 100)  # extends to x=380, y=280
        box_region(frame, bbox, color=(0, 0, 0))
        # In-frame portion (280..300, 180..200) is covered.
        self.assertTrue(np.all(frame[180:200, 280:300] == 0))
        # A pixel outside that portion is untouched.
        self.assertTrue(np.array_equal(frame[0, 0], original[0, 0]))

    def test_negative_origin_bbox(self):
        # Box with negative origin (top-left off-frame) — clamp, don't crash.
        frame = _noisy_frame(h=200, w=300)
        bbox = (-20, -10, 60, 40)  # in-frame part is (0,0)..(40,30)
        # Should not raise.
        box_region(frame, bbox, color=(0, 0, 0))
        self.assertTrue(np.all(frame[0:30, 0:40] == 0))

    def test_zero_area_bbox_is_noop(self):
        frame = _noisy_frame()
        original = frame.copy()
        for bad in [(50, 50, 0, 30), (50, 50, 30, 0), (50, 50, 0, 0)]:
            with self.subTest(bad=bad):
                blur_region(frame, bad)
                box_region(frame, bad)
                fake_data_region(frame, bad, "x")
        self.assertTrue(np.array_equal(frame, original))

    def test_fully_offframe_bbox_is_noop(self):
        frame = _noisy_frame(h=200, w=300)
        original = frame.copy()
        bbox = (500, 500, 40, 40)  # entirely outside
        blur_region(frame, bbox)
        box_region(frame, bbox)
        fake_data_region(frame, bbox, "x")
        self.assertTrue(np.array_equal(frame, original))

    def test_none_and_empty_frame_do_not_crash(self):
        self.assertIsNone(blur_region(None, (0, 0, 10, 10)))
        empty = np.array([])
        # size == 0 => returned unchanged, no crash.
        box_region(empty, (0, 0, 10, 10))
        fake_data_region(empty, (0, 0, 10, 10), "x")


if __name__ == "__main__":
    unittest.main()
