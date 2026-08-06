"""
Focused tests for the FOUR-PART fake-data quality improvement:
Part 1 — conservative glyph removal with bounded safety expansion
Part 2 — inpainting (TELEA and NS) instead of solid fill
Part 3 — lightweight source-style estimation
Part 4 — original PII formatting preservation

These tests verify the new behavior in isolation, complementing the existing
regression tests in test_redactor.py, test_fake_data.py, and test_video_pipeline.py.
"""

"""
IMPORTANT interrupted-test detail:
The last action before the API failure was fixing
test_bright_text_on_dark_background_detected(). Its original synthetic fixture
used a uniformly bright region, so k-means could not meaningfully distinguish
foreground text from background. The test was being rewritten to use a dark
background with sparse/thin bright-green text-like strokes (minority pixels).
That edit may be incomplete. Inspect and finish/correct this test rather than
assuming its current state is valid.
"""

import unittest
import numpy as np
import cv2

from core import redactor
from utils import fake_data


class TestGlyphRemovalSafetyExpansion(unittest.TestCase):
    """Part 1: Bounded safety margin for glyph removal."""

    def test_inpaint_mask_has_safety_margin(self):
        """The removal mask should expand beyond the bbox by a bounded margin."""
        frame = np.full((200, 400, 3), 128, dtype=np.uint8)
        bbox = (100, 80, 120, 30)

        # Capture the mask by temporarily replacing inpaint_region
        captured_mask = None
        original_inpaint = redactor.inpaint_region

        def capture_inpaint(frame, mask, method="telea"):
            nonlocal captured_mask
            captured_mask = mask.copy()
            return original_inpaint(frame, mask, method)

        redactor.inpaint_region = capture_inpaint
        try:
            redactor.fake_data_region(
                frame, bbox, "test", inpaint_method="telea"
            )
        finally:
            redactor.inpaint_region = original_inpaint

        self.assertIsNotNone(captured_mask)

        # The mask should cover the original bbox
        x, y, w, h = bbox
        self.assertTrue((captured_mask[y:y+h, x:x+w] == 255).all())

        # The mask should extend beyond the bbox (safety margin)
        # Check if at least one pixel immediately outside the bbox is masked
        margin_pixels_exist = (
            (y > 0 and (captured_mask[y-1, x:x+w] == 255).any()) or
            (x > 0 and (captured_mask[y:y+h, x-1] == 255).any()) or
            (y+h < 200 and (captured_mask[y+h, x:x+w] == 255).any()) or
            (x+w < 400 and (captured_mask[y:y+h, x+w] == 255).any())
        )
        self.assertTrue(margin_pixels_exist, "Safety margin should extend beyond bbox")

    def test_safety_margin_is_bounded(self):
        """The safety margin should be bounded, not unbounded expansion."""
        frame = np.full((200, 400, 3), 128, dtype=np.uint8)
        bbox = (100, 80, 120, 30)

        captured_mask = None
        original_inpaint = redactor.inpaint_region

        def capture_inpaint(frame, mask, method="telea"):
            nonlocal captured_mask
            captured_mask = mask.copy()
            return original_inpaint(frame, mask, method)

        redactor.inpaint_region = capture_inpaint
        try:
            redactor.fake_data_region(
                frame, bbox, "test", inpaint_method="telea"
            )
        finally:
            redactor.inpaint_region = original_inpaint

        # Count total masked pixels
        masked_pixels = np.sum(captured_mask == 255)
        bbox_pixels = bbox[2] * bbox[3]  # w * h

        # The expansion should be modest (bounded)
        # margin = min(max(2, min(bw,bh)//15), 5) per implementation
        # So at most a 5-pixel border on all sides
        max_expected = (bbox[2] + 10) * (bbox[3] + 10)

        self.assertGreater(masked_pixels, bbox_pixels, "Should expand beyond bbox")
        self.assertLess(masked_pixels, max_expected, "Expansion should be bounded")


class TestInpainting(unittest.TestCase):
    """Part 2: Inpainting methods (TELEA and NS) selectable via API."""

    def test_inpaint_method_telea_is_callable(self):
        """TELEA inpainting method should be selectable and not raise."""
        frame = np.full((100, 200, 3), 100, dtype=np.uint8)
        frame[30:50, 50:150] = [200, 100, 50]  # Distinctive region

        bbox = (50, 30, 100, 20)
        redactor.fake_data_region(
            frame, bbox, "replacement", inpaint_method="telea"
        )
        # Should not raise; region should be modified
        region = frame[30:50, 50:150]
        self.assertFalse(np.all(region == [200, 100, 50]))

    def test_inpaint_method_ns_is_callable(self):
        """Navier-Stokes inpainting method should be selectable and not raise."""
        frame = np.full((100, 200, 3), 100, dtype=np.uint8)
        frame[30:50, 50:150] = [200, 100, 50]

        bbox = (50, 30, 100, 20)
        redactor.fake_data_region(
            frame, bbox, "replacement", inpaint_method="ns"
        )
        region = frame[30:50, 50:150]
        self.assertFalse(np.all(region == [200, 100, 50]))

    def test_inpaint_reconstructs_background_not_white_fill(self):
        """Inpainting must reconstruct the surrounding background, not leave a
        solid (white) fill block — this is what distinguishes real inpainting
        from the old white-box removal.

        The frame around the bbox is uniform mid-gray; the bbox itself holds a
        bright block to be removed. TELEA/NS propagate the surrounding gray
        inward, so the reconstructed region is ~gray. The white-fill fallback
        (default fill_color when no style/inpaint) would instead leave it white.
        Empty text isolates the background reconstruction from glyph drawing.
        """
        for method in ("telea", "ns"):
            frame = np.full((100, 200, 3), 100, dtype=np.uint8)  # gray surround
            x, y, w, h = 60, 40, 80, 20
            frame[y:y+h, x:x+w] = 240  # bright block to remove
            redactor.fake_data_region(
                frame, (x, y, w, h), "", inpaint_method=method
            )
            region = frame[y:y+h, x:x+w]
            self.assertLess(
                region.mean(), 170,
                f"{method}: inpaint should pull in surrounding gray (~100), "
                f"not leave a bright/white block (got mean {region.mean():.0f})",
            )

    def test_invalid_inpaint_method_raises_valueerror(self):
        """Invalid inpaint method names should raise ValueError clearly."""
        frame = np.full((100, 200, 3), 100, dtype=np.uint8)
        bbox = (50, 30, 100, 20)

        with self.assertRaises(ValueError) as ctx:
            redactor.fake_data_region(
                frame, bbox, "test", inpaint_method="invalid"
            )
        self.assertIn("telea", str(ctx.exception).lower())
        self.assertIn("ns", str(ctx.exception).lower())

    def test_none_inpaint_method_uses_solid_fill(self):
        """When inpaint_method is None, should fall back to solid fill."""
        frame = np.full((100, 200, 3), 50, dtype=np.uint8)
        bbox = (50, 30, 100, 20)

        # Without style, should use default white fill
        redactor.fake_data_region(frame, bbox, "text", inpaint_method=None)

        # Region should be mostly white (solid fill), not inpainted texture
        region = frame[30:50, 50:150]
        # At least some pixels should be near white (text may be darker)
        self.assertTrue((region > 200).any(), "Expected solid fill pixels")

    def test_inpaint_methods_share_same_removal_mask(self):
        """Both TELEA and NS should operate on the same removal mask."""
        # Capture masks from both methods
        mask1 = None
        mask2 = None
        original_inpaint = redactor.inpaint_region

        def capture_inpaint1(frame, mask, method="telea"):
            nonlocal mask1
            mask1 = mask.copy()
            return original_inpaint(frame, mask, method)

        def capture_inpaint2(frame, mask, method="ns"):
            nonlocal mask2
            mask2 = mask.copy()
            return original_inpaint(frame, mask, method)

        frame1 = np.full((100, 200, 3), 128, dtype=np.uint8)
        frame2 = frame1.copy()
        bbox = (60, 30, 80, 20)

        try:
            # Capture TELEA mask
            redactor.inpaint_region = capture_inpaint1
            redactor.fake_data_region(frame1, bbox, "test", inpaint_method="telea")

            # Capture NS mask
            redactor.inpaint_region = capture_inpaint2
            redactor.fake_data_region(frame2, bbox, "test", inpaint_method="ns")
        finally:
            redactor.inpaint_region = original_inpaint

        # Both masks should be identical (same removal region)
        self.assertIsNotNone(mask1)
        self.assertIsNotNone(mask2)
        self.assertTrue(np.array_equal(mask1, mask2), "Both methods should use identical masks")


class TestSourceStyleEstimation(unittest.TestCase):
    """Part 3: Lightweight source-style estimation before pixel destruction."""

    def test_estimate_text_style_returns_required_keys(self):
        """Style dict should contain all required keys."""
        frame = np.full((100, 200, 3), 200, dtype=np.uint8)
        # Add a dark text-like region
        frame[40:60, 80:120] = [30, 30, 30]

        bbox = (80, 40, 40, 20)
        style = redactor.estimate_text_style(frame, bbox)

        self.assertIsNotNone(style)
        self.assertIn("text_color", style)
        self.assertIn("bg_color", style)
        self.assertIn("text_height", style)
        self.assertIn("baseline_offset", style)
        self.assertIn("width", style)

    def test_bright_text_on_dark_background_detected(self):
        """Bright-green text on dark background should NOT become black-on-white."""
        # Create a dark background
        frame = np.full((100, 200, 3), [20, 20, 20], dtype=np.uint8)

        # Add bright green "text-like" strokes (minority pixels)
        # Simulate text by drawing thin strokes on a dark background
        bbox = (80, 40, 40, 20)
        x, y, w, h = bbox

        # Most of the region stays dark background
        frame[y:y+h, x:x+w] = [20, 20, 20]

        # Add bright green strokes (simulating text) - minority of pixels
        # Vertical strokes
        frame[y+2:y+h-2, x+5] = [50, 250, 50]
        frame[y+2:y+h-2, x+15] = [50, 250, 50]
        frame[y+2:y+h-2, x+25] = [50, 250, 50]
        frame[y+2:y+h-2, x+35] = [50, 250, 50]

        style = redactor.estimate_text_style(frame, bbox)

        self.assertIsNotNone(style)

        # Text color should be bright (minority cluster)
        text_color = style["text_color"]
        text_brightness = np.mean(text_color)

        # Background color should be dark (majority cluster)
        bg_color = style["bg_color"]
        bg_brightness = np.mean(bg_color)

        self.assertGreater(
            text_brightness, bg_brightness,
            "Text should be brighter than background for bright-on-dark case"
        )
        self.assertGreater(text_brightness, 100, "Text should be bright")
        self.assertLess(bg_brightness, 100, "Background should be dark")

    def test_dark_text_on_light_background_detected(self):
        """Dark text on light background should be correctly distinguished."""
        frame = np.full((100, 200, 3), [240, 240, 240], dtype=np.uint8)
        bbox = (50, 40, 100, 28)
        x, y, w, h = bbox
        # Draw real dark text
        cv2.putText(frame, 'dark text', (x+2, y+h-6), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (30,30,30), 1, cv2.LINE_AA)

        style = redactor.estimate_text_style(frame, bbox)

        self.assertIsNotNone(style)
        text_color = style["text_color"]
        bg_color = style["bg_color"]
        text_brightness = np.mean(text_color)
        bg_brightness = np.mean(bg_color)

        self.assertLess(text_brightness, bg_brightness, "Text darker than background")
        self.assertLess(text_brightness, 150, "Text should be dark")
        self.assertGreater(bg_brightness, 180, "Background should be light")

    def test_text_height_measured_not_box_height(self):
        """text_height should measure glyph size, not collapse to box height."""
        frame = np.full((100, 300, 3), [240, 240, 240], dtype=np.uint8)
        bbox = (40, 40, 200, 28)
        x, y, w, h = bbox
        # Draw real text at scale 0.6 -> expect height ~10px, NOT 28px (box height)
        cv2.putText(frame, 'john.doe@x.com', (x+2, y+h-6), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (20,20,20), 1, cv2.LINE_AA)

        style = redactor.estimate_text_style(frame, bbox)

        text_height = style["text_height"]
        # At scale 0.6, Hershey cap height is ~10-14px. Must NOT be 28 (box height).
        self.assertLess(text_height, 20, f"text_height {text_height} should be < 20 (not box height {h})")
        self.assertGreater(text_height, 5, "text_height should be > 5 for real glyphs")

    def test_style_estimation_before_destruction(self):
        """Style estimation must happen before original pixels are destroyed."""
        frame = np.full((100, 200, 3), 180, dtype=np.uint8)
        frame[40:60, 80:120] = [30, 30, 30]

        bbox = (80, 40, 40, 20)

        # Estimate style first
        style = redactor.estimate_text_style(frame, bbox)
        original_text_color = style["text_color"]

        # Now destroy pixels with inpainting
        redactor.fake_data_region(
            frame, bbox, "replacement", inpaint_method="telea", style=style
        )

        # If we try to estimate again after destruction, the colors will differ
        style_after = redactor.estimate_text_style(frame, bbox)

        # The "before" style should reflect the original dark text
        self.assertLess(
            np.mean(original_text_color), 100,
            "Original text color should be dark"
        )


class TestStyleGuidedRendering(unittest.TestCase):
    """Part 3 (rendering side): the replacement is drawn using the estimated
    appearance, so it no longer always looks like black-on-white."""

    def _rendered_fg_bg(self, frame, bbox):
        """Return (brightest-pixel BGR, darkest-pixel BGR) of a rendered region
        as a cheap proxy for replacement foreground/background color."""
        x, y, w, h = bbox
        region = frame[y:y+h, x:x+w].reshape(-1, 3).astype(np.float32)
        brightness = region.mean(axis=1)
        fg = region[brightness > np.percentile(brightness, 95)].mean(axis=0)
        bg = region[brightness < np.percentile(brightness, 50)].mean(axis=0)
        return fg, bg

    def test_bright_green_on_dark_source_preserved_in_replacement(self):
        """The critical manual case: bright-green text on a dark background must
        render a bright-green-on-dark replacement, NOT black-on-white."""
        frame = np.full((80, 300, 3), [25, 25, 25], dtype=np.uint8)
        bbox = (30, 30, 240, 28)
        x, y, w, h = bbox
        cv2.putText(frame, '4000 1234 5678 9010', (x+2, y+h-6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (60, 240, 60), 1, cv2.LINE_AA)

        style = redactor.estimate_text_style(frame, bbox)
        redactor.fake_data_region(
            frame, bbox, '4000 9999 8888 7777',
            inpaint_method='telea', style=style,
        )

        fg, bg = self._rendered_fg_bg(frame, bbox)
        # Foreground green channel dominates red and blue (still greenish).
        self.assertGreater(fg[1], fg[0] + 20, "replacement text should stay green (G>B)")
        self.assertGreater(fg[1], fg[2] + 20, "replacement text should stay green (G>R)")
        # Background stays dark, not white.
        self.assertLess(bg.mean(), 90, "replacement background should stay dark, not white")

    def test_replacement_color_approximates_source_color(self):
        """Replacement foreground color should be close to the source foreground
        color (not a fixed black)."""
        frame = np.full((80, 300, 3), [240, 240, 240], dtype=np.uint8)
        bbox = (30, 30, 240, 28)
        x, y, w, h = bbox
        source_fg = (180, 90, 20)  # a distinct blue-ish color (BGR)
        cv2.putText(frame, 'john.doe@ex.com', (x+2, y+h-6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, source_fg, 1, cv2.LINE_AA)

        style = redactor.estimate_text_style(frame, bbox)
        est_fg = np.array(style["text_color"], dtype=np.float32)
        # The estimated foreground should be nearer the source color than to
        # black — proving color is actually inferred, not defaulted.
        dist_to_source = np.linalg.norm(est_fg - np.array(source_fg))
        dist_to_black = np.linalg.norm(est_fg - np.array([0, 0, 0]))
        self.assertLess(dist_to_source, dist_to_black,
                        "estimated text color should be closer to source than black")

    def test_replacement_text_stays_within_bbox_vertically(self):
        """Style-guided placement should keep the drawn text inside the box's
        vertical bounds (no text spilling above/below the region)."""
        # Solid-colored surround so we can detect drawn (differing) pixels.
        frame = np.full((120, 320, 3), [200, 200, 200], dtype=np.uint8)
        bbox = (40, 50, 240, 30)
        x, y, w, h = bbox
        # Mark rows just outside the box so we can assert they're untouched.
        style = {
            "text_color": (10, 10, 10),
            "bg_color": (250, 250, 250),
            "text_height": 16,
            "baseline_offset": 5,
            "width": w,
        }
        before = frame.copy()
        redactor.fake_data_region(
            frame, bbox, "1234 5678", inpaint_method=None, style=style,
        )
        # Rows above y and below y+h must be unchanged (text drawn inside box).
        self.assertTrue(np.array_equal(frame[:y, :], before[:y, :]),
                        "no pixels changed above the bbox")
        self.assertTrue(np.array_equal(frame[y+h:, :], before[y+h:, :]),
                        "no pixels changed below the bbox")

    def test_larger_source_text_yields_larger_replacement(self):
        """Replacement text scale should track the estimated source height."""
        def render_and_measure(source_scale):
            frame = np.full((120, 400, 3), [240, 240, 240], dtype=np.uint8)
            bbox = (30, 40, 320, 40)
            x, y, w, h = bbox
            cv2.putText(frame, 'ACCOUNT 12345', (x+2, y+h-8),
                        cv2.FONT_HERSHEY_SIMPLEX, source_scale, (20, 20, 20), 2, cv2.LINE_AA)
            style = redactor.estimate_text_style(frame, bbox)
            return style["text_height"]

        small_h = render_and_measure(0.6)
        large_h = render_and_measure(1.2)
        self.assertGreater(large_h, small_h,
                           "larger source text should estimate a larger text_height")


class TestFormattingPreservation(unittest.TestCase):
    """Part 4: Preserve original PII formatting in fake values."""

    def test_phone_format_digits_only(self):
        """Digits-only phone should generate digits-only fake phone."""
        fake = fake_data.generate("PHONE", original="9876543210")
        self.assertTrue(fake.replace(" ", "").replace("-", "").replace("(", "").replace(")", "").isdigit())
        # Should not have parentheses or hyphens for digits-only input
        self.assertNotIn("(", fake)
        self.assertNotIn("-", fake)

    def test_phone_format_hyphenated(self):
        """Hyphenated phone should generate hyphenated fake phone."""
        fake = fake_data.generate("PHONE", original="987-654-3210")
        self.assertIn("-", fake)

    def test_phone_format_parenthesized(self):
        """Parenthesized phone should generate parenthesized fake phone."""
        fake = fake_data.generate("PHONE", original="(987) 654-3210")
        self.assertIn("(", fake)
        self.assertIn(")", fake)

    def test_card_format_space_grouped(self):
        """Space-grouped card should generate space-grouped fake card."""
        fake = fake_data.generate("CARD", original="4111 1111 1111 1111")
        self.assertIn(" ", fake)
        self.assertNotIn("-", fake)

    def test_card_format_hyphen_grouped(self):
        """Hyphen-grouped card should generate hyphen-grouped fake card."""
        fake = fake_data.generate("CARD", original="4111-1111-1111-1111")
        self.assertIn("-", fake)

    def test_card_format_digits_only(self):
        """Digits-only card should generate digits-only fake card."""
        fake = fake_data.generate("CARD", original="4111111111111111")
        self.assertNotIn(" ", fake)
        self.assertNotIn("-", fake)
        self.assertTrue(fake.isdigit())

    def test_formatting_with_none_original(self):
        """When original is None, should use default formatting."""
        fake_phone = fake_data.generate("PHONE", original=None)
        fake_card = fake_data.generate("CARD", original=None)

        # Should not raise, and should produce valid output
        self.assertIsInstance(fake_phone, str)
        self.assertIsInstance(fake_card, str)
        self.assertGreater(len(fake_phone), 0)
        self.assertGreater(len(fake_card), 0)


class TestBackwardCompatibility(unittest.TestCase):
    """Ensure new features don't break existing behavior."""

    def test_fake_data_region_without_inpaint_method_preserves_old_behavior(self):
        """Calling fake_data_region without inpaint_method should use solid fill."""
        frame = np.full((100, 200, 3), 50, dtype=np.uint8)
        bbox = (50, 30, 100, 20)

        redactor.fake_data_region(frame, bbox, "Test Text")

        # Should produce white fill + dark text (old behavior)
        region = frame[30:50, 50:150]
        self.assertTrue((region > 200).any(), "Expected light fill pixels")

    def test_fake_data_generate_without_original_uses_default(self):
        """generate() without original parameter should work as before."""
        email = fake_data.generate("EMAIL")
        phone = fake_data.generate("PHONE")
        card = fake_data.generate("CARD")
        ip = fake_data.generate("IP")

        self.assertIn("@example.com", email)
        self.assertIn("555", phone)
        self.assertTrue(len(card) > 0)
        self.assertTrue(ip.startswith("192.0.2."))


if __name__ == "__main__":
    unittest.main()
