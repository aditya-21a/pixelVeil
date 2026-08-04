"""
Local Flask app — the test harness UI described in docs/design.md.
Serves Upload / Processing / Results / Settings screens and (later) triggers
core/video_pipeline.py, streaming progress back to the browser.

This is a development/QA tool only, not the shipped product (see
docs/DECISIONS.md D10).

Upload screen state (video reference, mode, drawn zones) is held in a simple
in-memory store keyed by an upload id. It is intentionally process-local and
non-persistent — this is a single-user local harness — and is the reference the
next task ("wire Process Video to video_pipeline.py") will read from. Zones are
stored as (x, y, w, h) tuples in ORIGINAL video-pixel coordinates, exactly the
format core.zone_manager.ZoneManager.add_zone() expects.
"""

import os
import uuid

import cv2
from flask import (
    Flask,
    jsonify,
    render_template,
    request,
    send_file,
    url_for,
)
from werkzeug.utils import secure_filename

from . import upload_support

app = Flask(__name__)

# Generous cap so real screen recordings upload, but bad/huge input fails fast
# with a clear 413 rather than exhausting memory.
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024  # 2 GiB

UPLOAD_DIR = os.path.join(app.root_path, "uploads")

VALID_MODES = ("blur", "fake_data")

# upload id -> {"video_path", "frame_path", "width", "height", "mode", "zones"}
# Process-local; see module docstring. Not thread-safe by design (local, single
# user, Flask dev server).
_STATE = {}


# --- helpers -----------------------------------------------------------------
def _err(code, message):
    return jsonify({"error": message}), code


def _public_state(uid, st):
    """State view safe to hand back to the browser (no absolute paths)."""
    return {
        "id": uid,
        "filename": os.path.basename(st["video_path"]),
        "width": st["width"],
        "height": st["height"],
        "mode": st["mode"],
        "zones": st["zones"],
        "frame_url": url_for("frame", uid=uid),
    }


# --- screens (static pages; see base.html for nav) ---------------------------
@app.route("/")
def upload():
    return render_template("upload.html", active="upload")


@app.route("/processing")
def processing():
    return render_template("processing.html", active="processing")


@app.route("/results")
def results():
    return render_template("results.html", active="results")


@app.route("/settings")
def settings():
    return render_template("settings.html", active="settings")


# --- Upload screen API -------------------------------------------------------
@app.route("/upload", methods=["POST"])
def upload_video():
    """Accept a local video, validate it, extract + store its first frame.

    Validation is two-stage: an extension allowlist (cheap, clear rejection of
    obviously-wrong files) followed by an actual OpenCV decode of frame 0 (the
    real "is this a video?" test — catches a .mp4-named non-video).
    """
    if "video" not in request.files:
        return _err(400, "No file was uploaded (expected form field 'video').")
    file = request.files["video"]
    if not file or file.filename == "":
        return _err(400, "No file selected.")

    filename = secure_filename(file.filename)
    if not upload_support.is_allowed_video_filename(filename):
        allowed = ", ".join(sorted(upload_support.ALLOWED_VIDEO_EXTENSIONS))
        return _err(400, f"Unsupported file type. Allowed video types: {allowed}.")

    uid = uuid.uuid4().hex
    dest_dir = os.path.join(UPLOAD_DIR, uid)
    os.makedirs(dest_dir, exist_ok=True)
    video_path = os.path.join(dest_dir, filename)
    file.save(video_path)

    frame = upload_support.first_frame(video_path)
    if frame is None:
        # Not decodable — clean up so a bad upload leaves nothing behind.
        try:
            os.remove(video_path)
            os.rmdir(dest_dir)
        except OSError:
            pass
        return _err(400, "Could not read this file as a video (no decodable frames).")

    width, height = upload_support.frame_size(frame)
    frame_path = os.path.join(dest_dir, "frame0.png")
    cv2.imwrite(frame_path, frame)

    _STATE[uid] = {
        "video_path": video_path,
        "frame_path": frame_path,
        "width": width,
        "height": height,
        "mode": "blur",
        "zones": [],
    }
    return jsonify(_public_state(uid, _STATE[uid]))


@app.route("/frame/<uid>")
def frame(uid):
    """Serve the extracted first frame (PNG) for the zone-drawing canvas."""
    st = _STATE.get(uid)
    if not st:
        return _err(404, "Unknown upload id.")
    return send_file(st["frame_path"], mimetype="image/png")


@app.route("/mode", methods=["POST"])
def set_mode():
    """Persist the selected redaction mode ('blur' | 'fake_data')."""
    data = request.get_json(silent=True) or {}
    st = _STATE.get(data.get("id"))
    if not st:
        return _err(404, "Unknown upload id.")
    mode = data.get("mode")
    if mode not in VALID_MODES:
        return _err(400, f"Invalid mode {mode!r}; expected one of {VALID_MODES}.")
    st["mode"] = mode
    return jsonify({"mode": mode})


@app.route("/zone", methods=["POST"])
def add_zone():
    """Add one drawn zone, converting display coords -> video-pixel coords.

    Body: {id, rect:{x,y,w,h}, display:{w,h}} where rect is in the coordinate
    space of the displayed frame and display is that frame's on-screen size.
    The authoritative conversion happens here (server knows the true video
    dimensions), so a resized/zoomed canvas can never desync the mapping.
    """
    data = request.get_json(silent=True) or {}
    st = _STATE.get(data.get("id"))
    if not st:
        return _err(404, "Unknown upload id.")
    rect = data.get("rect") or {}
    display = data.get("display") or {}
    try:
        video_rect = upload_support.display_to_video_rect(
            (rect["x"], rect["y"], rect["w"], rect["h"]),
            (display["w"], display["h"]),
            (st["width"], st["height"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return _err(400, f"Invalid zone: {exc}")

    if video_rect[2] <= 0 or video_rect[3] <= 0:
        return _err(400, "Zone has zero area in video pixels; draw a larger box.")

    st["zones"].append(list(video_rect))
    return jsonify({
        "index": len(st["zones"]) - 1,
        "video_rect": list(video_rect),
        "zones": st["zones"],
    })


@app.route("/zone/delete", methods=["POST"])
def delete_zone():
    """Delete one zone by its index."""
    data = request.get_json(silent=True) or {}
    st = _STATE.get(data.get("id"))
    if not st:
        return _err(404, "Unknown upload id.")
    index = data.get("index")
    if not isinstance(index, int) or not (0 <= index < len(st["zones"])):
        return _err(400, f"Invalid zone index {index!r}.")
    st["zones"].pop(index)
    return jsonify({"zones": st["zones"]})


@app.route("/process", methods=["POST"])
def process():
    """Placeholder for the Process Video action.

    Intentionally does NOT call core.video_pipeline.process_video() — wiring the
    pipeline is the next Phase 3 task. This returns a controlled 501 with the
    exact state (video reference, mode, zones) the next task will feed in, and
    also guards the "process only after a valid video is loaded" rule at the API
    level: an unknown/absent id is rejected.
    """
    data = request.get_json(silent=True) or {}
    st = _STATE.get(data.get("id"))
    if not st:
        return _err(400, "No video loaded — upload a valid video first.")
    return jsonify({
        "status": "not_implemented",
        "message": "Video loaded and ready; pipeline wiring is the next task.",
        "id": data["id"],
        "video_path": st["video_path"],
        "mode": st["mode"],
        "zones": st["zones"],
        "num_zones": len(st["zones"]),
    }), 501


@app.route("/state/<uid>")
def get_state(uid):
    st = _STATE.get(uid)
    if not st:
        return _err(404, "Unknown upload id.")
    return jsonify(_public_state(uid, st))


@app.errorhandler(413)
def too_large(_exc):
    return _err(413, "File is too large.")


if __name__ == "__main__":
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    app.run(debug=True)
