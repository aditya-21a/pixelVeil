"""
Generates realistic-looking placeholder data for "fake_data" redaction mode
(e.g. "Test User 1", "john.doe@example.com") — this is PixelVeil's core
differentiator per docs/roadmap.md section 3 (USP).

    Args:
        pii_type: one of "EMAIL", "PHONE", "CARD", "IP".

    Returns:
        a placeholder string clearly distinguishable from real data.
    """
