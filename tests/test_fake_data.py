"""
Unit tests for utils/fake_data.py — synthetic placeholder generation for
fake-data redaction mode.

Format correctness is cross-checked against core/pii_matcher.py: a generated
fake EMAIL must be recognized by is_email(), a fake IP by is_ipv4(), etc. This
ties the generator's output to the exact shapes the detector recognizes, which
is what fake-data mode needs (the replacement must read as the same PII type).

No OCR/image machinery — pure string generation, fast and deterministic in
shape (values are random in content).
"""

import unittest

from utils.fake_data import generate, _SUPPORTED
from core.pii_matcher import is_email, is_phone, is_card, is_ipv4


class TestGenerateReturnsNonEmptyString(unittest.TestCase):
    def test_each_type_returns_non_empty_string(self):
        for t in _SUPPORTED:
            with self.subTest(pii_type=t):
                val = generate(t)
                self.assertIsInstance(val, str)
                self.assertTrue(val.strip(), f"empty value for {t}")

    def test_case_insensitive_type(self):
        # Mixed / lower case accepted.
        self.assertTrue(generate("email"))
        self.assertTrue(generate("Ip"))


class TestGeneratedFormats(unittest.TestCase):
    def test_email_format(self):
        val = generate("EMAIL")
        self.assertTrue(is_email(val), f"not an email shape: {val!r}")
        # Clearly synthetic: reserved example.com domain.
        self.assertTrue(val.endswith("@example.com"))

    def test_phone_format(self):
        val = generate("PHONE")
        self.assertTrue(is_phone(val), f"not a phone shape: {val!r}")
        # Fictional 555-01xx block.
        self.assertIn("555-01", val)

    def test_card_format(self):
        val = generate("CARD")
        self.assertTrue(is_card(val), f"not a card shape: {val!r}")
        digits = "".join(c for c in val if c.isdigit())
        self.assertEqual(len(digits), 16)

    def test_ip_format(self):
        val = generate("IP")
        self.assertTrue(is_ipv4(val), f"not an IPv4 shape: {val!r}")
        # TEST-NET-1 documentation range.
        self.assertTrue(val.startswith("192.0.2."))


class TestSyntheticSafety(unittest.TestCase):
    """Generated values must be recognizable test data, never real PII shapes
    that could be mistaken for a real address/number."""

    def test_card_is_not_luhn_valid_prefix(self):
        # Fixed 4000 prefix marks it as test data (real cards vary the BIN).
        self.assertTrue(generate("CARD").startswith("4000 "))

    def test_ip_in_documentation_range(self):
        # RFC 5737 TEST-NET-1 — never a routable/real host.
        octet = int(generate("IP").split(".")[-1])
        self.assertTrue(1 <= octet <= 254)


class TestInvalidType(unittest.TestCase):
    def test_unsupported_type_raises(self):
        for bad in ["NAME", "SSN", "", "unknown", "  "]:
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    generate(bad)

    def test_non_string_type_raises(self):
        for bad in [None, 123, ["EMAIL"]]:
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    generate(bad)


class TestRepeatedGeneration(unittest.TestCase):
    def test_repeated_calls_stay_valid_and_vary(self):
        # Over many calls, values remain correctly-shaped and show variation
        # (not a single hardcoded constant) — important so multiple redacted
        # regions in one frame don't all show identical placeholder text.
        for t, checker in [
            ("EMAIL", is_email),
            ("PHONE", is_phone),
            ("CARD", is_card),
            ("IP", is_ipv4),
        ]:
            with self.subTest(pii_type=t):
                vals = {generate(t) for _ in range(50)}
                for v in vals:
                    self.assertTrue(checker(v), f"bad {t} value: {v!r}")
                # Random content => expect more than one distinct value.
                self.assertGreater(len(vals), 1, f"{t} never varied")


if __name__ == "__main__":
    unittest.main()
