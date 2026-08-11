"""
Background processing-job runner for the test harness.

A single "process this uploaded video" job, run off the Flask request thread so
the UI stays responsive and can poll live progress. This is the simplest
mechanism appropriate for a local, single-user QA harness (docs/DECISIONS.md
D10): one daemon `threading.Thread` per job and an in-memory state object — no
queue, database, Celery, or Redis (explicitly out of scope).

The job calls core.video_pipeline.process_video() **only** through its existing
public API, passing the pipeline's own `progress_callback` so the per-frame
`{frame, total, faces, pii}` events drive the progress bar, the per-stage panel,
and the technical log. This module deliberately observes only what that callback
and the returned summary actually expose — it does not fabricate per-stage
internals the pipeline cannot report (see ProcessingJob.stages).

Most jobs run process_video() exactly once. A fake_data *comparison* job (the
harness feature that lets the developer eyeball TELEA vs Navier-Stokes inpainting
on the same input) instead runs it twice, sequentially — once with
`inpaint_method="telea"` and once with `"ns"` — writing a separate output per
method. This is driven purely by the `compare_methods` the harness passes in; the
core pipeline is untouched. The two passes are presented to the UI as ONE job:
overall progress spans both (TELEA fills the first half, NS the second), the job
only reaches COMPLETE after BOTH succeed, and if either pass fails the whole job
enters the controlled error state naming the method that failed (never a false
success). Detection is identical across passes (same faces/OCR/PII/zones — only
the inpaint fill differs), so the logical summary is reported once; an unexpected
per-method count difference is flagged, not hidden.

Thread-safety: ProcessingJob guards its mutable snapshot with a lock because the
worker thread writes it while Flask request threads read it for polling.
"""

import threading
import time
import traceback

import cv2

from core import video_pipeline

# Job lifecycle states (also used by the per-stage panel rows).
PENDING = "pending"
RUNNING = "running"
COMPLETE = "complete"
ERROR = "error"

# Cap on retained log lines so a long video can't grow the snapshot unbounded;
# the UI only ever shows a tail anyway.
_MAX_LOG_LINES = 500

# --- diagnostic preview tuning ------------------------------------------------
# The preview is a throttled, downscaled JPEG of the frame the pipeline just
# processed, with detection boxes overlaid. Only the LATEST image is retained
# (never a growing buffer of frames), and it is served through a dedicated
# endpoint — never base64'd into the ~500 ms /job poll (see server.py, D21).
_PREVIEW_MAX_W = 480               # downscale wide frames to this width
_PREVIEW_JPEG_QUALITY = 70         # cv2 JPEG quality for the diagnostic image
_PREVIEW_EVERY = 6                 # regenerate at most every Nth processed frame

# Overlay colors (BGR) + label per detection kind. PII shares one color; its
# label carries the specific type (EMAIL / PHONE / CARD / IP).
_FACE_COLOR = (0, 200, 0)          # green
_PII_COLOR = (0, 0, 220)           # red
_ZONE_COLOR = (255, 150, 0)        # blue/orange


def _clock():
    """Monotonic seconds. Wrapped so tests can trace elapsed-time behavior."""
    return time.monotonic()


def _draw_box(img, bbox, scale, color, label):
    """Draw one scaled, labeled diagnostic rectangle onto `img` (in place).

    `bbox` is (x, y, w, h) in original video pixels; `scale` maps it into the
    downscaled preview image. Purely a preview overlay — never applied to the
    output video (that frame was already written before this runs)."""
    try:
        x, y, w, h = (int(round(v * scale)) for v in bbox)
    except (TypeError, ValueError):
        return
    if w <= 0 or h <= 0:
        return
    cv2.rectangle(img, (x, y), (x + w, y + h), color, 2)
    # Label just above the box, or just inside the top if there's no room.
    ty = y - 5 if y - 5 > 8 else y + 14
    cv2.putText(img, label, (x, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1,
                cv2.LINE_AA)


def render_preview_jpeg(event, max_w=_PREVIEW_MAX_W):
    """Build the diagnostic preview JPEG for one pipeline preview event.

    Copies the frame (so the caller's/pipeline's frame is never mutated),
    downscales it, overlays the face / PII / zone detection boxes carried in the
    event, and returns JPEG bytes. Returns None if there is no usable frame.

    The event is exactly what core.video_pipeline's preview_callback emits:
    ``{"frame", "faces", "pii", "zones", ...}``.
    """
    frame = event.get("frame")
    if frame is None or getattr(frame, "size", 0) == 0:
        return None
    # Copy before any drawing — the diagnostic overlay must never touch the
    # array the pipeline (or output writer) is using.
    img = frame.copy()
    h, w = img.shape[:2]
    scale = 1.0
    if w > max_w:
        scale = max_w / float(w)
        img = cv2.resize(img, (max(1, int(w * scale)), max(1, int(h * scale))))

    for bbox in event.get("faces") or []:
        _draw_box(img, bbox, scale, _FACE_COLOR, "FACE")
    for pii_type, bbox in event.get("pii") or []:
        _draw_box(img, bbox, scale, _PII_COLOR, str(pii_type))
    for bbox in event.get("zones") or []:
        _draw_box(img, bbox, scale, _ZONE_COLOR, "ZONE")

    ok, buf = cv2.imencode(".jpg", img,
                           [int(cv2.IMWRITE_JPEG_QUALITY), _PREVIEW_JPEG_QUALITY])
    if not ok:
        return None
    return buf.tobytes()


class ProcessingJob:
    """One background video-processing job and its live, pollable state.

    The pipeline exposes progress via a per-frame callback carrying
    ``{frame, total, faces, pii}`` and a final summary dict. Everything this job
    reports to the UI is derived from those two real sources — nothing is
    invented. In particular the per-stage panel reflects only observable signals:
    overall frame progress, cumulative faces blurred, and cumulative PII
    redactions; stages whose internals the callback does not expose are shown as
    active/idle rather than given fabricated counts.

    A job runs one or more sequential *passes*. Normally there is a single pass
    (blur, or a plain fake_data run) writing `output_path`. When the harness
    supplies `compare_methods` (fake_data TELEA-vs-NS comparison) there is one
    pass per method, each with its own `inpaint_method` and output file; overall
    progress spans all passes and COMPLETE is reached only after every pass
    succeeds.
    """

    def __init__(self, uid, input_path, output_path, mode, zones,
                 ocr_sample_rate=1, face_min_confidence=None, runner=None,
                 preview_every=_PREVIEW_EVERY, compare_methods=None,
                 face_redaction_method="blur", face_blur_intensity="medium"):
        self.uid = uid
        self.input_path = input_path
        self.output_path = output_path
        self.mode = mode
        self.zones = list(zones or [])
        self.ocr_sample_rate = ocr_sample_rate
        self.face_min_confidence = face_min_confidence
        self.face_redaction_method = face_redaction_method
        self.face_blur_intensity = face_blur_intensity
        # Injectable for tests: defaults to the real pipeline entry point, so
        # web tests can substitute a fake and never run OCR.
        self._runner = runner or video_pipeline.process_video
        # Regenerate the diagnostic preview at most every Nth processed frame
        # (throttle). Injectable so tests can force/relax the cadence.
        self._preview_every = max(1, int(preview_every))

        # Build the sequential pass list. `compare_methods` is a list of
        # (label, inpaint_method, output_path) supplied by the harness for the
        # fake_data TELEA/NS comparison; without it the job runs a single pass
        # writing `output_path` with no explicit inpaint_method (so the pipeline
        # keeps its own default — blur ignores it; a plain fake_data run uses
        # TELEA). inpaint_method is passed to process_video() ONLY when set, so
        # the blur/back-compat call is byte-identical to before.
        if compare_methods:
            self._passes = [
                {"label": label, "inpaint_method": method, "output_path": path}
                for (label, method, path) in compare_methods
            ]
        else:
            self._passes = [
                {"label": "redacted", "inpaint_method": None,
                 "output_path": output_path},
            ]
        self._num_passes = len(self._passes)
        self._pass_index = 0                       # which pass is running (0-based)
        self._current_pass_label = self._passes[0]["label"]

        self._lock = threading.Lock()
        self._thread = None
        self._started_at = None

        self.status = PENDING
        self.frame = 0
        self.total = 0
        self.faces = 0            # cumulative faces blurred (current pass)
        self.pii = 0             # cumulative PII regions redacted (current pass)
        self.elapsed = 0.0
        self.summary = None       # canonical (first pass) summary, on success
        self.summaries = {}       # label -> summary for each completed pass
        self.output_paths = {p["label"]: p["output_path"] for p in self._passes}
        self.summary_discrepancy = None  # set if passes disagree on detection
        self.failed_method = None  # label of the pass that errored, if any
        self.error = None         # controlled error message, on failure
        self.log = []             # list of technical log line strings
        self._last_log_time = 0.0  # timestamp of the last logged frame progress entry
        self.diagnostics = None   # hardware/backend diagnostics populated on start

        # Latest diagnostic preview only — never a growing buffer of frames.
        self._preview_jpeg = None      # bytes of the most recent preview image
        self._preview_seq = 0          # increments each time the image updates
        self._preview_frame_seen = 0   # processed-frame counter for throttling

    # -- lifecycle ------------------------------------------------------------
    def start(self):
        """Spawn the worker thread. Call once; use is_active() to guard restarts."""
        from core import device_manager
        from core import face_detector
        
        # Pre-initialize the compute device so diagnostics are accurate before the
        # worker thread starts. (process_video will re-call this with 'auto').
        face_detector.set_compute_device("auto")
        
        # Capture hardware state before starting
        dev_info = device_manager.get_device_info()
        self.diagnostics = {
            "compute_device": dev_info.get("device"),
            "gpu_name": dev_info.get("gpu_name"),
            "face_detector": {
                "model": face_detector.get_active_model_name(),
                "provider": face_detector.get_active_provider(),
            },
            "ocr": {
                "provider": dev_info.get("ocr_provider", "CPUExecutionProvider")
            },
            "tracker": {"device": dev_info.get("tracker", "CPU")},
            "redactor": {"device": dev_info.get("redactor", "CPU")},
            "encoder": {"device": dev_info.get("encoder", "CPU")},
            "fallback_reason": dev_info.get("fallback_reason")
        }

        self._started_at = _clock()
        self.status = RUNNING
        self._append_log("job started — mode=%s, zones=%d" % (self.mode, len(self.zones)))
        self._thread = threading.Thread(target=self._run, name="pv-job-%s" % self.uid,
                                        daemon=True)
        self._thread.start()

    def is_active(self):
        """True while the job is pending or running (used for duplicate-start guard)."""
        return self.status in (PENDING, RUNNING)

    def join(self, timeout=None):
        """Wait for the worker thread (used by tests; UI never blocks on this)."""
        if self._thread is not None:
            self._thread.join(timeout)

    # -- worker ---------------------------------------------------------------
    def _run(self):
        try:
            for idx, p in enumerate(self._passes):
                self._run_pass(idx, p)
            # Every pass succeeded. Detection counts must agree across methods
            # (same input, same detection — only the inpaint fill differs); flag
            # a difference rather than silently reporting one method's numbers.
            self._check_summary_discrepancy()
            with self._lock:
                # Sum frames_processed across all actual passes, but keep detection
                # counts (faces, PII, zones) from the first pass so they represent
                # the unique detections in the input video without doubling.
                total_frames = sum(s.get("frames_processed", 0) for s in self.summaries.values())
                first_summary = next(iter(self.summaries.values()))

                self.summary = {
                    "frames_processed": total_frames,
                    "faces_blurred": first_summary.get("faces_blurred", 0),
                    "pii_by_type": first_summary.get("pii_by_type", {}),
                    "zones_applied": first_summary.get("zones_applied", 0),
                }

                self.status = COMPLETE
                self.elapsed = _clock() - self._started_at
            if self._num_passes > 1:
                self._append_log("complete — %d outputs ready (%s)"
                                 % (self._num_passes,
                                    ", ".join(p["label"] for p in self._passes)))
            else:
                s = self.summary or {}
                self._append_log(
                    "complete — %d frames, %d faces, output ready"
                    % (s.get("frames_processed", 0), s.get("faces_blurred", 0)))
        except Exception as exc:  # controlled failure surface for the UI
            with self._lock:
                self.status = ERROR
                self.error = "%s: %s" % (type(exc).__name__, exc)
                self.elapsed = _clock() - self._started_at
            # Keep the traceback in the log for debugging, but expose only the
            # short message via `error`.
            self._append_log("ERROR — " + self.error)
            for line in traceback.format_exc().rstrip().splitlines():
                self._append_log("  " + line)

    def _run_pass(self, idx, p):
        """Run one pipeline pass (process_video call) and record its summary.

        Progress counters are reset per pass so each pass reports its own
        frames/faces/pii — the same input processed twice must not double-count.
        A failure is re-raised (single pass: unchanged message; comparison:
        wrapped to name the method) so `_run` records the controlled error.
        """
        with self._lock:
            self._pass_index = idx
            self._current_pass_label = p["label"]
            self.frame = 0
            self.total = 0
            self.faces = 0
            self.pii = 0
            self._last_log_time = 0.0
        method = p["inpaint_method"]
        if self._num_passes > 1:
            self._append_log(
                "pass %d/%d — %s (inpaint_method=%s)"
                % (idx + 1, self._num_passes, p["label"], method))

        kwargs = dict(
            mode=self.mode,
            zones=self.zones,
            ocr_sample_rate=self.ocr_sample_rate,
            face_min_confidence=self.face_min_confidence,
            progress_callback=self._on_progress,
            preview_callback=self._on_preview,
            face_redaction_method=self.face_redaction_method,
            face_blur_intensity=self.face_blur_intensity,
        )
        # Only forward inpaint_method when this pass specifies one, so the
        # blur/back-compat call to process_video() is unchanged.
        if method is not None:
            kwargs["inpaint_method"] = method

        try:
            summary = self._runner(self.input_path, p["output_path"], **kwargs)
        except Exception as exc:
            self.failed_method = p["label"]
            if self._num_passes > 1:
                raise RuntimeError(
                    "%s pass failed — %s: %s"
                    % (p["label"].upper(), type(exc).__name__, exc)) from exc
            raise

        with self._lock:
            self.summaries[p["label"]] = summary
            if self.summary is None:
                self.summary = summary
        if self._num_passes > 1:
            self._append_log(
                "pass %d/%d complete — %s: %d frames, %d faces"
                % (idx + 1, self._num_passes, p["label"],
                   summary.get("frames_processed", 0),
                   summary.get("faces_blurred", 0)))

    def _check_summary_discrepancy(self):
        """Flag (never hide) a per-method disagreement on detection counts.

        Inpainting changes pixels, not detections, so both passes should report
        identical frames/faces/PII/zones. If they don't, record a human-readable
        note (surfaced on Results + in the log) instead of silently trusting one.
        """
        if len(self.summaries) < 2:
            return

        def _detection_view(s):
            return (
                s.get("frames_processed"),
                s.get("faces_blurred"),
                tuple(sorted((s.get("pii_by_type") or {}).items())),
                s.get("zones_applied"),
            )

        views = {label: _detection_view(s) for label, s in self.summaries.items()}
        if len(set(views.values())) > 1:
            self.summary_discrepancy = (
                "Detection counts differ between methods — "
                + "; ".join(
                    "%s: frames=%s faces=%s pii=%s zones=%s"
                    % (label, v[0], v[1], dict(v[2]), v[3])
                    for label, v in views.items()))
            self._append_log("WARNING — " + self.summary_discrepancy)

    def _on_progress(self, event):
        """Pipeline progress_callback: one call per processed frame."""
        now = _clock()
        with self._lock:
            self.frame = event.get("frame", self.frame)
            self.total = event.get("total", self.total)
            self.faces += event.get("faces", 0)
            self.pii += event.get("pii", 0)
            self.elapsed = now - self._started_at
            should_log = False
            frame = event.get("frame", 0)
            total = event.get("total", 0)
            if frame == 1 or (total and frame == total) or (now - self._last_log_time >= 1.0):
                self._last_log_time = now
                should_log = True

        if should_log:
            # Prefix the method on a comparison job so the log makes the two
            # sequential passes legible ("telea frame 30/60", "ns frame 30/60").
            prefix = ("%s " % self._current_pass_label) if self._num_passes > 1 else ""
            self._append_log(
                "%sframe %d/%s | faces this frame: %d | pii regions: %d"
                % (prefix, frame, total or "?", event.get("faces", 0),
                   event.get("pii", 0))
            )

    def _on_preview(self, event):
        """Pipeline preview_callback: build+store the latest diagnostic image.

        Throttled to every Nth processed frame so a long video doesn't spend all
        its time JPEG-encoding. Only the most recent JPEG is kept (the previous
        one is replaced, never accumulated). The frame is copied inside
        render_preview_jpeg before any drawing, so the output video is untouched.
        """
        self._preview_frame_seen += 1
        n = self._preview_frame_seen
        total = event.get("total") or 0
        # Update on the first frame, every Nth frame, and the final frame so the
        # preview lands promptly and ends on the last processed frame.
        if not (n == 1 or n % self._preview_every == 0 or (total and n == total)):
            return
        jpeg = render_preview_jpeg(event)
        if jpeg is None:
            return
        with self._lock:
            self._preview_jpeg = jpeg
            self._preview_seq += 1

    def preview_jpeg(self):
        """Return (jpeg_bytes, seq) for the latest preview, or (None, seq)."""
        with self._lock:
            return self._preview_jpeg, self._preview_seq

    def _append_log(self, message):
        with self._lock:
            ts = time.strftime("%H:%M:%S")
            self.log.append("[%s] %s" % (ts, message))
            if len(self.log) > _MAX_LOG_LINES:
                del self.log[: len(self.log) - _MAX_LOG_LINES]

    # -- pollable snapshot ----------------------------------------------------
    def stages(self):
        """Per-stage panel rows, derived only from observable signals.

        The pipeline reports overall frame progress and cumulative face/PII
        counts, not a separate live count for every internal stage. So each row's
        state is honestly derived: face/PII/zone/redactor/writer stages are
        `running` while the job runs and `complete`/`error` at the end; only the
        counts the callback actually exposes (faces, PII) are shown — others show
        an activity marker, not a fabricated number.
        """
        running = self.status == RUNNING
        if self.status == COMPLETE:
            end = COMPLETE
        elif self.status == ERROR:
            end = ERROR
        elif running:
            end = RUNNING
        else:
            end = PENDING

        zones_n = len(self.zones)
        if self._num_passes > 1:
            redactor_detail = ("mode: %s — comparing telea + ns (pass %d/%d: %s)"
                               % (self.mode, self._pass_index + 1,
                                  self._num_passes, self._current_pass_label))
        else:
            redactor_detail = "mode: %s" % self.mode
        return [
            {"name": "face_detector", "state": end, "detail": "%d faces blurred" % self.faces},
            {"name": "ocr_detector", "state": end,
             "detail": "sampling every %d frame(s)" % self.ocr_sample_rate},
            {"name": "pii_matcher", "state": end, "detail": "%d PII regions" % self.pii},
            {"name": "zone_manager", "state": end,
             "detail": "%d static zone(s)/frame" % zones_n},
            {"name": "redactor", "state": end, "detail": redactor_detail},
            {"name": "video writer / ffmpeg mux", "state": end,
             "detail": "writing output" if running else
                       ("output ready" if self.status == COMPLETE else "—")},
        ]

    def _percent_locked(self):
        """Overall progress across all passes (call holding self._lock).

        Each pass is an equal slice of the bar: completed passes contribute their
        full slice and the running pass contributes its own frame fraction. For a
        single-pass job this reduces to the old frame/total percentage; for a
        fake_data comparison TELEA fills 0–50% and NS 50–100%.
        """
        if self.status == COMPLETE:
            return 100
        frac = float(self._pass_index)
        if self.total:
            frac += self.frame / self.total
        return max(0, min(100, int(frac * 100 / self._num_passes)))

    def snapshot(self):
        """Thread-safe view for the polling endpoint."""
        with self._lock:
            return {
                "uid": self.uid,
                "status": self.status,
                "frame": self.frame,
                "total": self.total,
                "percent": self._percent_locked(),
                "faces": self.faces,
                "pii": self.pii,
                "elapsed": round(self.elapsed, 1),
                "mode": self.mode,
                "num_zones": len(self.zones),
                "error": self.error,
                "summary": self.summary,
                "output_ready": self.status == COMPLETE,
                "stages": self.stages(),
                "log": list(self.log),
                # Two-pass fake_data comparison progress (1 for a normal job).
                "num_passes": self._num_passes,
                "pass_index": self._pass_index,
                "pass_label": self._current_pass_label,
                "summaries": dict(self.summaries),
                "summary_discrepancy": self.summary_discrepancy,
                "failed_method": self.failed_method,
                "diagnostics": self.diagnostics,
                # Lightweight preview signaling only — the image itself is served
                # by a dedicated endpoint, never embedded in this poll (D21).
                "has_preview": self._preview_jpeg is not None,
                "preview_seq": self._preview_seq,
            }
