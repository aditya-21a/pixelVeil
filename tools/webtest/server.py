"""
Local Flask app — the test harness UI described in docs/design.md.
Serves Upload / Processing / Results / Settings screens and (later) triggers
core/video_pipeline.py, streaming progress back to the browser.

This is a development/QA tool only, not the shipped product (see
docs/DECISIONS.md D10).

Upload screen state (video reference, mode, drawn zones) is held in a simple
in-memory store keyed by an upload id. It is intentionally process-local and
non-persistent — this is a single-user local harness. Zones are stored as
(x, y, w, h) tuples in ORIGINAL video-pixel coordinates, exactly the format
core.zone_manager.ZoneManager.add_zone() expects.

Processing (Screen 2) runs the real core.video_pipeline.process_video() in a
background daemon thread (see job.py) so the request never blocks; the browser
polls /job/<uid> for live progress, per-stage status, and the technical log.
Only one job runs at a time (single-user local harness — no queue/DB/Celery,
per DECISIONS.md D10/D20). The uploaded source (uploads/) and the processed
output (outputs/) are kept in separate directories.
"""

import os
import threading
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
from .job import ProcessingJob

app = Flask(__name__)

# Generous cap so real screen recordings upload, but bad/huge input fails fast
# with a clear 413 rather than exhausting memory.
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024  # 2 GiB

UPLOAD_DIR = os.path.join(app.root_path, "uploads")    # uploaded source videos
OUTPUT_DIR = os.path.join(app.root_path, "outputs")    # processed output videos

VALID_MODES = ("blur", "fake_data")

# upload id -> {"video_path", "frame_path", "width", "height", "mode", "zones",
#               and (once processing starts) "job", "output_path"}
# Process-local; see module docstring. Not thread-safe by design for the upload
# fields (local, single user, Flask dev server); the background job manages its
# own locking for the fields the worker thread mutates.
_STATE = {}

# Guards the single-job invariant across concurrent /process requests.
_JOB_LOCK = threading.Lock()
_ACTIVE_JOB_UID = None


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
    # `job` query param (set by the Upload screen's redirect) tells the page
    # which job to poll; a direct visit with no param shows the idle state.
    return render_template("processing.html", active="processing",
                           job_id=request.args.get("job", ""))


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
    """Start processing the uploaded video in a background job.

    Runs core.video_pipeline.process_video() off the request thread (job.py) so
    the UI can navigate to /processing and poll live progress. Guards:
      * an unknown/absent upload id is rejected (process only after a valid
        upload) — 400;
      * only one job runs at a time in this local harness, so a request made
        while another job is still active is rejected — 409 (duplicate-start
        protection).
    The uploaded source and the processed output are kept in separate dirs.
    """
    global _ACTIVE_JOB_UID
    data = request.get_json(silent=True) or {}
    uid = data.get("id")
    st = _STATE.get(uid)
    if not st:
        return _err(400, "No video loaded — upload a valid video first.")

    with _JOB_LOCK:
        active = _STATE.get(_ACTIVE_JOB_UID, {}).get("job") if _ACTIVE_JOB_UID else None
        if active is not None and active.is_active():
            return _err(409, "A processing job is already running; wait for it to finish.")

        out_dir = os.path.join(OUTPUT_DIR, uid)
        os.makedirs(out_dir, exist_ok=True)
        output_path = os.path.join(out_dir, "redacted_" + os.path.basename(st["video_path"]))

        # Zones are stored as [x, y, w, h] lists; pass them as tuples — exactly
        # the (x, y, w, h) form ZoneManager.add_zone() (inside process_video)
        # expects. process_video is reached only through its public API.
        job = ProcessingJob(
            uid,
            st["video_path"],
            output_path,
            st["mode"],
            [tuple(z) for z in st["zones"]],
        )
        st["job"] = job
        st["output_path"] = output_path
        _ACTIVE_JOB_UID = uid
        job.start()

    return jsonify({
        "id": uid,
        "status": job.status,
        "poll_url": url_for("job_status", uid=uid),
    }), 202


@app.route("/job/<uid>")
def job_status(uid):
    """Live job snapshot for polling: progress, per-stage panel, and log."""
    st = _STATE.get(uid)
    job = st.get("job") if st else None
    if job is None:
        return _err(404, "No processing job for this upload.")
    return jsonify(job.snapshot())


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
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    # threaded=True so a poll request is served while the worker thread runs.
    app.run(debug=True, threaded=True)
