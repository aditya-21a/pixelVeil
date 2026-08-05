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

Thread-safety: ProcessingJob guards its mutable snapshot with a lock because the
worker thread writes it while Flask request threads read it for polling.
"""

import threading
import time
import traceback

from core import video_pipeline

# Job lifecycle states (also used by the per-stage panel rows).
PENDING = "pending"
RUNNING = "running"
COMPLETE = "complete"
ERROR = "error"

# Cap on retained log lines so a long video can't grow the snapshot unbounded;
# the UI only ever shows a tail anyway.
_MAX_LOG_LINES = 500


def _clock():
    """Monotonic seconds. Wrapped so tests can trace elapsed-time behavior."""
    return time.monotonic()


class ProcessingJob:
    """One background video-processing job and its live, pollable state.

    The pipeline exposes progress via a per-frame callback carrying
    ``{frame, total, faces, pii}`` and a final summary dict. Everything this job
    reports to the UI is derived from those two real sources — nothing is
    invented. In particular the per-stage panel reflects only observable signals:
    overall frame progress, cumulative faces blurred, and cumulative PII
    redactions; stages whose internals the callback does not expose are shown as
    active/idle rather than given fabricated counts.
    """

    def __init__(self, uid, input_path, output_path, mode, zones,
                 ocr_sample_rate=1, runner=None):
        self.uid = uid
        self.input_path = input_path
        self.output_path = output_path
        self.mode = mode
        self.zones = list(zones or [])
        self.ocr_sample_rate = ocr_sample_rate
        # Injectable for tests: defaults to the real pipeline entry point, so
        # web tests can substitute a fake and never run OCR.
        self._runner = runner or video_pipeline.process_video

        self._lock = threading.Lock()
        self._thread = None
        self._started_at = None

        self.status = PENDING
        self.frame = 0
        self.total = 0
        self.faces = 0            # cumulative faces blurred
        self.pii = 0             # cumulative PII regions redacted
        self.elapsed = 0.0
        self.summary = None       # process_video()'s return value, on success
        self.error = None         # controlled error message, on failure
        self.log = []             # list of technical log line strings

    # -- lifecycle ------------------------------------------------------------
    def start(self):
        """Spawn the worker thread. Call once; use is_active() to guard restarts."""
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
            summary = self._runner(
                self.input_path,
                self.output_path,
                mode=self.mode,
                zones=self.zones,
                ocr_sample_rate=self.ocr_sample_rate,
                progress_callback=self._on_progress,
            )
            with self._lock:
                self.summary = summary
                self.status = COMPLETE
                self.elapsed = _clock() - self._started_at
            self._append_log(
                "complete — %d frames, %d faces, output ready"
                % (summary.get("frames_processed", 0), summary.get("faces_blurred", 0))
            )
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

    def _on_progress(self, event):
        """Pipeline progress_callback: one call per processed frame."""
        with self._lock:
            self.frame = event.get("frame", self.frame)
            self.total = event.get("total", self.total)
            self.faces += event.get("faces", 0)
            self.pii += event.get("pii", 0)
            self.elapsed = _clock() - self._started_at
        # Log at a readable cadence, not every single frame, plus the first frame.
        frame = event.get("frame", 0)
        total = event.get("total", 0)
        if frame == 1 or frame % 30 == 0 or (total and frame == total):
            self._append_log(
                "frame %d/%s | faces this frame: %d | pii regions: %d"
                % (frame, total or "?", event.get("faces", 0), event.get("pii", 0))
            )

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
        return [
            {"name": "face_detector", "state": end, "detail": "%d faces blurred" % self.faces},
            {"name": "ocr_detector", "state": end,
             "detail": "sampling every %d frame(s)" % self.ocr_sample_rate},
            {"name": "pii_matcher", "state": end, "detail": "%d PII regions" % self.pii},
            {"name": "zone_manager", "state": end,
             "detail": "%d static zone(s)/frame" % zones_n},
            {"name": "redactor", "state": end, "detail": "mode: %s" % self.mode},
            {"name": "video writer / ffmpeg mux", "state": end,
             "detail": "writing output" if running else
                       ("output ready" if self.status == COMPLETE else "—")},
        ]

    def snapshot(self):
        """Thread-safe view for the polling endpoint."""
        with self._lock:
            percent = 0
            if self.total:
                percent = min(100, int(self.frame * 100 / self.total))
            elif self.status == COMPLETE:
                percent = 100
            return {
                "uid": self.uid,
                "status": self.status,
                "frame": self.frame,
                "total": self.total,
                "percent": percent,
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
            }
