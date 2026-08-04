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

import os
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


def _digits(s):
    """Keep only decimal digits — for phone/card comparison, where OCR spacing
    and grouping (e.g. "4111 1111 1111 1111") is irrelevant to the value."""
    return "".join(c for c in s if c.isdigit())


class TestOCRDetectorRealScreenshot(unittest.TestCase):
    """Integration test against a realistic PixelVeil dashboard screenshot
    (`tests/assets/ocr_real_screen.png`), as opposed to the synthetic
    cv2.putText frames above.

    Unlike the synthetic cases, this fixture has real UI chrome — cards, icons,
    nav text, mixed font sizes/weights/colours, and text spread across the
    screen. Labels ("Email:") and their values ("john.doe@example.com") are
    spatially separate, so RapidOCR returns them as *separate* boxes; the value
    of a field is never assumed to share a box with its label (per the task's
    segmentation notes).

    Acceptance is the five planted values (name + 4 PII shapes from TESTING.md
    3.2); a small subset of UI strings is checked as a general OCR sanity signal
    only. This runs detect_text(frame) exactly as production code would.
    """

    # Path is resolved relative to THIS test file, not the shell's CWD, so the
    # test works regardless of where pytest is invoked from.
    FIXTURE = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "assets", "ocr_real_screen.png"
    )

    # Ground-truth planted values (the acceptance criteria).
    EXPECT_NAME = "John Doe"
    EXPECT_EMAIL = "john.doe@example.com"
    EXPECT_PHONE = "9876543210"
    EXPECT_IPV4 = "192.168.1.105"
    EXPECT_CARD = "4111 1111 1111 1111"

    # A small representative subset of known UI text — a general OCR sanity
    # check, NOT an exhaustive transcript of the screenshot.
    EXPECT_UI = [
        "PixelVeil Test Account",
        "Account Information",
        "Account Settings",
        "Privacy Configuration",
    ]

    @classmethod
    def setUpClass(cls):
        # Fail loudly if the fixture is missing or unreadable — never skip. A
        # silent skip would let a broken fixture masquerade as "OCR passed".
        if not os.path.isfile(cls.FIXTURE):
            raise FileNotFoundError(
                f"Required OCR fixture not found: {cls.FIXTURE}. "
                "This test must not be skipped — the real-screenshot validation "
                "depends on it."
            )
        frame = cv2.imread(cls.FIXTURE)
        if frame is None or getattr(frame, "size", 0) == 0:
            raise AssertionError(
                f"OCR fixture could not be decoded by cv2.imread: {cls.FIXTURE}"
            )
        cls.frame = frame
        # Run OCR exactly as production would — no special params.
        cls.results = detect_text(frame)

        # Requirement: print every (text, bbox) so real OCR behaviour is
        # inspectable (visible with `pytest -s`, and on any failure).
        fh, fw = frame.shape[:2]
        print(f"\n[ocr_real_screen] frame={fw}x{fh}  detections={len(cls.results)}")
        for text, bbox in cls.results:
            print(f"  {bbox}  {text!r}")

    def _blob(self):
        """All detected text as one lowercased, whitespace-stripped string.

        Whitespace is normalised away (so label/value box splits and OCR
        spacing don't matter) but punctuation is preserved, so email/IPv4
        assertions still require the '.', '@' etc. to have been read correctly.
        """
        return _normalize(" ".join(t for t, _ in self.results))

    def _all_digits(self):
        return _digits(self._blob())

    def _find(self, predicate):
        """Return the first (text, bbox) whose text satisfies `predicate`, else
        None — used to report the actual OCR box backing each planted value."""
        for text, bbox in self.results:
            if predicate(text):
                return (text, bbox)
        return None

    # -- bbox invariants ---------------------------------------------------

    def test_all_bboxes_in_bounds(self):
        """Every returned bbox must be in-frame with positive area, so
        downstream code can slice frame[y:y+h, x:x+w] without bounds checks."""
        fh, fw = self.frame.shape[:2]
        self.assertIsInstance(self.results, list)
        self.assertGreater(len(self.results), 0, "no text detected at all")
        for text, bbox in self.results:
            self.assertIsInstance(text, str)
            x, y, w, h = bbox
            self.assertGreaterEqual(x, 0, f"x<0 for {text!r}")
            self.assertGreaterEqual(y, 0, f"y<0 for {text!r}")
            self.assertGreater(w, 0, f"w<=0 for {text!r}")
            self.assertGreater(h, 0, f"h<=0 for {text!r}")
            self.assertLessEqual(x + w, fw, f"x+w>{fw} for {text!r}")
            self.assertLessEqual(y + h, fh, f"y+h>{fh} for {text!r}")

    # -- planted PII (acceptance criteria) ---------------------------------

    def test_name_detected(self):
        target = _normalize(self.EXPECT_NAME)  # 'johndoe'
        hit = self._find(lambda t: target in _normalize(t))
        self.assertIsNotNone(
            hit,
            f"Name {self.EXPECT_NAME!r} not found. Closest blob: {self._blob()!r}",
        )
        self.assertIn(target, self._blob())

    def test_email_detected(self):
        # Punctuation-preserving check: the exact '.'/'@' structure must be read.
        target = self.EXPECT_EMAIL.lower()
        hit = self._find(lambda t: target in _normalize(t))
        self.assertIsNotNone(
            hit,
            f"Email {self.EXPECT_EMAIL!r} not found. Closest blob: {self._blob()!r}",
        )
        self.assertIn(target, self._blob())

    def test_phone_detected(self):
        # Digits-only comparison — grouping/spacing is irrelevant to the value.
        hit = self._find(lambda t: self.EXPECT_PHONE in _digits(t))
        self.assertIsNotNone(
            hit,
            f"Phone {self.EXPECT_PHONE!r} not found. Digits seen: {self._all_digits()!r}",
        )
        self.assertIn(self.EXPECT_PHONE, self._all_digits())

    def test_ipv4_detected(self):
        # Punctuation-preserving: the dotted-quad structure must be read exactly.
        target = self.EXPECT_IPV4.lower()
        hit = self._find(lambda t: target in _normalize(t))
        self.assertIsNotNone(
            hit,
            f"IPv4 {self.EXPECT_IPV4!r} not found. Closest blob: {self._blob()!r}",
        )
        self.assertIn(target, self._blob())

    def test_credit_card_detected(self):
        target = _digits(self.EXPECT_CARD)  # '4111111111111111'
        hit = self._find(lambda t: target in _digits(t))
        self.assertIsNotNone(
            hit,
            f"Card {self.EXPECT_CARD!r} not found. Digits seen: {self._all_digits()!r}",
        )
        self.assertIn(target, self._all_digits())

    # -- representative UI sanity check ------------------------------------

    def test_representative_ui_text(self):
        blob = self._blob()
        missing = [ui for ui in self.EXPECT_UI if _normalize(ui) not in blob]
        self.assertEqual(
            missing, [], f"Representative UI text missing from OCR: {missing}"
        )


if __name__ == "__main__":
    unittest.main()
