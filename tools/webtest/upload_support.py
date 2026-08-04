"""
Pure, UI-agnostic helpers for the Upload screen (docs/design.md Screen 1).

Kept separate from server.py (Flask routing) and from core/ (the pipeline) so
the two pieces the pipeline-wiring task will depend on — input validation and
the display->video coordinate mapping — are plain functions with no Flask or
OpenCV request context, and can be unit-tested directly.

Nothing here imports Flask. `first_frame` uses OpenCV only to decode frame 0.
"""

import os

import cv2

# Container/extensions we accept for a screen recording. Deliberately a small
# allowlist of common screen-recorder outputs (OBS/Loom/QuickTime/Windows) —
# validation is by extension here; the real decodability check is first_frame().
ALLOWED_VIDEO_EXTENSIONS = frozenset(
    {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
)


def is_allowed_video_filename(filename):
    """True if `filename` has an allowed video extension (case-insensitive).

    Pure string check — does not touch the filesystem. An empty/None name or a
    name with no extension or an unknown extension returns False.
    """
    if not filename:
        return False
    _, ext = os.path.splitext(str(filename))
    return ext.lower() in ALLOWED_VIDEO_EXTENSIONS


def normalize_rect(x0, y0, x1, y1):
    """Normalize a click-drag (two corner points) to (x, y, w, h) with w,h >= 0.

    The user may drag in any direction (e.g. bottom-right -> top-left); this
    returns the top-left origin plus non-negative width/height.
    """
    x = min(x0, x1)
    y = min(y0, y1)
    w = abs(x1 - x0)
    h = abs(y1 - y0)
    return x, y, w, h


def display_to_video_rect(rect, display_size, video_size):
    """Map a rectangle drawn on the *displayed* frame to ORIGINAL video pixels.

    ZoneManager.add_zone() expects zones in video-frame pixel coordinates, not
    the (usually smaller) browser/canvas coordinates the user actually drew in.
    This is the conversion that keeps a drawn box over the right region.

    Args:
        rect: (x, y, w, h) in display/canvas coordinates. May come straight from
            normalize_rect(); w/h are treated as non-negative.
        display_size: (display_w, display_h) — the on-screen size of the frame
            the user drew on (e.g. a canvas scaled down to fit the page).
        video_size: (video_w, video_h) — the original frame's pixel dimensions.

    Returns:
        (x, y, w, h) ints in video-pixel space, clamped to the frame so the zone
        never extends past the real frame bounds. Independent x/y scaling means
        non-uniform resizes (different scale per axis) are handled correctly.

    Raises:
        ValueError if any dimension is non-positive (a zero-area display or
        video makes the mapping undefined).
    """
    x, y, w, h = rect
    disp_w, disp_h = display_size
    vid_w, vid_h = video_size
    if disp_w <= 0 or disp_h <= 0:
        raise ValueError(f"display_size must be positive, got {display_size!r}")
    if vid_w <= 0 or vid_h <= 0:
        raise ValueError(f"video_size must be positive, got {video_size!r}")

    sx = vid_w / disp_w
    sy = vid_h / disp_h

    # Scale the two edges independently, then derive w/h, so rounding stays
    # consistent with the mapped corners (avoids a 1px drift vs scaling w/h).
    vx0 = x * sx
    vy0 = y * sy
    vx1 = (x + abs(w)) * sx
    vy1 = (y + abs(h)) * sy

    # Clamp to the frame.
    vx0 = max(0.0, min(vx0, vid_w))
    vy0 = max(0.0, min(vy0, vid_h))
    vx1 = max(0.0, min(vx1, vid_w))
    vy1 = max(0.0, min(vy1, vid_h))

    ix = int(round(vx0))
    iy = int(round(vy0))
    iw = int(round(vx1 - vx0))
    ih = int(round(vy1 - vy0))
    return ix, iy, iw, ih


def first_frame(video_path):
    """Return frame 0 of `video_path` as a BGR ndarray, or None if undecodable.

    The capture is always released (Windows keeps the file locked otherwise).
    This doubles as the real "is this actually a video?" check — a file that
    passed the extension allowlist but can't be decoded returns None.
    """
    cap = cv2.VideoCapture(video_path)
    try:
        if not cap.isOpened():
            return None
        ok, frame = cap.read()
        return frame if ok else None
    finally:
        cap.release()


def frame_size(frame):
    """(width, height) of a BGR frame ndarray."""
    h, w = frame.shape[:2]
    return int(w), int(h)
