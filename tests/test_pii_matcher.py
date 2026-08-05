"""
Unit tests for core/pii_matcher.py — regex PII matching (DECISIONS.md D7).

Each pattern (EMAIL, PHONE, CARD, IPv4) is tested against a set of valid
strings it must match and a set of invalid strings it must reject. These
operate on plain strings (as produced by ocr_detector.detect_text), so no
image/OCR machinery is involved — fast, deterministic, offline.

Per TESTING.md's philosophy (bias toward catching false negatives), the
patterns are intentionally permissive; these tests assert that real PII shapes
always match, while still checking that clearly-unrelated text does not.
"""

import unittest

from core import pii_matcher
from core.pii_matcher import is_email, is_phone, is_card, is_ipv4


class TestEmailPattern(unittest.TestCase):
    def test_valid_emails(self):
        valid = [
            "user@example.com",
            "john.doe@example.com",
            "jane_doe@corp.io",
            "first.last+tag@sub.domain.co.uk",
            "a@b.co",
            "name123@test-domain.com",
        ]
        for s in valid:
            with self.subTest(s=s):
                self.assertTrue(is_email(s), f"should match email: {s!r}")

    def test_email_embedded_in_text(self):
        # OCR may return a label + value in one box.
        self.assertTrue(is_email("Email: john.doe@example.com"))

    def test_invalid_emails(self):
        invalid = [
            "",
            "not an email",
            "john.doe",
            "@example.com",
            "user@",
            "user@domain",  # no TLD
            "just text with no at sign",
            "192.168.1.1",
        ]
        for s in invalid:
            with self.subTest(s=s):
                self.assertFalse(is_email(s), f"should NOT match email: {s!r}")

    def test_none_is_false(self):
        self.assertFalse(is_email(None))


class TestPhonePattern(unittest.TestCase):
    def test_valid_phones(self):
        valid = [
            "555-123-4567",
            "(555) 123-4567",
            "555.123.4567",
            "5551234567",
            "+1 555-123-4567",
            "1-555-123-4567",
            "123-4567",  # local 7-digit
        ]
        for s in valid:
            with self.subTest(s=s):
                self.assertTrue(is_phone(s), f"should match phone: {s!r}")

    def test_phone_embedded_in_text(self):
        self.assertTrue(is_phone("Phone: 9876543210"))

    def test_invalid_phones(self):
        invalid = [
            "",
            "no digits here",
            "12345",  # too few digits
            "abc-def-ghij",
        ]
        for s in invalid:
            with self.subTest(s=s):
                self.assertFalse(is_phone(s), f"should NOT match phone: {s!r}")

    def test_none_is_false(self):
        self.assertFalse(is_phone(None))


class TestCardPattern(unittest.TestCase):
    def test_valid_cards(self):
        valid = [
            "4111 1111 1111 1111",  # Visa, grouped
            "4111-1111-1111-1111",  # dash-separated
            "4111111111111111",  # no separators, 16 digits
            "5500 0000 0000 0004",  # Mastercard
            "340000000000009",  # Amex, 15 digits
            "6011000000000004",  # Discover
        ]
        for s in valid:
            with self.subTest(s=s):
                self.assertTrue(is_card(s), f"should match card: {s!r}")

    def test_card_embedded_in_text(self):
        self.assertTrue(is_card("Card: 4111 1111 1111 1111"))

    def test_invalid_cards(self):
        invalid = [
            "",
            "1234",  # too short
            "not a card number",
            "12 34",
        ]
        for s in invalid:
            with self.subTest(s=s):
                self.assertFalse(is_card(s), f"should NOT match card: {s!r}")

    def test_none_is_false(self):
        self.assertFalse(is_card(None))


class TestIPv4Pattern(unittest.TestCase):
    def test_valid_ips(self):
        valid = [
            "192.168.1.105",
            "10.0.0.1",
            "8.8.8.8",
            "127.0.0.1",
            "255.255.255.0",
        ]
        for s in valid:
            with self.subTest(s=s):
                self.assertTrue(is_ipv4(s), f"should match IPv4: {s!r}")

    def test_ip_embedded_in_text(self):
        self.assertTrue(is_ipv4("IP Address: 192.168.1.105"))

    def test_invalid_ips(self):
        invalid = [
            "",
            "not an ip",
            "192.168",  # too few octets
            "192-168-1-1",  # wrong separator
            "just.some.words.here",
        ]
        for s in invalid:
            with self.subTest(s=s):
                self.assertFalse(is_ipv4(s), f"should NOT match IPv4: {s!r}")

    def test_none_is_false(self):
        self.assertFalse(is_ipv4(None))


class TestConfigurablePatterns(unittest.TestCase):
    """The get/set/reset pattern API added for the Settings screen. Patterns are
    process-global module state, so every test restores the shipped defaults in
    tearDown — an override must never leak into another test (or file)."""

    def tearDown(self):
        pii_matcher.reset_patterns()

    def test_get_patterns_returns_all_four_types_as_strings(self):
        patterns = pii_matcher.get_patterns()
        self.assertEqual(set(patterns), set(pii_matcher.PII_TYPES))
        for value in patterns.values():
            self.assertIsInstance(value, str)

    def test_get_defaults_match_active_before_any_override(self):
        self.assertEqual(pii_matcher.get_patterns(),
                         pii_matcher.get_default_patterns())

    def test_set_patterns_changes_matching(self):
        # Narrow EMAIL to only match a literal token; a real email then misses.
        self.assertTrue(is_email("user@example.com"))
        pii_matcher.set_patterns({"EMAIL": r"SECRET_TOKEN"})
        self.assertFalse(is_email("user@example.com"))
        self.assertTrue(is_email("here is SECRET_TOKEN inline"))
        # Other types are untouched by a partial update.
        self.assertTrue(is_ipv4("192.168.1.1"))

    def test_reset_restores_default_behavior(self):
        pii_matcher.set_patterns({"PHONE": r"NOPE"})
        self.assertFalse(is_phone("555-123-4567"))
        pii_matcher.reset_patterns()
        self.assertTrue(is_phone("555-123-4567"))
        self.assertEqual(pii_matcher.get_patterns(),
                         pii_matcher.get_default_patterns())

    def test_invalid_regex_rejected_without_corrupting_active(self):
        before = pii_matcher.get_patterns()
        with self.assertRaises(ValueError):
            pii_matcher.set_patterns({"EMAIL": r"("})  # unbalanced group
        # The bad edit left the active patterns (and matching) intact.
        self.assertEqual(pii_matcher.get_patterns(), before)
        self.assertTrue(is_email("user@example.com"))

    def test_all_or_nothing_when_one_of_several_is_invalid(self):
        before = pii_matcher.get_patterns()
        with self.assertRaises(ValueError):
            # First is valid, second is not — neither must be applied.
            pii_matcher.set_patterns({"EMAIL": r"foo", "PHONE": r"["})
        self.assertEqual(pii_matcher.get_patterns(), before)
        self.assertTrue(is_email("user@example.com"))

    def test_unknown_type_rejected(self):
        with self.assertRaises(ValueError):
            pii_matcher.set_patterns({"SSN": r"\d{9}"})

    def test_empty_or_non_string_rejected(self):
        for bad in ("", "   ", None, 123):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    pii_matcher.set_patterns({"EMAIL": bad})


if __name__ == "__main__":
    unittest.main()
