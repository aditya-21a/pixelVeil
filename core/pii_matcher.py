"""
Regex-based PII matching against OCR text output. See docs/DECISIONS.md D7
for why regex was chosen over an NER/ML approach for v1.

Patterns to implement: EMAIL, PHONE, CARD, IP.
"""

import re
