"""
Generates realistic-looking placeholder data for "fake_data" redaction mode
(e.g. "john.doe@example.com") — this is PixelVeil's core differentiator per
docs/roadmap.md section 3 (USP). The generated value is handed to
redactor.fake_data_region() as the replacement string; this module is
responsible only for *producing* that string — no OCR, PII matching,
rendering, or video processing.

Public API:
    generate(pii_type) -> str

`pii_type` is one of the PII types pii_matcher.py detects: "EMAIL", "PHONE",
"CARD", "IP" (case-insensitive). Names are intentionally not supported — the
detection side (pii_matcher.py / D7) matches only these structured formats;
free-form name detection is deferred to v2, so there is nothing upstream that
would flag a name region to replace.

Generated values are deliberately synthetic:
- emails use the reserved ``example.com`` domain (RFC 2606, guaranteed never a
  real address),
- IPs come from the ``192.0.2.0/24`` TEST-NET-1 documentation range (RFC 5737),
- phone numbers use the ``555-01xx`` range reserved for fictional use,
- card numbers are non-Luhn-valid so they can never pass real card validation.

They still *look* like plausible on-screen values so fake-data mode reads
naturally, but they are clearly test data and contain no real personal
information.
"""

import random

# Canonical supported PII types (matches pii_matcher.py's detected shapes).
_SUPPORTED = ("EMAIL", "PHONE", "CARD", "IP")

# Fake name fragments used only to build realistic-looking email local parts —
# not a "name" PII type, just filler for the address.
_FIRST_NAMES = (
    "alex", "jamie", "jordan", "taylor", "casey", "morgan", "riley", "sam",
)
_LAST_NAMES = (
    "doe", "test", "sample", "example", "smith", "jones", "user", "demo",
)


def _fake_email():
    """A synthetic email on the reserved example.com domain (RFC 2606)."""
    first = random.choice(_FIRST_NAMES)
    last = random.choice(_LAST_NAMES)
    return f"{first}.{last}@example.com"


def _fake_phone():
    """A synthetic US phone in the 555-01xx fictional range.

    The 555-0100..555-0199 block is officially reserved for fictional use, so
    these numbers never route to a real subscriber.
    """
    area = random.randint(200, 999)
    line = random.randint(100, 199)  # 01xx fictional block
    return f"({area}) 555-{line:04d}"


def _fake_card():
    """A synthetic 16-digit card number that is clearly test data.

    Prefixed with 4 (Visa-like display) so it reads as a card, grouped in the
    usual 4x4 layout. The digits are random and not Luhn-valid, so the value
    cannot pass real card validation.
    """
    groups = ["4000"]
    groups += [f"{random.randint(0, 9999):04d}" for _ in range(3)]
    return " ".join(groups)


def _fake_ip():
    """A synthetic IPv4 in the 192.0.2.0/24 TEST-NET-1 documentation range."""
    return f"192.0.2.{random.randint(1, 254)}"


_GENERATORS = {
    "EMAIL": _fake_email,
    "PHONE": _fake_phone,
    "CARD": _fake_card,
    "IP": _fake_ip,
}


def generate(pii_type):
    """Return a clearly-synthetic placeholder string for the given PII type.

    Args:
        pii_type: one of "EMAIL", "PHONE", "CARD", "IP" (case-insensitive).

    Returns:
        A non-empty placeholder string in the general format of that PII type,
        realistic enough to display naturally but clearly fake test data.

    Raises:
        ValueError: if `pii_type` is not one of the supported types.

    Example:
        >>> generate("EMAIL")            # doctest: +SKIP
        'jamie.doe@example.com'
    """
    if not isinstance(pii_type, str):
        raise ValueError(f"pii_type must be a string, got {type(pii_type).__name__}")
    key = pii_type.strip().upper()
    if key not in _GENERATORS:
        raise ValueError(
            f"Unsupported PII type {pii_type!r}. "
            f"Supported types: {', '.join(_SUPPORTED)}."
        )
    return _GENERATORS[key]()
