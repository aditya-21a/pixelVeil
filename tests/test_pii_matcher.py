"""
Unit tests for core/pii_matcher.py. See docs/TESTING.md section 3.2 for
the full test case list (valid PII formats + non-PII text that must NOT
be flagged).
"""

import unittest
from core.pii_matcher import match_pii


class TestPiiMatcher(unittest.TestCase):
    def test_email_match(self):
        self.assertEqual(match_pii("contact me at test@example.com"), "EMAIL")

    def test_no_false_positive_on_plain_text(self):
        self.assertIsNone(match_pii("Welcome to the dashboard"))


if __name__ == "__main__":
    unittest.main()
