"""
Regex-based PII matching against OCR text output. See docs/DECISIONS.md D7
for why regex was chosen over an NER/ML approach for v1.

Public API:
    is_email(text) -> bool
    is_phone(text) -> bool
    is_card(text) -> bool
    is_ipv4(text) -> bool
    find_pii(text) -> list[(pii_type, start, end, value)]
    get_patterns() / get_default_patterns() -> {type: regex_string}
    set_patterns({type: regex_string}) / reset_patterns()

The ``is_*()`` functions answer only "does this text contain PII of type X?".
``find_pii()`` additionally reports *where* each PII value sits (its character
span), so a caller holding one OCR box can redact only the value's sub-region
and leave a surrounding label ("Email:", "CARD", ...) visible.

Each is_*() function returns True if the given text matches the corresponding
PII pattern. These are designed for OCR output, so they're deliberately
permissive (bias toward recall over precision) — a false positive here is
merely an extra box sent to the redactor, while a false negative is a privacy
failure.

The four patterns (EMAIL / PHONE / CARD / IP) ship with the defaults below and
are what the pipeline uses unless a caller overrides them via set_patterns()
(used by the test-harness Settings screen for tuning; validated, all-or-nothing,
and restorable with reset_patterns()). No new PII categories are added in v1.

Patterns implemented: EMAIL, PHONE (US-focused 10-digit), CARD (13-19 digits),
and IP (IPv4 dotted-quad).
"""

import re

# EMAIL: standard user@domain.tld format. Accepts common chars in the local
# part and domain. Deliberately permissive — OCR may produce minor noise around
# punctuation, and over-matching is safer than under-matching for redaction.
_EMAIL_PATTERN = re.compile(
    r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
)

# PHONE: US-focused 10-digit pattern. Matches (555) 123-4567, 555-123-4567,
# 555.123.4567, 5551234567, and similar variants. Does not validate area code
# ranges (that's overkill for v1 — OCR output is noisy, and we want to catch
# everything that looks like a phone number on screen).
_PHONE_PATTERN = re.compile(
    r'\b'
    r'(?:\+?1[-.\s]?)?'  # optional country code +1
    r'(?:\(?\d{3}\)?[-.\s]?)?'  # optional area code with optional parens
    r'\d{3}[-.\s]?\d{4}'  # main 7 digits (3-4 format)
    r'\b'
)

# CARD: credit card number, 13-19 digits (covers Visa/MC/Amex/Discover/etc.),
# with optional spaces, dashes, or no separators. OCR often preserves the
# grouped display format (4111 1111 1111 1111), so accept those. Does NOT
# validate Luhn checksum — that would reject test cards and add complexity for
# no redaction benefit (if it looks like a card, redact it).
_CARD_PATTERN = re.compile(
    r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{3,4}\b'  # 13-16 digit grouped
    r'|\b\d{13,19}\b'  # or just 13-19 digits with no separators
)

# IP: IPv4 dotted-quad (four octets 0-255 separated by dots). Strict format but
# does not enforce valid octet ranges (e.g. 999.999.999.999 would match) — for
# redaction purposes, "looks like an IP" is the criterion, not "is a routable
# IP." Real IPs like 192.168.1.105 and 10.0.0.1 will always match.
_IPV4_PATTERN = re.compile(
    r'\b(?:\d{1,3}\.){3}\d{1,3}\b'
)

# The four supported PII types, in this fixed set (v1 adds no new categories).
PII_TYPES = ("EMAIL", "PHONE", "CARD", "IP")

# Precedence for resolving overlapping matches in find_pii(). EMAIL and IP are
# resolved before CARD and PHONE because their punctuation makes them
# unambiguous, whereas the digit-oriented CARD/PHONE shapes are broad and could
# otherwise claim the digits of an IP or the local part of an email. When two
# patterns match overlapping characters, the earlier (higher-precedence) type
# wins and the overlapping lower-precedence match is dropped. This mirrors the
# single-type classification order the pipeline used previously, so a box that
# holds only one value still classifies exactly as it did before.
_MATCH_PRECEDENCE = ("EMAIL", "IP", "CARD", "PHONE")

# Default compiled patterns, keyed by PII type. These are the shipped behavior;
# the four is_*() functions consult `_active_patterns` (below), which starts as
# a copy of these. The test harness Settings screen may override individual
# patterns for tuning via set_patterns(); nothing else in the pipeline changes.
_DEFAULT_PATTERNS = {
    "EMAIL": _EMAIL_PATTERN,
    "PHONE": _PHONE_PATTERN,
    "CARD": _CARD_PATTERN,
    "IP": _IPV4_PATTERN,
}

# Currently active compiled patterns. Process-local mutable state: overriding a
# pattern here (set_patterns) transparently changes what is_*() — and therefore
# the pipeline's PII classification, which calls these functions — matches. The
# default is exactly the shipped patterns, so behavior is unchanged until a
# caller explicitly overrides it, and reset_patterns() restores the defaults.
_active_patterns = dict(_DEFAULT_PATTERNS)


def get_patterns():
    """Return the currently active PII regex **source strings**, keyed by type.

    Returns a dict with the keys in ``PII_TYPES`` (``EMAIL``/``PHONE``/``CARD``/
    ``IP``); each value is the pattern's source string, suitable for displaying
    or editing in the Settings screen.
    """
    return {key: _active_patterns[key].pattern for key in PII_TYPES}


def get_default_patterns():
    """Return the default (shipped) PII regex source strings, keyed by type."""
    return {key: _DEFAULT_PATTERNS[key].pattern for key in PII_TYPES}


def set_patterns(mapping):
    """Override one or more PII patterns from a ``{type: regex_string}`` mapping.

    Validation is all-or-nothing: every supplied pattern is compiled first, and
    the active patterns are only replaced if *all* of them are valid. A bad
    regex (or unknown type) raises ``ValueError`` and leaves the previously
    active configuration untouched — an invalid edit can never corrupt matching.

    Only the four known ``PII_TYPES`` are accepted (v1 adds no new categories).
    Keys not present in `mapping` keep their current pattern.
    """
    if not isinstance(mapping, dict):
        raise ValueError("patterns must be a mapping of PII type -> regex string")

    compiled = {}
    for key, source in mapping.items():
        if key not in PII_TYPES:
            raise ValueError(
                f"unknown PII type {key!r}; expected one of {PII_TYPES}"
            )
        if not isinstance(source, str) or source.strip() == "":
            raise ValueError(f"pattern for {key} must be a non-empty string")
        try:
            compiled[key] = re.compile(source)
        except re.error as exc:
            raise ValueError(f"invalid regex for {key}: {exc}") from exc

    # All valid — apply atomically (only now do we mutate the active state).
    _active_patterns.update(compiled)


def reset_patterns():
    """Restore all PII patterns to their shipped defaults."""
    _active_patterns.clear()
    _active_patterns.update(_DEFAULT_PATTERNS)


def is_email(text):
    """Return True if `text` matches the EMAIL pattern.

    Args:
        text: A string, typically one OCR detection box's recognized text.

    Returns:
        True if the text contains an email address, False otherwise.

    Example:
        >>> is_email("user@example.com")
        True
        >>> is_email("not an email")
        False
    """
    if not text:
        return False
    return _active_patterns["EMAIL"].search(text) is not None


def is_phone(text):
    """Return True if `text` matches the PHONE pattern (US 10-digit).

    Args:
        text: A string, typically one OCR detection box's recognized text.

    Returns:
        True if the text contains a phone number, False otherwise.

    Example:
        >>> is_phone("555-123-4567")
        True
        >>> is_phone("not a phone")
        False
    """
    if not text:
        return False
    return _active_patterns["PHONE"].search(text) is not None


def is_card(text):
    """Return True if `text` matches the CARD (credit card) pattern.

    Args:
        text: A string, typically one OCR detection box's recognized text.

    Returns:
        True if the text contains a credit card number, False otherwise.

    Example:
        >>> is_card("4111 1111 1111 1111")
        True
        >>> is_card("1234")
        False
    """
    if not text:
        return False
    return _active_patterns["CARD"].search(text) is not None


def is_ipv4(text):
    """Return True if `text` matches the IPv4 address pattern.

    Args:
        text: A string, typically one OCR detection box's recognized text.

    Returns:
        True if the text contains an IPv4 address, False otherwise.

    Example:
        >>> is_ipv4("192.168.1.105")
        True
        >>> is_ipv4("not an ip")
        False
    """
    if not text:
        return False
    return _active_patterns["IP"].search(text) is not None


def find_pii(text):
    """Locate every PII value inside `text` and report where each one sits.

    Returns a list of ``(pii_type, start, end, value)`` tuples, one per matched
    PII value, sorted by start position. ``start``/``end`` are character offsets
    into `text` forming a half-open slice, so ``text[start:end] == value``. The
    caller (video_pipeline) maps that span onto a tighter sub-region of the OCR
    box, so only the value — not a leading label like ``"Email:"`` or ``"CARD"``
    — gets redacted.

    ``value`` is the exact matched substring. The patterns are ``\\b``-anchored,
    so surrounding whitespace and label text are naturally excluded; no manual
    stripping of leading/trailing spaces is needed.

    When two patterns match overlapping characters (e.g. the broad PHONE/CARD
    digit shapes catching part of an IP address), the higher-precedence type in
    ``_MATCH_PRECEDENCE`` wins and the overlapping lower-precedence match is
    dropped. A box holding a single value therefore classifies to exactly the
    same type the pipeline assigned before this function existed.

    Multiple *non-overlapping* PII values in one string each get their own
    tuple (e.g. an email and a phone on the same OCR line).

    Args:
        text: a string, typically one OCR detection box's recognized text.

    Returns:
        A list of ``(pii_type, start, end, value)`` tuples sorted by ``start``;
        an empty list for empty/None text or text containing no PII.

    Example:
        >>> find_pii("Email: john.doe@example.com")
        [('EMAIL', 7, 27, 'john.doe@example.com')]
        >>> find_pii("no pii here")
        []
    """
    if not text:
        return []

    # (start, end, pii_type, value) for spans accepted so far, in precedence
    # order. finditer within one pattern already yields non-overlapping matches;
    # the overlap guard below only needs to reject a lower-precedence span that
    # collides with an already-accepted higher-precedence one.
    accepted = []
    for pii_type in _MATCH_PRECEDENCE:
        pattern = _active_patterns[pii_type]
        for match in pattern.finditer(text):
            start, end = match.start(), match.end()
            if end <= start:
                continue  # zero-width match: nothing to redact
            overlaps = any(
                start < a_end and a_start < end
                for a_start, a_end, _, _ in accepted
            )
            if overlaps:
                continue
            accepted.append((start, end, pii_type, match.group()))

    accepted.sort(key=lambda item: item[0])
    return [(pii_type, start, end, value)
            for start, end, pii_type, value in accepted]
