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

import io
import os
import threading
import uuid
import zipfile

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
from . import settings_store
from .job import ProcessingJob

app = Flask(__name__)

# Generous cap so real screen recordings upload, but bad/huge input fails fast
# with a clear 413 rather than exhausting memory.
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024  # 2 GiB

UPLOAD_DIR = os.path.join(app.root_path, "uploads")    # uploaded source videos
OUTPUT_DIR = os.path.join(app.root_path, "outputs")    # processed output videos

VALID_MODES = ("blur", "fake_data")

# fake_data is processed twice for a manual TELEA-vs-Navier-Stokes inpainting
# comparison (a temporary QA capability — no winner is chosen here). Each method
# gets its own output file so neither overwrites the other. Order is the order
# the passes run (TELEA fills the first half of the progress bar, NS the second).
COMPARE_METHODS = ("telea", "ns")
COMPARE_LABELS = {"telea": "Fake Data — TELEA", "ns": "Fake Data — Navier-Stokes"}

# upload id -> {"video_path", "frame_path", "width", "height", "mode", "zones",
#               and (once processing starts) "job", plus output paths}
# For a blur job the output lives at "output_path" (single redacted file). For a
# fake_data job the harness runs the pipeline twice to compare inpainting methods
# and stores "output_paths" = {"telea": ..., "ns": ...} instead (see /process).
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


def _method_output_path(out_dir, video_path, method):
    """Build a method-specific output path, e.g. test.mp4 -> test_telea.mp4.

    Keeps each inpainting method's output distinct within the per-upload output
    directory so a comparison job never overwrites one method's result with the
    other's. `method` is one of COMPARE_METHODS (a fixed server-side allowlist),
    never client input, so the suffix is always a safe token.
    """
    stem, ext = os.path.splitext(os.path.basename(video_path))
    return os.path.join(out_dir, "%s_%s%s" % (stem, method, ext))


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


def _current_job_uid():
    """The upload id the nav should treat as the 'current job', or "".

    A page navigation must never lose the active job (a background ProcessingJob
    keeps running regardless), so the top-nav Processing/Results links need a job
    id to carry. Prefer the job the current page is already about (its ?job=
    query param), then fall back to the most-recently started job
    (`_ACTIVE_JOB_UID`). Only return an id we still hold state for AND that has a
    job started — so the links point somewhere real. This is a read-only lookup;
    it never starts, stops, or mutates a job.
    """
    for candidate in (request.args.get("job"), _ACTIVE_JOB_UID):
        st = _STATE.get(candidate) if candidate else None
        if st and st.get("job") is not None:
            return candidate
    return ""


@app.context_processor
def inject_current_job():
    """Expose the current job id to every template (used by the nav in base.html).

    Kept context-aware rather than hardcoded in the templates/JS: with a job
    present, the Processing/Results tabs link to that job so navigating away and
    back reconnects to the SAME in-memory job instead of an idle/blank screen.
    """
    return {"active_job_uid": _current_job_uid()}


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
    """Results screen: before/after video preview, summary, and download.

    Accessed via ?job=<uid> query param (set by the Processing screen when a job
    completes). Shows the original uploaded video, the processed/redacted video,
    and the real summary returned by process_video(). Gracefully handles unknown
    job, still-running job, failed job, and missing-output states.
    """
    uid = request.args.get("job", "")
    st = _STATE.get(uid)
    job = st.get("job") if st else None

    # Guard: unknown upload id
    if not st:
        return render_template("results.html", active="results",
                               error="Unknown job — no upload found with that id.")

    # Guard: no job started yet (shouldn't happen via normal flow, but guard it)
    if job is None:
        return render_template("results.html", active="results",
                               error="No processing job found for this upload.")

    # Guard: job still running
    if job.is_active():
        return render_template("results.html", active="results",
                               error="Processing is still running — wait for it to finish.",
                               job_url=url_for("processing", job=uid))

    # Guard: job failed
    if job.status == "error":
        return render_template("results.html", active="results",
                               error=f"Processing failed: {job.error or 'unknown error'}",
                               job_url=url_for("processing", job=uid))

    # From here the job completed successfully. blur and fake_data differ in how
    # many outputs exist and how they're presented, so branch on mode.
    if st.get("mode") == "fake_data":
        return _results_fake_data(uid, st, job)
    return _results_blur(uid, st, job)


def _results_blur(uid, st, job):
    """Render Results for a completed single-output (blur) job."""
    # Guard: job completed but output file missing (unlikely — ProcessingJob
    # writes it before marking complete, but filesystem issues could delete it)
    if not os.path.exists(st.get("output_path", "")):
        return render_template("results.html", active="results",
                               error="Output video file is missing (deleted or moved).")

    summary = job.summary or {}
    return render_template("results.html", active="results",
                           mode="blur",
                           uid=uid,
                           original_filename=os.path.basename(st["video_path"]),
                           output_filename=os.path.basename(st["output_path"]),
                           summary=summary)


def _results_fake_data(uid, st, job):
    """Render Results for a completed fake_data TELEA-vs-NS comparison job.

    Shows three players (Original + one per inpainting method) and downloads for
    each method (plus a combined ZIP). The detection summary is shown ONCE — the
    same input was processed twice with identical detection, so counting it twice
    would be misleading; any unexpected per-method count difference is surfaced
    via `summary_discrepancy` rather than hidden.
    """
    output_paths = st.get("output_paths") or {}
    # Guard: a completed comparison must have both method outputs on disk.
    missing = [m for m in COMPARE_METHODS
               if not os.path.exists(output_paths.get(m, ""))]
    if missing:
        return render_template(
            "results.html", active="results",
            error="Output video file is missing for: %s (deleted or moved)."
                  % ", ".join(missing))

    return render_template(
        "results.html", active="results",
        mode="fake_data",
        uid=uid,
        original_filename=os.path.basename(st["video_path"]),
        telea_filename=os.path.basename(output_paths["telea"]),
        ns_filename=os.path.basename(output_paths["ns"]),
        summary=job.summary or {},
        summary_discrepancy=job.summary_discrepancy)


@app.route("/settings")
def settings():
    """Settings screen: current tuning values with editable controls.

    Values come from the process-local settings_store (OCR sample rate, face
    confidence, PII regex patterns) so the page always reflects what a newly
    started job would use. Saving/resetting is done via the JSON API below.
    """
    return render_template("settings.html", active="settings",
                           settings=settings_store.get_settings())


@app.route("/settings/values")
def settings_values():
    """Current settings as JSON (used by the Settings screen after save/reset)."""
    return jsonify(settings_store.get_settings())


@app.route("/settings", methods=["POST"])
def save_settings():
    """Validate and apply a settings update; echo back the new settings.

    Body: {ocr_sample_rate, face_min_confidence, pii_patterns:{EMAIL,PHONE,
    CARD,IP}}. Any field may be omitted. Validation is all-or-nothing — an
    invalid OCR rate, out-of-range confidence, or uncompilable regex is rejected
    with 400 and the previous valid configuration is left untouched (in
    particular, a bad regex never replaces the working patterns).
    """
    data = request.get_json(silent=True) or {}
    try:
        new_settings = settings_store.update_settings(
            ocr_sample_rate=data.get("ocr_sample_rate"),
            face_min_confidence=data.get("face_min_confidence"),
            pii_patterns=data.get("pii_patterns"),
        )
    except ValueError as exc:
        return _err(400, str(exc))
    return jsonify(new_settings)


@app.route("/settings/reset", methods=["POST"])
def reset_settings():
    """Restore all settings (OCR rate, face confidence, PII patterns) to defaults."""
    return jsonify(settings_store.reset_settings())


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

        # Zones are stored as [x, y, w, h] lists; pass them as tuples — exactly
        # the (x, y, w, h) form ZoneManager.add_zone() (inside process_video)
        # expects. process_video is reached only through its public API.
        # Current Settings-screen values (OCR sample rate, face confidence) are
        # read at start time so a job always uses the latest saved tuning; the
        # PII patterns are applied globally in core.pii_matcher by the store.
        proc_kwargs = settings_store.processing_kwargs()
        job_kwargs = dict(
            ocr_sample_rate=proc_kwargs["ocr_sample_rate"],
            face_min_confidence=proc_kwargs["face_min_confidence"],
        )

        if st["mode"] == "fake_data":
            # Compare TELEA vs Navier-Stokes on the SAME input: two sequential
            # pipeline passes, one output file each (never overwriting the
            # other). Blur is unaffected and still runs once. This is a manual
            # comparison aid — the pipeline/redaction logic is untouched; only
            # the inpaint_method differs between passes (see job.ProcessingJob).
            output_paths = {
                m: _method_output_path(out_dir, st["video_path"], m)
                for m in COMPARE_METHODS
            }
            compare_methods = [
                (m, m, output_paths[m]) for m in COMPARE_METHODS
            ]
            job = ProcessingJob(
                uid,
                st["video_path"],
                None,                       # no single output; see compare_methods
                st["mode"],
                [tuple(z) for z in st["zones"]],
                compare_methods=compare_methods,
                **job_kwargs,
            )
            st["output_paths"] = output_paths
            st.pop("output_path", None)     # not a single-output job
        else:
            output_path = os.path.join(
                out_dir, "redacted_" + os.path.basename(st["video_path"]))
            job = ProcessingJob(
                uid,
                st["video_path"],
                output_path,
                st["mode"],
                [tuple(z) for z in st["zones"]],
                **job_kwargs,
            )
            st["output_path"] = output_path
            st.pop("output_paths", None)    # not a comparison job

        st["job"] = job
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


@app.route("/job/<uid>/preview")
def job_preview(uid):
    """Serve the latest diagnostic preview JPEG for a job.

    Kept out of the ~500 ms /job poll on purpose (D21): the browser refreshes
    this image endpoint separately, so a full frame is never base64'd into every
    status poll. Returns 404 before the first frame has been processed (the UI
    degrades to its placeholder until then).
    """
    st = _STATE.get(uid)
    job = st.get("job") if st else None
    if job is None:
        return _err(404, "No processing job for this upload.")
    jpeg, _seq = job.preview_jpeg()
    if jpeg is None:
        return _err(404, "No preview available yet.")
    resp = send_file(io.BytesIO(jpeg), mimetype="image/jpeg")
    # Diagnostic frames change constantly; never let a proxy/browser cache them.
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/video/<uid>/original")
def video_original(uid):
    """Serve the original uploaded video for before/after playback.

    The path comes from server-controlled _STATE (set at upload from a decoded
    file), never from a client-supplied path — a caller cannot request an
    arbitrary filesystem location, only the video tied to a known upload id.
    """
    st = _STATE.get(uid)
    if not st:
        return _err(404, "Unknown upload id.")
    path = st.get("video_path")
    if not path or not os.path.exists(path):
        return _err(404, "Original video file is missing.")
    return send_file(path, mimetype="video/mp4", conditional=True)


@app.route("/video/<uid>/processed")
def video_processed(uid):
    """Serve the processed/redacted output video for before/after playback.

    Requires a completed job with an existing output file. The path is taken
    from server-controlled _STATE, not from the client.
    """
    st = _STATE.get(uid)
    job = st.get("job") if st else None
    if job is None:
        return _err(404, "No processing job for this upload.")
    if job.status != "complete":
        return _err(409, "Processed video is not ready yet.")
    path = st.get("output_path")
    if not path or not os.path.exists(path):
        return _err(404, "Processed video file is missing.")
    return send_file(path, mimetype="video/mp4", conditional=True)


@app.route("/download/<uid>")
def download_output(uid):
    """Download the final processed video, preserving its actual filename.

    Serves the existing completed output file from server-controlled _STATE
    (never a client path) as an attachment with the real output filename.
    """
    st = _STATE.get(uid)
    job = st.get("job") if st else None
    if job is None:
        return _err(404, "No processing job for this upload.")
    if job.status != "complete":
        return _err(409, "Output is not ready to download yet.")
    path = st.get("output_path")
    if not path or not os.path.exists(path):
        return _err(404, "Output video file is missing.")
    return send_file(path, mimetype="video/mp4", as_attachment=True,
                     download_name=os.path.basename(path))


def _serve_fake_output(uid, method, as_attachment):
    """Serve one method's fake_data output (TELEA or NS) from server state.

    Shared by the per-method video and download routes. Enforces the same
    controlled-access rules as the blur routes: the path comes only from
    server-owned `output_paths` (never client input), the job must be a completed
    fake_data comparison, `method` must be a known method, and the file must
    exist. Returns a Flask response, or an (_err) tuple on any failure.
    """
    st = _STATE.get(uid)
    job = st.get("job") if st else None
    if job is None:
        return _err(404, "No processing job for this upload.")
    if method not in COMPARE_METHODS:
        return _err(404, "Unknown comparison method.")
    if job.status != "complete":
        return _err(409, "Processed video is not ready yet.")
    # output_paths is only set for fake_data comparison jobs — a blur job (single
    # output_path) has no per-method files, so these routes 404 for it.
    output_paths = st.get("output_paths") or {}
    path = output_paths.get(method)
    if not path or not os.path.exists(path):
        return _err(404, "Processed video file is missing for method %r." % method)
    return send_file(path, mimetype="video/mp4", conditional=True,
                     as_attachment=as_attachment,
                     download_name=os.path.basename(path))


@app.route("/video/<uid>/telea")
def video_telea(uid):
    """Serve the TELEA-inpainted fake_data output for before/after playback."""
    return _serve_fake_output(uid, "telea", as_attachment=False)


@app.route("/video/<uid>/ns")
def video_ns(uid):
    """Serve the Navier-Stokes-inpainted fake_data output for playback."""
    return _serve_fake_output(uid, "ns", as_attachment=False)


@app.route("/download/<uid>/telea")
def download_telea(uid):
    """Download the TELEA fake_data output, preserving its _telea filename."""
    return _serve_fake_output(uid, "telea", as_attachment=True)


@app.route("/download/<uid>/ns")
def download_ns(uid):
    """Download the Navier-Stokes fake_data output, preserving its _ns filename."""
    return _serve_fake_output(uid, "ns", as_attachment=True)


@app.route("/download/<uid>/both")
def download_both(uid):
    """Download both fake_data outputs as a single ZIP (stdlib zipfile).

    Contains exactly the two processed MP4s under their method-specific
    filenames — nothing else. Built in-memory (no temp file, no new dependency).
    Same controlled-access rules as the per-method routes: paths come only from
    server-owned `output_paths`, the job must be a completed fake_data
    comparison, and both files must exist.
    """
    st = _STATE.get(uid)
    job = st.get("job") if st else None
    if job is None:
        return _err(404, "No processing job for this upload.")
    if job.status != "complete":
        return _err(409, "Output is not ready to download yet.")
    output_paths = st.get("output_paths") or {}
    paths = [output_paths.get(m) for m in COMPARE_METHODS]
    if any(not p or not os.path.exists(p) for p in paths):
        return _err(404, "One or both output video files are missing.")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in paths:
            # arcname = basename only, so the ZIP holds two clearly-named files
            # (…_telea.mp4 / …_ns.mp4) and leaks no server directory structure.
            zf.write(path, arcname=os.path.basename(path))
    buf.seek(0)
    stem, _ext = os.path.splitext(os.path.basename(st["video_path"]))
    return send_file(buf, mimetype="application/zip", as_attachment=True,
                     download_name="%s_telea_ns.zip" % stem)


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
