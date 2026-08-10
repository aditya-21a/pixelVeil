"""
Process-local settings for the test harness (Settings screen, design.md 2.4).

These are tuning knobs the developer changes while testing — OCR sample rate,
face-detection confidence, and the four PII regex patterns. This is a local,
single-user QA harness (DECISIONS.md D10), so the settings live in a plain
in-memory dict for the lifetime of the Flask process: no database, config file,
user accounts, Redis, or new dependency. Restarting the server resets to
defaults, which is the desired behavior for a test tool.

The store is the single source of truth for the *harness's* current values. The
PII patterns are additionally mirrored into core.pii_matcher's active patterns
(the pipeline consults those directly), so a saved regex actually changes what
subsequent processing matches. OCR sample rate and face confidence are read from
here when a job starts and passed into process_video().

Validation lives here so the Flask routes stay thin:
  * OCR sample rate must be a positive integer.
  * Face confidence must be a number in [0.0, 1.0].
  * Each PII pattern must be a compilable regex; an invalid one is rejected
    without disturbing the last valid configuration (pii_matcher enforces the
    all-or-nothing apply).
"""

import threading

from core import face_detector
from core import pii_matcher

# Defaults mirror the shipped pipeline behavior exactly, so "reset to defaults"
# (and a fresh process) reproduce untouched behavior:
#   * ocr_sample_rate=1  -> OCR every frame (video_pipeline default)
#   * face confidence    -> face_detector.DEFAULT_MIN_CONFIDENCE
#   * PII patterns       -> pii_matcher's shipped defaults
DEFAULT_OCR_SAMPLE_RATE = 1
DEFAULT_FACE_REDACTION_METHOD = "blur"
DEFAULT_FACE_BLUR_INTENSITY = "medium"
DEFAULT_FACE_PIXELATE_INTENSITY = "medium"


def _default_face_confidence():
    return float(face_detector.DEFAULT_MIN_CONFIDENCE)


# Guards reads/writes of the settings dict against concurrent requests (Flask
# dev server is threaded, and a job may start on another thread).
_LOCK = threading.Lock()

# The live settings. PII patterns are stored as source strings here for display/
# editing; core.pii_matcher holds the compiled, active copy.
_settings = {
    "ocr_sample_rate": DEFAULT_OCR_SAMPLE_RATE,
    "face_min_confidence": _default_face_confidence(),
    "face_redaction_method": DEFAULT_FACE_REDACTION_METHOD,
    "face_blur_intensity": DEFAULT_FACE_BLUR_INTENSITY,
    "face_pixelate_intensity": DEFAULT_FACE_PIXELATE_INTENSITY,
}


def defaults():
    """Return a fresh dict of the default settings (patterns included)."""
    return {
        "ocr_sample_rate": DEFAULT_OCR_SAMPLE_RATE,
        "face_min_confidence": _default_face_confidence(),
        "face_redaction_method": DEFAULT_FACE_REDACTION_METHOD,
        "face_blur_intensity": DEFAULT_FACE_BLUR_INTENSITY,
        "face_pixelate_intensity": DEFAULT_FACE_PIXELATE_INTENSITY,
        "pii_patterns": pii_matcher.get_default_patterns(),
    }


def get_settings():
    """Return the current settings as a plain dict, safe to hand to the UI.

    Includes the live PII pattern strings (read from core.pii_matcher, the
    authoritative active copy) plus the defaults, so the Settings screen can
    show current values and offer a reset without extra round-trips.
    """
    with _LOCK:
        return {
            "ocr_sample_rate": _settings["ocr_sample_rate"],
            "face_min_confidence": _settings["face_min_confidence"],
            "face_redaction_method": _settings["face_redaction_method"],
            "face_blur_intensity": _settings["face_blur_intensity"],
            "face_pixelate_intensity": _settings["face_pixelate_intensity"],
            "pii_patterns": pii_matcher.get_patterns(),
            "defaults": defaults(),
        }


def _validate_ocr_sample_rate(value):
    """Coerce/validate an OCR sample rate to a positive int, else ValueError."""
    if isinstance(value, bool):
        raise ValueError("OCR sample rate must be a positive integer.")
    # Accept an int, or a string of digits (form input arrives as text).
    if isinstance(value, str):
        value = value.strip()
        if not value.lstrip("+").isdigit():
            raise ValueError("OCR sample rate must be a positive integer.")
        value = int(value)
    if not isinstance(value, int) or value < 1:
        raise ValueError("OCR sample rate must be a positive integer (1 or more).")
    return value


def _validate_face_confidence(value):
    """Coerce/validate a face confidence to a float in [0.0, 1.0], else ValueError."""
    if isinstance(value, bool):
        raise ValueError("Face confidence must be a number between 0.0 and 1.0.")
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ValueError("Face confidence must be a number between 0.0 and 1.0.")
    if not (0.0 <= value <= 1.0):
        raise ValueError("Face confidence must be between 0.0 and 1.0.")
    return value


def _validate_face_redaction_method(value):
    if value not in ("blur", "pixelate"):
        raise ValueError("Face redaction method must be 'blur' or 'pixelate'.")
    return value


def _validate_intensity(value):
    if value not in ("low", "medium", "high"):
        raise ValueError("Intensity must be 'low', 'medium', or 'high'.")
    return value


def update_settings(ocr_sample_rate=None, face_min_confidence=None,
                    pii_patterns=None, face_redaction_method=None,
                    face_blur_intensity=None, face_pixelate_intensity=None):
    """Validate and apply a partial settings update; return the new settings.

    Only the supplied fields change. Validation is all-or-nothing across the
    whole call: every field is validated (and PII patterns compiled) *before*
    anything is applied, so a single invalid value — a bad OCR rate, an
    out-of-range confidence, or an uncompilable regex — rejects the entire
    update with ValueError and leaves the previous valid configuration intact.

    `pii_patterns` is a ``{type: regex_string}`` mapping restricted to the four
    known types (EMAIL/PHONE/CARD/IP); it is pushed into core.pii_matcher so the
    pipeline's matching actually changes. Raises ValueError on any invalid input.
    """
    new_rate = None
    new_conf = None
    new_method = None
    new_blur_int = None
    new_pix_int = None

    if ocr_sample_rate is not None:
        new_rate = _validate_ocr_sample_rate(ocr_sample_rate)
    if face_min_confidence is not None:
        new_conf = _validate_face_confidence(face_min_confidence)
    if face_redaction_method is not None:
        new_method = _validate_face_redaction_method(face_redaction_method)
    if face_blur_intensity is not None:
        new_blur_int = _validate_intensity(face_blur_intensity)
    if face_pixelate_intensity is not None:
        new_pix_int = _validate_intensity(face_pixelate_intensity)
    if pii_patterns is not None:
        if not isinstance(pii_patterns, dict) or not pii_patterns:
            raise ValueError("PII patterns must be a non-empty mapping.")
        # pii_matcher.set_patterns compiles all-or-nothing and raises ValueError
        # on a bad regex/unknown type without touching the active patterns.
        pii_matcher.set_patterns(pii_patterns)

    with _LOCK:
        if new_rate is not None:
            _settings["ocr_sample_rate"] = new_rate
        if new_conf is not None:
            _settings["face_min_confidence"] = new_conf
        if new_method is not None:
            _settings["face_redaction_method"] = new_method
        if new_blur_int is not None:
            _settings["face_blur_intensity"] = new_blur_int
        if new_pix_int is not None:
            _settings["face_pixelate_intensity"] = new_pix_int

    return get_settings()


def reset_settings():
    """Restore all settings — OCR rate, face confidence, PII patterns — to defaults."""
    pii_matcher.reset_patterns()
    with _LOCK:
        _settings["ocr_sample_rate"] = DEFAULT_OCR_SAMPLE_RATE
        _settings["face_min_confidence"] = _default_face_confidence()
        _settings["face_redaction_method"] = DEFAULT_FACE_REDACTION_METHOD
        _settings["face_blur_intensity"] = DEFAULT_FACE_BLUR_INTENSITY
        _settings["face_pixelate_intensity"] = DEFAULT_FACE_PIXELATE_INTENSITY
    return get_settings()


def processing_kwargs():
    """Return the pipeline kwargs a newly started job should use.

    Reads the live OCR sample rate and face confidence so a job started after a
    save picks up the current values. PII patterns are applied globally in
    core.pii_matcher (not per-call), so they take effect without being threaded
    through here.
    """
    with _LOCK:
        return {
            "ocr_sample_rate": _settings["ocr_sample_rate"],
            "face_min_confidence": _settings["face_min_confidence"],
            "face_redaction_method": _settings["face_redaction_method"],
            "face_blur_intensity": _settings["face_blur_intensity"],
            "face_pixelate_intensity": _settings["face_pixelate_intensity"],
        }
