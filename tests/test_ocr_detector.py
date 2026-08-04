"""
Standalone tests for core/ocr_detector.py — text detection via RapidOCR
(ONNX Runtime backend, see DECISIONS.md D17, which supersedes D6).

Acceptance criteria: docs/TESTING.md 3.2 — a static visible email / phone /
credit-card / IP is detected (later matched by pii_matcher). These tests cover
the OCR half only: that detect_text() reads the text back and returns
in-bounds bounding boxes. PII regex matching is pii_matcher.py's job and is
tested separately.

RapidOCR ships its ONNX detection/recognition models inside the wheel, so these
tests run fully offline with no fixture files and no network — text images are
synthesized with OpenCV at test time. OCR is inherently imperfect, so text
assertions check that the key token is present (case-insensitive, ignoring
incidental spaces) rather than demanding an exact transcription; bbox invariants
(in-bounds, positive area) are always asserted strictly.
"""

import unittest

import numpy as np
import cv2

from core.ocr_detector import detect_text


def _render_text(
    text,
    scale=1.0,
    thickness=2,
    width=900,
    height=140,
    pad=40,
):
    """Render black `text` on a white BGR frame, the way on-screen UI text
    appears to the detector. Returns an OpenCV BGR numpy array."""
    img = np.full((height, width, 3), 255, np.uint8)
    baseline = height // 2 + 15
    cv2.putText(
        img,
        text,
        (pad, baseline),
        cv2.FONT_HERSHEY_SIMPLEX,
        scale,
        (0, 0, 0),
        thickness,
        cv2.LINE_AA,
    )
    return img


def _normalize(s):
    """Lowercase and strip all whitespace, for lenient token comparison."""
    return "".join(s.split()).lower()


class TestOCRDetectorGuards(unittest.TestCase):
    """Invalid/empty input handling — must never raise, always return a list.
    These run without touching the OCR engine's detection path."""

    def test_none_frame_returns_empty_list(self):
        self.assertEqual(detect_text(None), [])

    def test_empty_array_returns_empty_list(self):
        self.assertEqual(detect_text(np.array([])), [])

    def test_blank_frame_returns_empty_list(self):
        # A uniform white frame contains no text.
        blank = np.full((100, 300, 3), 255, np.uint8)
        self.assertEqual(detect_text(blank), [])


class TestOCRDetectorText(unittest.TestCase):
    """Real detection path: normal UI text, plus the PII shapes from
    TESTING.md 3.2 (email / phone / IPv4 / card) and a small-text case."""

    def _assert_boxes_in_bounds(self, results, frame):
        fh, fw = frame.shape[:2]
        self.assertIsInstance(results, list)
        for text, bbox in results:
            self.assertIsInstance(text, str)
            x, y, w, h = bbox
            self.assertGreaterEqual(x, 0)
            self.assertGreaterEqual(y, 0)
            self.assertGreater(w, 0)
            self.assertGreater(h, 0)
            self.assertLessEqual(x + w, fw)
            self.assertLessEqual(y + h, fh)

    def _detected_text(self, results):
        return _normalize(" ".join(t for t, _ in results))

    def test_normal_ui_text(self):
        frame = _render_text("File Edit View Settings")
        results = detect_text(frame)
        self._assert_boxes_in_bounds(results, frame)
        self.assertIn("settings", self._detected_text(results))

    def test_email_address(self):
        frame = _render_text("user@example.com")
        results = detect_text(frame)
        self._assert_boxes_in_bounds(results, frame)
        # OCR may split around the '@'; check the distinctive domain token.
        self.assertIn("example.com", self._detected_text(results))

    def test_phone_number(self):
        frame = _render_text("555-123-4567")
        results = detect_text(frame)
        self._assert_boxes_in_bounds(results, frame)
        detected = self._detected_text(results)
        digits = "".join(c for c in detected if c.isdigit())
        self.assertIn("5551234567", digits)

    def test_ipv4_address(self):
        frame = _render_text("192.168.1.5")
        results = detect_text(frame)
        self._assert_boxes_in_bounds(results, frame)
        detected = self._detected_text(results)
        digits = "".join(c for c in detected if c.isdigit())
        self.assertIn("19216815", digits)

    def test_credit_card_number(self):
        frame = _render_text("4111 1111 1111 1111")
        results = detect_text(frame)
        self._assert_boxes_in_bounds(results, frame)
        detected = self._detected_text(results)
        digits = "".join(c for c in detected if c.isdigit())
        self.assertIn("4111111111111111", digits)

    def test_small_text(self):
        # Smaller font (scale 0.5) — the practical lower bound for legible
        # on-screen text. Recognition is expected but leniently checked.
        frame = _render_text("Account: jane.doe@corp.io", scale=0.5, thickness=1)
        results = detect_text(frame)
        self._assert_boxes_in_bounds(results, frame)
        self.assertIn("corp.io", self._detected_text(results))


class TestOCRDetectorNoText(unittest.TestCase):
    """A frame with graphics but no text should yield no detections (and must
    not raise)."""

    def test_non_text_graphics_return_list(self):
        img = np.full((200, 200, 3), 255, np.uint8)
        cv2.circle(img, (100, 100), 60, (0, 0, 0), 3)
        results = detect_text(img)
        self.assertIsInstance(results, list)
        # No text present; any spurious boxes must still be in-bounds.
        for _text, (x, y, w, h) in results:
            self.assertGreaterEqual(x, 0)
            self.assertGreaterEqual(y, 0)
            self.assertLessEqual(x + w, 200)
            self.assertLessEqual(y + h, 200)


if __name__ == "__main__":
    unittest.main()
