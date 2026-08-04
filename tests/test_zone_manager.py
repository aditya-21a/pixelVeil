"""
Unit tests for core/zone_manager.py — storage and application of user-defined
static redaction zones (TESTING.md 3.4).

Zones are in video-frame pixel coordinates. Storage tests cover add/remove/
get/clear and validation; application tests use generated NumPy frames and
verify pixel-level effects (zone covered, adjacent pixels untouched, multiple
zones, edge / partial / off-frame / invalid handling). No video fixture needed.
"""

import unittest

import numpy as np

from core.zone_manager import ZoneManager


def _noisy_frame(h=200, w=300):
    rng = np.random.RandomState(7)
    return rng.randint(0, 256, (h, w, 3), dtype=np.uint8)


class TestZoneStorage(unittest.TestCase):
    def test_add_and_get(self):
        zm = ZoneManager()
        idx = zm.add_zone((10, 20, 30, 40))
        self.assertEqual(idx, 0)
        self.assertEqual(zm.get_zones(), [(10, 20, 30, 40)])

    def test_add_multiple_preserves_order(self):
        zm = ZoneManager()
        zm.add_zone((0, 0, 10, 10))
        zm.add_zone((50, 50, 20, 20))
        self.assertEqual(zm.get_zones(), [(0, 0, 10, 10), (50, 50, 20, 20)])

    def test_add_coerces_to_int(self):
        zm = ZoneManager()
        zm.add_zone((1.9, 2.1, 5.0, 6.0))
        self.assertEqual(zm.get_zones(), [(1, 2, 5, 6)])

    def test_remove_zone(self):
        zm = ZoneManager()
        zm.add_zone((0, 0, 10, 10))
        zm.add_zone((50, 50, 20, 20))
        zm.remove_zone(0)
        self.assertEqual(zm.get_zones(), [(50, 50, 20, 20)])

    def test_remove_out_of_range_raises(self):
        zm = ZoneManager()
        with self.assertRaises(IndexError):
            zm.remove_zone(0)

    def test_clear(self):
        zm = ZoneManager()
        zm.add_zone((0, 0, 10, 10))
        zm.clear()
        self.assertEqual(zm.get_zones(), [])

    def test_add_invalid_zone_raises(self):
        zm = ZoneManager()
        for bad in [(0, 0, 0, 10), (0, 0, 10, 0), (0, 0, -5, 10), (1, 2, 3)]:
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    zm.add_zone(bad)
        # Nothing invalid should have been stored.
        self.assertEqual(zm.get_zones(), [])


class TestZoneApplicationBox(unittest.TestCase):
    def test_single_zone_covered_box(self):
        zm = ZoneManager()
        zm.add_zone((100, 60, 80, 50))
        frame = _noisy_frame()
        zm.apply_zones(frame, mode="box", color=(0, 0, 0))
        self.assertTrue(np.all(frame[60:110, 100:180] == 0))

    def test_zone_affects_only_specified_area(self):
        zm = ZoneManager()
        zm.add_zone((100, 60, 80, 50))
        frame = _noisy_frame()
        original = frame.copy()
        zm.apply_zones(frame, mode="box")
        mask = np.ones(frame.shape[:2], dtype=bool)
        mask[60:110, 100:180] = False
        self.assertTrue(np.array_equal(frame[mask], original[mask]))

    def test_coordinate_accuracy_exact_bounds(self):
        # The covered rectangle must be exactly [y, y+h) x [x, x+w), no off-by-one
        # bleed into the neighbouring row/column.
        zm = ZoneManager()
        zm.add_zone((100, 60, 80, 50))
        frame = np.full((200, 300, 3), 255, np.uint8)
        zm.apply_zones(frame, mode="box", color=(0, 0, 0))
        # Inside corners are black.
        self.assertTrue(np.all(frame[60, 100] == 0))
        self.assertTrue(np.all(frame[109, 179] == 0))
        # Just outside each edge is still white.
        self.assertTrue(np.all(frame[59, 100] == 255))   # row above
        self.assertTrue(np.all(frame[110, 100] == 255))  # row below
        self.assertTrue(np.all(frame[60, 99] == 255))    # col left
        self.assertTrue(np.all(frame[60, 180] == 255))   # col right

    def test_multiple_zones_all_covered(self):
        zm = ZoneManager()
        zm.add_zone((0, 0, 40, 40))
        zm.add_zone((250, 150, 50, 50))
        frame = _noisy_frame()
        zm.apply_zones(frame, mode="box", color=(0, 0, 0))
        self.assertTrue(np.all(frame[0:40, 0:40] == 0))
        self.assertTrue(np.all(frame[150:200, 250:300] == 0))


class TestZoneApplicationBlur(unittest.TestCase):
    def test_blur_zone_changes_region(self):
        zm = ZoneManager()
        zm.add_zone((100, 60, 80, 50))
        frame = _noisy_frame()
        before = frame[60:110, 100:180].copy()
        zm.apply_zones(frame, mode="blur")
        after = frame[60:110, 100:180]
        self.assertFalse(np.array_equal(before, after))
        self.assertLess(after.var(), before.var())

    def test_blur_leaves_outside_unchanged(self):
        zm = ZoneManager()
        zm.add_zone((100, 60, 80, 50))
        frame = _noisy_frame()
        original = frame.copy()
        zm.apply_zones(frame, mode="blur")
        mask = np.ones(frame.shape[:2], dtype=bool)
        mask[60:110, 100:180] = False
        self.assertTrue(np.array_equal(frame[mask], original[mask]))


class TestZoneEdgeCases(unittest.TestCase):
    def test_zone_at_frame_boundary(self):
        zm = ZoneManager()
        zm.add_zone((250, 150, 50, 50))  # x+w == 300, y+h == 200 exactly
        frame = _noisy_frame(h=200, w=300)
        zm.apply_zones(frame, mode="box", color=(0, 0, 0))
        self.assertTrue(np.all(frame[150:200, 250:300] == 0))

    def test_partially_out_of_frame_zone(self):
        zm = ZoneManager()
        zm.add_zone((280, 180, 100, 100))  # extends past right/bottom edges
        frame = _noisy_frame(h=200, w=300)
        original = frame.copy()
        # Must not raise or write out of bounds.
        zm.apply_zones(frame, mode="box", color=(0, 0, 0))
        # In-frame portion covered.
        self.assertTrue(np.all(frame[180:200, 280:300] == 0))
        # A far pixel untouched.
        self.assertTrue(np.array_equal(frame[0, 0], original[0, 0]))

    def test_fully_offframe_zone_is_noop(self):
        zm = ZoneManager()
        zm.add_zone((500, 500, 40, 40))
        frame = _noisy_frame(h=200, w=300)
        original = frame.copy()
        zm.apply_zones(frame, mode="box")
        self.assertTrue(np.array_equal(frame, original))

    def test_apply_with_no_zones_is_noop(self):
        zm = ZoneManager()
        frame = _noisy_frame()
        original = frame.copy()
        zm.apply_zones(frame, mode="box")
        self.assertTrue(np.array_equal(frame, original))

    def test_invalid_mode_raises(self):
        zm = ZoneManager()
        zm.add_zone((0, 0, 10, 10))
        frame = _noisy_frame()
        with self.assertRaises(ValueError):
            zm.apply_zones(frame, mode="fake_data")


class TestZoneConsistencyAcrossFrames(unittest.TestCase):
    def test_same_zones_applied_to_every_frame(self):
        # TESTING.md 3.4: 100% coverage across frames — applying the stored
        # zone to N independent frames covers the identical region each time.
        zm = ZoneManager()
        zm.add_zone((100, 60, 80, 50))
        for _ in range(5):
            frame = _noisy_frame()
            zm.apply_zones(frame, mode="box", color=(0, 0, 0))
            self.assertTrue(np.all(frame[60:110, 100:180] == 0))


if __name__ == "__main__":
    unittest.main()
