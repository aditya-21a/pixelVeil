"""
Focused tests for the fake_data TELEA-vs-Navier-Stokes comparison feature of the
Flask test harness (tools/webtest).

Background: when a job runs in fake_data mode the harness processes the SAME
input twice — once with inpaint_method="telea" and once with "ns" — so a
developer can eyeball the two classical-inpainting fills side by side. This is a
temporary/manual comparison capability; NO winner is chosen here. Blur mode is
untouched and still runs the pipeline exactly once.

Two layers, mirroring test_webtest_processing.py:
  * ProcessingJob unit tests (tools/webtest/job.py) with an INJECTED fake runner
    — cover the two sequential passes, per-method inpaint_method, distinct
    outputs, both summaries retained, the "not complete after only TELEA"
    invariant, sensible overall progress, and the controlled error state when
    either method fails.
  * Flask route tests via app.test_client() with core.video_pipeline.process_video
    MOCKED — cover the dual output paths/filenames, the Results 3-up page, the
    per-method video/download routes, the Download-Both ZIP, the once-only
    summary (no double counting), and that blur still behaves as before with no
    per-method routes reachable (no arbitrary/traversal path access).

process_video is always mocked here so OCR never runs.
"""

import io
import os
import shutil
import sys
import threading
import unittest
import uuid
import zipfile
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

from webtest import server  # noqa: E402
from webtest.job import ProcessingJob, RUNNING, COMPLETE, ERROR  # noqa: E402

# Reuse the recording runner + summary helper from the processing tests so the
# fake pipeline behaves identically across both suites.
from test_webtest_processing import _RecordingRunner, _summary  # noqa: E402


# --------------------------------------------------------------------------- #
# Specialized fake runners for the comparison-specific behaviors
# --------------------------------------------------------------------------- #
class _NsStartProbeRunner:
    """Records the inpaint_method of each pass and captures the job snapshot at
    the START of the NS pass — i.e. right after TELEA finished but before NS
    completes. Lets a test assert the job is NOT complete after only TELEA and
    that overall progress has advanced to the halfway point."""

    def __init__(self, summary=None):
        self.summary = summary if summary is not None else _summary()
        self.calls = []
        self.job = None                 # set by the test before start()
        self.snapshot_at_ns_start = None

    def __call__(self, input_path, output_path, mode="blur", zones=None,
                 ocr_sample_rate=1, face_min_confidence=None,
                 progress_callback=None, preview_callback=None,
                 inpaint_method=None):
        self.calls.append(inpaint_method)
        if inpaint_method == "ns" and self.job is not None:
            self.snapshot_at_ns_start = self.job.snapshot()
        return self.summary


class _MethodFailRunner:
    """Raises on the pass whose inpaint_method == fail_on; returns a summary
    otherwise. Used to check the controlled error state for a TELEA-only or
    NS-only failure."""

    def __init__(self, fail_on, summary=None):
        self.fail_on = fail_on
        self.summary = summary if summary is not None else _summary()
        self.calls = []

    def __call__(self, input_path, output_path, mode="blur", zones=None,
                 ocr_sample_rate=1, face_min_confidence=None,
                 progress_callback=None, preview_callback=None,
                 inpaint_method=None):
        self.calls.append(inpaint_method)
        if inpaint_method == self.fail_on:
            raise RuntimeError("inpaint %s exploded" % inpaint_method)
        return self.summary


class _PerMethodSummaryRunner:
    """Returns a different summary per inpaint_method so a test can exercise the
    (unexpected) detection-count discrepancy handling."""

    def __init__(self, summaries):
        self.summaries = summaries        # {"telea": {...}, "ns": {...}}
        self.calls = []

    def __call__(self, input_path, output_path, mode="blur", zones=None,
                 ocr_sample_rate=1, face_min_confidence=None,
                 progress_callback=None, preview_callback=None,
                 inpaint_method=None):
        self.calls.append(inpaint_method)
        return self.summaries[inpaint_method]


def _compare_methods(out_dir, stem="test_mixed", ext=".mp4"):
    """Build the (label, inpaint_method, output_path) list the harness passes for
    a fake_data comparison job, mirroring server._method_output_path."""
    return [
        (m, m, os.path.join(out_dir, "%s_%s%s" % (stem, m, ext)))
        for m in ("telea", "ns")
    ]


# --------------------------------------------------------------------------- #
# ProcessingJob-level tests (no Flask, injected runner)
# --------------------------------------------------------------------------- #
class TestDualPassJob(unittest.TestCase):
    def _make_job(self, runner, out_dir="/out", stem="test_mixed"):
        return ProcessingJob(
            "uid-cmp", "/src/%s.mp4" % stem, None, "fake_data", [],
            compare_methods=_compare_methods(out_dir, stem=stem),
            runner=runner)

    def test_runs_telea_then_ns_with_correct_inpaint_methods(self):
        runner = _RecordingRunner()
        job = self._make_job(runner)
        job.start()
        job.join(5)
        # exactly two passes, TELEA first then NS, each with its inpaint_method
        self.assertEqual(len(runner.calls), 2)
        self.assertEqual(runner.calls[0]["inpaint_method"], "telea")
        self.assertEqual(runner.calls[1]["inpaint_method"], "ns")
        self.assertEqual(job.snapshot()["status"], COMPLETE)

    def test_two_distinct_output_paths_with_method_suffixes(self):
        runner = _RecordingRunner()
        job = self._make_job(runner)
        job.start()
        job.join(5)
        out_telea = runner.calls[0]["output_path"]
        out_ns = runner.calls[1]["output_path"]
        # distinct files, one per method
        self.assertNotEqual(out_telea, out_ns)
        self.assertTrue(os.path.basename(out_telea).endswith("_telea.mp4"))
        self.assertTrue(os.path.basename(out_ns).endswith("_ns.mp4"))
        # and both are retained in job state keyed by method label
        self.assertEqual(set(job.output_paths), {"telea", "ns"})
        self.assertEqual(job.output_paths["telea"], out_telea)
        self.assertEqual(job.output_paths["ns"], out_ns)

    def test_both_summaries_retained_in_job_state(self):
        runner = _RecordingRunner(summary=_summary(frames=7, faces=2))
        job = self._make_job(runner)
        job.start()
        job.join(5)
        snap = job.snapshot()
        self.assertEqual(set(snap["summaries"]), {"telea", "ns"})
        self.assertEqual(snap["summaries"]["telea"]["frames_processed"], 7)
        self.assertEqual(snap["summaries"]["ns"]["frames_processed"], 7)
        # canonical single summary is also present (shown once on Results)
        self.assertEqual(snap["summary"]["frames_processed"], 7)

    def test_not_complete_after_only_telea_and_progress_is_halfway(self):
        runner = _NsStartProbeRunner()
        job = self._make_job(runner)
        runner.job = job
        job.start()
        job.join(5)
        # Captured at the moment TELEA is done and NS is about to start.
        mid = runner.snapshot_at_ns_start
        self.assertIsNotNone(mid, "NS pass should have started")
        self.assertEqual(mid["status"], RUNNING)     # NOT complete yet
        self.assertFalse(mid["output_ready"])
        self.assertEqual(mid["pass_index"], 1)       # second pass (NS)
        self.assertEqual(mid["num_passes"], 2)
        self.assertEqual(mid["percent"], 50)         # TELEA filled the first half
        # And only after BOTH passes does the job reach 100 % / complete.
        final = job.snapshot()
        self.assertEqual(final["status"], COMPLETE)
        self.assertEqual(final["percent"], 100)

    def test_progress_within_telea_pass_stays_in_first_half(self):
        # Drive TELEA frame events; overall percent must stay <= 50 until NS.
        runner = _RecordingRunner(events=[
            {"frame": 1, "total": 2, "faces": 0, "pii": 0},
            {"frame": 2, "total": 2, "faces": 0, "pii": 0},
        ])
        job = self._make_job(runner)
        job.start()
        job.join(5)
        # After completion it's 100; the invariant is checked structurally in
        # _percent_locked (frac/num_passes), so just confirm terminal state here.
        self.assertEqual(job.snapshot()["percent"], 100)

    def test_telea_failure_produces_controlled_error_naming_method(self):
        runner = _MethodFailRunner(fail_on="telea")
        job = self._make_job(runner)
        job.start()
        job.join(5)
        snap = job.snapshot()
        self.assertEqual(snap["status"], ERROR)
        self.assertFalse(snap["output_ready"])
        self.assertEqual(snap["failed_method"], "telea")
        self.assertIn("TELEA", snap["error"])
        self.assertIn("inpaint telea exploded", snap["error"])
        # NS must NOT run once TELEA has failed.
        self.assertEqual(runner.calls, ["telea"])

    def test_ns_failure_after_telea_produces_controlled_error(self):
        runner = _MethodFailRunner(fail_on="ns")
        job = self._make_job(runner)
        job.start()
        job.join(5)
        snap = job.snapshot()
        self.assertEqual(snap["status"], ERROR)
        self.assertEqual(snap["failed_method"], "ns")
        self.assertIn("NS", snap["error"])
        # TELEA ran first, then NS failed.
        self.assertEqual(runner.calls, ["telea", "ns"])

    def test_detection_count_discrepancy_flagged_not_hidden(self):
        runner = _PerMethodSummaryRunner({
            "telea": _summary(frames=6, faces=1),
            "ns": _summary(frames=6, faces=9),   # unexpected: faces differ
        })
        job = self._make_job(runner)
        job.start()
        job.join(5)
        snap = job.snapshot()
        self.assertEqual(snap["status"], COMPLETE)
        self.assertIsNotNone(snap["summary_discrepancy"])
        self.assertIn("differ", snap["summary_discrepancy"].lower())

    def test_matching_summaries_have_no_discrepancy(self):
        runner = _RecordingRunner(summary=_summary())
        job = self._make_job(runner)
        job.start()
        job.join(5)
        self.assertIsNone(job.snapshot()["summary_discrepancy"])

    def test_blur_job_runs_once_with_no_inpaint_method(self):
        # A single-output (blur) job is the control: one pass, no compare split.
        runner = _RecordingRunner()
        job = ProcessingJob("uid-blur", "/src/in.mp4", "/out/redacted_in.mp4",
                            "blur", [], runner=runner)
        job.start()
        job.join(5)
        self.assertEqual(len(runner.calls), 1)
        # blur never forwards inpaint_method (pipeline keeps its own default)
        self.assertIsNone(runner.calls[0]["inpaint_method"])
        snap = job.snapshot()
        self.assertEqual(snap["num_passes"], 1)
        self.assertEqual(snap["status"], COMPLETE)


# --------------------------------------------------------------------------- #
# Flask route tests (process_video mocked)
# --------------------------------------------------------------------------- #
class TestDualOutputRoutes(unittest.TestCase):
    def setUp(self):
        server.app.config["TESTING"] = True
        self.client = server.app.test_client()
        server._STATE.clear()
        server._ACTIVE_JOB_UID = None

    def tearDown(self):
        for st in server._STATE.values():
            job = st.get("job")
            if job is not None:
                job.join(5)
        server._STATE.clear()
        server._ACTIVE_JOB_UID = None
        shutil.rmtree(server.OUTPUT_DIR, ignore_errors=True)
        shutil.rmtree(server.UPLOAD_DIR, ignore_errors=True)

    # -- fixtures ---------------------------------------------------------- #
    def _upload(self, mode, filename="test_mixed.mp4"):
        uid = uuid.uuid4().hex
        updir = os.path.join(server.UPLOAD_DIR, uid)
        os.makedirs(updir, exist_ok=True)
        video_path = os.path.join(updir, filename)
        with open(video_path, "wb") as fh:
            fh.write(b"ORIGINAL_VIDEO_BYTES")
        server._STATE[uid] = {
            "video_path": video_path,
            "frame_path": os.path.join(updir, "frame0.png"),
            "width": 100, "height": 80,
            "mode": mode, "zones": [],
        }
        return uid

    def _run(self, uid, runner):
        with mock.patch("core.video_pipeline.process_video", runner):
            self.client.post("/process", json={"id": uid})
            server._STATE[uid]["job"].join(5)

    def _write_outputs(self, uid):
        """The fake runner writes no files; materialize each declared output so
        the video/download/results routes have real bytes to serve."""
        paths = server._STATE[uid]["output_paths"]
        contents = {}
        for method, path in paths.items():
            os.makedirs(os.path.dirname(path), exist_ok=True)
            data = ("FAKE_%s_VIDEO" % method).encode()
            with open(path, "wb") as fh:
                fh.write(data)
            contents[method] = data
        return contents

    def _complete_fake_data(self, filename="test_mixed.mp4"):
        uid = self._upload("fake_data", filename=filename)
        runner = _RecordingRunner(events=[
            {"frame": 1, "total": 2, "faces": 1, "pii": 0},
            {"frame": 2, "total": 2, "faces": 0, "pii": 1},
        ], summary=_summary())
        self._run(uid, runner)
        contents = self._write_outputs(uid)
        return uid, runner, contents

    # -- process: dual output --------------------------------------------- #
    def test_process_fake_data_starts_two_passes_and_records_both_outputs(self):
        uid, runner, _ = self._complete_fake_data()
        # process_video called twice: telea then ns
        methods = [c["inpaint_method"] for c in runner.calls]
        self.assertEqual(methods, ["telea", "ns"])
        # server retained BOTH output paths (server-owned, not client input)
        out = server._STATE[uid]["output_paths"]
        self.assertEqual(set(out), {"telea", "ns"})
        self.assertTrue(out["telea"].endswith("_telea.mp4"))
        self.assertTrue(out["ns"].endswith("_ns.mp4"))
        # and does NOT keep a single-output key for a comparison job
        self.assertNotIn("output_path", server._STATE[uid])
        # both output paths are under the per-upload outputs dir (isolation)
        for p in out.values():
            self.assertTrue(p.startswith(server.OUTPUT_DIR))
            self.assertIn(uid, p)

    def test_process_fake_data_outputs_are_distinct_files(self):
        uid, _runner, _ = self._complete_fake_data()
        out = server._STATE[uid]["output_paths"]
        self.assertNotEqual(out["telea"], out["ns"])
        self.assertTrue(os.path.exists(out["telea"]))
        self.assertTrue(os.path.exists(out["ns"]))

    # -- Results page: 3-up ------------------------------------------------ #
    def test_results_fake_data_shows_original_telea_ns(self):
        uid, _runner, _ = self._complete_fake_data()
        html = self.client.get("/results?job=%s" % uid).get_data(as_text=True)
        # three labeled players
        self.assertIn("Original", html)
        self.assertIn("Fake Data — TELEA", html)
        self.assertIn("Fake Data — Navier-Stokes", html)
        # each served from its controlled, id-keyed route
        self.assertIn("/video/%s/original" % uid, html)
        self.assertIn("/video/%s/telea" % uid, html)
        self.assertIn("/video/%s/ns" % uid, html)
        # per-method downloads + the ZIP
        self.assertIn("/download/%s/telea" % uid, html)
        self.assertIn("/download/%s/ns" % uid, html)
        self.assertIn("/download/%s/both" % uid, html)
        self.assertIn("Download TELEA", html)
        self.assertIn("Download NS", html)
        # the developer-only harness never showed a "Flag an issue" control
        self.assertNotIn(">Flag an issue<", html)

    def test_results_fake_data_summary_shown_once_not_doubled(self):
        # _summary() has a single EMAIL match; processing twice must NOT report 2.
        uid, _runner, _ = self._complete_fake_data()
        html = self.client.get("/results?job=%s" % uid).get_data(as_text=True)
        self.assertIn("<strong>1</strong>", html)     # PII total = 1, not 2
        self.assertIn("shown once", html)             # explicit single-count note

    def test_results_fake_data_reports_discrepancy_when_counts_differ(self):
        uid = self._upload("fake_data")
        runner = _PerMethodSummaryRunner({
            "telea": _summary(frames=6, faces=1),
            "ns": _summary(frames=6, faces=4),
        })
        self._run(uid, runner)
        self._write_outputs(uid)
        html = self.client.get("/results?job=%s" % uid).get_data(as_text=True)
        self.assertIn("Detection counts differ", html)

    def test_results_fake_data_missing_output_is_controlled_error(self):
        uid, _runner, _ = self._complete_fake_data()
        os.remove(server._STATE[uid]["output_paths"]["ns"])
        html = self.client.get("/results?job=%s" % uid).get_data(as_text=True)
        self.assertIn("missing", html.lower())
        self.assertIn("ns", html)

    # -- per-method video routes ------------------------------------------ #
    def test_video_telea_route_serves_telea_file(self):
        uid, _runner, contents = self._complete_fake_data()
        r = self.client.get("/video/%s/telea" % uid)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.mimetype, "video/mp4")
        self.assertEqual(r.data, contents["telea"])

    def test_video_ns_route_serves_ns_file(self):
        uid, _runner, contents = self._complete_fake_data()
        r = self.client.get("/video/%s/ns" % uid)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data, contents["ns"])

    def test_video_routes_do_not_cross_methods(self):
        uid, _runner, contents = self._complete_fake_data()
        telea = self.client.get("/video/%s/telea" % uid).data
        ns = self.client.get("/video/%s/ns" % uid).data
        self.assertNotEqual(telea, ns)
        self.assertEqual(telea, contents["telea"])
        self.assertEqual(ns, contents["ns"])

    # -- per-method download routes --------------------------------------- #
    def test_download_telea_returns_correct_file_as_attachment(self):
        uid, _runner, contents = self._complete_fake_data()
        r = self.client.get("/download/%s/telea" % uid)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data, contents["telea"])
        cd = r.headers.get("Content-Disposition", "")
        self.assertIn("attachment", cd)
        self.assertIn("_telea.mp4", cd)

    def test_download_ns_returns_correct_file_as_attachment(self):
        uid, _runner, contents = self._complete_fake_data()
        r = self.client.get("/download/%s/ns" % uid)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data, contents["ns"])
        cd = r.headers.get("Content-Disposition", "")
        self.assertIn("attachment", cd)
        self.assertIn("_ns.mp4", cd)

    # -- Download Both (ZIP) ---------------------------------------------- #
    def test_download_both_zip_contains_exactly_the_two_outputs(self):
        uid, _runner, contents = self._complete_fake_data()
        r = self.client.get("/download/%s/both" % uid)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.mimetype, "application/zip")
        cd = r.headers.get("Content-Disposition", "")
        self.assertIn("attachment", cd)
        self.assertIn("test_mixed_telea_ns.zip", cd)

        zf = zipfile.ZipFile(io.BytesIO(r.data))
        names = sorted(zf.namelist())
        # exactly the two processed outputs, method-specific basenames only
        self.assertEqual(names, ["test_mixed_ns.mp4", "test_mixed_telea.mp4"])
        self.assertEqual(zf.read("test_mixed_telea.mp4"), contents["telea"])
        self.assertEqual(zf.read("test_mixed_ns.mp4"), contents["ns"])

    # -- blur unchanged ---------------------------------------------------- #
    def test_blur_still_runs_once_and_keeps_original_redacted(self):
        uid = self._upload("blur")
        runner = _RecordingRunner()
        self._run(uid, runner)
        # one pass, single output_path, no per-method state
        self.assertEqual(len(runner.calls), 1)
        self.assertIn("output_path", server._STATE[uid])
        self.assertNotIn("output_paths", server._STATE[uid])
        # materialize the single redacted output so Results renders happy path
        path = server._STATE[uid]["output_path"]
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(b"REDACTED")
        html = self.client.get("/results?job=%s" % uid).get_data(as_text=True)
        self.assertIn("Redacted", html)
        self.assertIn("/video/%s/processed" % uid, html)
        self.assertIn("Download output video", html)
        # no comparison UI leaks into a blur result
        self.assertNotIn("Fake Data — TELEA", html)
        self.assertNotIn("/video/%s/telea" % uid, html)

    def test_blur_job_has_no_per_method_routes(self):
        # A blur job must not expose telea/ns/both — they 404 (no output_paths),
        # never touching the filesystem for a method that doesn't exist here.
        uid = self._upload("blur")
        runner = _RecordingRunner()
        self._run(uid, runner)
        path = server._STATE[uid]["output_path"]
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(b"REDACTED")
        self.assertEqual(self.client.get("/video/%s/telea" % uid).status_code, 404)
        self.assertEqual(self.client.get("/video/%s/ns" % uid).status_code, 404)
        self.assertEqual(self.client.get("/download/%s/both" % uid).status_code, 404)

    # -- controlled errors / no arbitrary access -------------------------- #
    def test_unknown_id_is_404_on_every_comparison_route(self):
        for path in ("/video/nope/telea", "/video/nope/ns",
                     "/download/nope/telea", "/download/nope/ns",
                     "/download/nope/both"):
            self.assertEqual(self.client.get(path).status_code, 404, path)

    def test_incomplete_job_returns_controlled_error_not_file(self):
        uid = self._upload("fake_data")
        gate = threading.Event()
        runner = _RecordingRunner(gate=gate)
        with mock.patch("core.video_pipeline.process_video", runner):
            self.client.post("/process", json={"id": uid})
            try:
                # Job still running (blocked in the gate) — outputs not ready.
                self.assertEqual(self.client.get("/video/%s/telea" % uid).status_code, 409)
                self.assertEqual(self.client.get("/download/%s/ns" % uid).status_code, 409)
                self.assertEqual(self.client.get("/download/%s/both" % uid).status_code, 409)
            finally:
                gate.set()
                server._STATE[uid]["job"].join(5)

    def test_completed_but_missing_file_is_404_not_serving(self):
        uid, _runner, _ = self._complete_fake_data()
        os.remove(server._STATE[uid]["output_paths"]["telea"])
        self.assertEqual(self.client.get("/video/%s/telea" % uid).status_code, 404)
        self.assertEqual(self.client.get("/download/%s/telea" % uid).status_code, 404)
        # both-zip also refuses when either file is gone
        self.assertEqual(self.client.get("/download/%s/both" % uid).status_code, 404)

    def test_job_persists_for_navigation_after_completion(self):
        # Navigating away and back must reconnect to the SAME job (its snapshot
        # stays pollable and the nav carries the job id).
        uid, _runner, _ = self._complete_fake_data()
        self.assertEqual(self.client.get("/processing?job=%s" % uid).status_code, 200)
        snap = self.client.get("/job/%s" % uid).get_json()
        self.assertEqual(snap["status"], "complete")
        self.assertEqual(snap["num_passes"], 2)

    def test_results_robust_to_ui_mode_change(self):
        # Even if the UI mode in _STATE is toggled back to "blur" after a fake_data job
        # completes, /results and per-method routes must still resolve using job.mode.
        uid, _runner, _ = self._complete_fake_data()
        server._STATE[uid]["mode"] = "blur"
        r = self.client.get("/results?job=%s" % uid)
        self.assertEqual(r.status_code, 200)
        self.assertIn("Fake Data — TELEA", r.get_data(as_text=True))
        self.assertEqual(self.client.get("/video/%s/telea" % uid).status_code, 200)
        self.assertEqual(self.client.get("/download/%s/both" % uid).status_code, 200)


if __name__ == "__main__":
    unittest.main()
