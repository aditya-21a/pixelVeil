"""
Stores and applies user-marked static redaction zones — fixed regions
redacted on every frame regardless of detection (e.g. "always cover this
CRM sidebar").

Zones are ``(x, y, w, h)`` integer tuples in **actual video-frame pixel
coordinates** (the same convention as face_detector/ocr_detector/redactor).
Mapping from GUI canvas coordinates to video pixels is the caller's job — this
module only stores and applies pixel-space zones, and never touches detection,
OCR, PII matching, fake-data generation, video iteration, or GUI/canvas logic.

Rendering is delegated to core.redactor (blur / solid box), so zone redaction
reuses exactly the same drawing code as detection-driven redaction and inherits
its safe clamping of edge / partially-out-of-frame / off-frame boxes.
"""

from core import redactor


class ZoneManager:
    def __init__(self):
        self.zones = []  # list of (x, y, w, h) in video-frame pixel coords

    def add_zone(self, bbox):
        """Store a static zone.

        Args:
            bbox: an ``(x, y, w, h)`` tuple in video-frame pixel coordinates.
                ``w`` and ``h`` must be positive.

        Returns:
            The index of the newly added zone.

        Raises:
            ValueError: if `bbox` is not a 4-element box or has non-positive
                area. Rejecting invalid zones at insertion keeps the stored
                list clean and gives the caller immediate, predictable feedback
                rather than a silently-ignored zone at apply time.
        """
        if bbox is None or len(bbox) != 4:
            raise ValueError(f"zone must be a 4-tuple (x, y, w, h), got {bbox!r}")
        x, y, w, h = (int(v) for v in bbox)
        if w <= 0 or h <= 0:
            raise ValueError(f"zone must have positive area, got w={w}, h={h}")
        self.zones.append((x, y, w, h))
        return len(self.zones) - 1

    def remove_zone(self, index):
        """Remove the stored zone at `index`.

        Raises:
            IndexError: if `index` is out of range (standard list semantics).
        """
        del self.zones[index]

    def get_zones(self):
        """Return the list of stored zones, ``(x, y, w, h)`` in pixel coords."""
        return self.zones

    def clear(self):
        """Remove all stored zones."""
        self.zones = []

    def apply_zones(self, frame, mode="blur", color=(0, 0, 0)):
        """Apply every stored zone to `frame`, in place, via core.redactor.

        The same stored zones are applied identically each call, so calling
        this once per video frame gives 100%-consistent static-zone coverage
        (TESTING.md 3.4). Each zone is drawn independently, so multiple zones
        compose; redactor clamps any zone that touches or extends past a frame
        edge, and a zone fully outside the frame is a safe no-op.

        Args:
            frame: OpenCV BGR numpy array.
            mode: "blur" (Gaussian blur the zone) or "box" (solid `color` fill).
            color: BGR fill color used when mode == "box".

        Returns:
            The (same) frame.

        Raises:
            ValueError: if `mode` is not "blur" or "box".
        """
        if mode not in ("blur", "box"):
            raise ValueError(f"mode must be 'blur' or 'box', got {mode!r}")
        for zone in self.zones:
            if mode == "blur":
                redactor.blur_region(frame, zone)
            else:
                redactor.box_region(frame, zone, color=color)
        return frame
