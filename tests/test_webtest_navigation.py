"""
Focused regression tests for the Phase 3 web-harness polish pass:

  * Persistent navigation context — a page navigation must NEVER lose the active
    job. A background ProcessingJob runs independently of HTTP requests, so the
    only thing that used to "lose" it was the top-nav links dropping the job id.
    The nav now carries the current job id (server-injected `active_job_uid`),
    so Processing/Results reconnect to the SAME in-memory job; merely GETting a
    page never starts/stops/replaces a job, and process_video() runs exactly
    once per started job regardless of navigation.
  * Duplicate "View results" — the Processing screen used to render a static
    fallback button in addition to the one app.js injects on completion. The
    server-rendered page must now contain no static "View results" action.

process_video is always mocked (per the harness test convention) so OCR never
runs; gated fakes hold a job "running" deterministically. Every test restores
process-global harness state in tearDown so nothing leaks across files.
"""

import os
import shutil
import sys
import threading
import unittest
import uuid
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

from webtest import server  # noqa: E402

# Reuse the recording fake runner + summary helper from the processing tests.
from test_webtest_processing import _RecordingRunner, _summary  # noqa: E402


class _NavTestBase(unittest.TestCase):
    def setUp(self):
        server.app.config["TESTING"] = True
        self.client = server.app.test_client()
        server._STATE.clear()
        server._ACTIVE_JOB_UID = None

    def tearDown(self):
        # Release any gate so a still-"running" fake job can finish, then join.
        for st in list(server._STATE.values()):
            gate = st.get("_gate")
            if gate is not None:
                gate.set()
            job = st.get("job")
            if job is not None:
                job.join(5)
        server._STATE.clear()
        server._ACTIVE_JOB_UID = None
        shutil.rmtree(server.OUTPUT_DIR, ignore_errors=True)
        shutil.rmtree(server.UPLOAD_DIR, ignore_errors=True)

    # -- fixtures -------------------------------------------------------------
    def _make_upload_with_source(self, filename="clip.mp4"):
        """Create an upload whose source video file actually exists on disk."""
        uid = uuid.uuid4().hex
        up_dir = os.path.join(server.UPLOAD_DIR, uid)
        os.makedirs(up_dir, exist_ok=True)
        video_path = os.path.join(up_dir, filename)
        with open(video_path, "wb") as fh:
            fh.write(b"\x00\x00\x00\x18ftypmp42original-video-bytes")
        server._STATE[uid] = {
            "video_path": video_path,
            "frame_path": os.path.join(up_dir, "frame0.png"),
            "width": 100, "height": 80,
            "mode": "blur", "zones": [],
        }
        return uid

    def _start_running_job(self, uid):
        """Start a job that stays 'running' until its gate is released.

        Returns the _RecordingRunner so callers can assert call counts. The gate
        is stashed in _STATE so tearDown can always release it.
        """
        gate = threading.Event()
        runner = _RecordingRunner(gate=gate)
        with mock.patch("core.video_pipeline.process_video", runner):
            self.client.post("/process", json={"id": uid})
        server._STATE[uid]["_gate"] = gate
        return runner

    def _complete_job(self, uid, summary=None, write_output=True):
        """Run a fake job to completion via /process; optionally write output."""
        runner = _RecordingRunner(summary=summary or _summary())
        with mock.patch("core.video_pipeline.process_video", runner):
            self.client.post("/process", json={"id": uid})
            server._STATE[uid]["job"].join(5)
        if write_output:
            out_path = server._STATE[uid]["output_path"]
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, "wb") as fh:
                fh.write(b"\x00\x00\x00\x18ftypmp42redacted-video-bytes")
        return runner


class TestNavigationCarriesJob(_NavTestBase):
    def test_nav_links_carry_job_while_running(self):
        uid = self._make_upload_with_source()
        self._start_running_job(uid)
        # Visiting an unrelated page still shows job-aware nav links.
        body = self.client.get("/settings").get_data(as_text=True)
        self.assertIn(f"/processing?job={uid}", body)
        self.assertIn(f"/results?job={uid}", body)

    def test_current_job_survives_navigation_to_upload(self):
        uid = self._make_upload_with_source()
        self._start_running_job(uid)
        job = server._STATE[uid]["job"]
        # Merely visiting Upload must not clear/replace the job.
        body = self.client.get("/").get_data(as_text=True)
        self.assertIn(f"/processing?job={uid}", body)
        self.assertIs(server._STATE[uid]["job"], job)   # same object
        self.assertEqual(server._ACTIVE_JOB_UID, uid)
        self.assertTrue(job.is_active())

    def test_current_job_survives_navigation_to_settings(self):
        uid = self._make_upload_with_source()
        self._start_running_job(uid)
        job = server._STATE[uid]["job"]
        self.client.get("/settings")
        self.assertIs(server._STATE[uid]["job"], job)
        self.assertTrue(job.is_active())

    def test_returning_to_processing_reuses_same_job(self):
        uid = self._make_upload_with_source()
        self._start_running_job(uid)
        job = server._STATE[uid]["job"]
        # Follow the nav link back to Processing: it must bind to the SAME job.
        r = self.client.get(f"/processing?job={uid}")
        self.assertEqual(r.status_code, 200)
        body = r.get_data(as_text=True)
        self.assertIn(f'data-job-id="{uid}"', body)     # page polls this job
        self.assertIs(server._STATE[uid]["job"], job)   # not restarted

    def test_navigation_does_not_restart_process_video(self):
        uid = self._make_upload_with_source()
        runner = self._complete_job(uid)
        # Wander around the app after completion.
        for path in ("/", "/settings", f"/processing?job={uid}",
                     f"/results?job={uid}"):
            self.assertEqual(self.client.get(path).status_code, 200)
        # process_video must have been invoked exactly once, ever.
        self.assertEqual(len(runner.calls), 1)

    def test_no_job_nav_links_are_plain(self):
        # With no job at all, the nav falls back to bare links (sensible default).
        body = self.client.get("/").get_data(as_text=True)
        self.assertNotIn("/processing?job=", body)
        self.assertNotIn("/results?job=", body)
        self.assertIn('href="/processing"', body)
        self.assertIn('href="/results"', body)


class TestCompletedJobStillReachable(_NavTestBase):
    def test_completed_job_accessible_through_results_nav(self):
        uid = self._make_upload_with_source()
        self._complete_job(uid, summary=_summary(frames=60, faces=3))
        # The nav on any page carries the completed job to Results...
        nav = self.client.get("/settings").get_data(as_text=True)
        self.assertIn(f"/results?job={uid}", nav)
        # ...and that Results link renders the finished result, not an error.
        r = self.client.get(f"/results?job={uid}")
        self.assertEqual(r.status_code, 200)
        body = r.get_data(as_text=True)
        self.assertNotIn("Unknown job", body)
        self.assertIn(f"/video/{uid}/processed", body)

    def test_results_nav_before_completion_is_handled(self):
        uid = self._make_upload_with_source()
        self._start_running_job(uid)
        # Clicking Results while still processing must not lose state: it shows
        # the "still running" state with a link back to Processing.
        r = self.client.get(f"/results?job={uid}")
        self.assertEqual(r.status_code, 200)
        body = r.get_data(as_text=True)
        self.assertIn("still running", body)
        self.assertIn(f"/processing?job={uid}", body)

    def test_video_and_download_routes_still_serve_after_navigation(self):
        uid = self._make_upload_with_source(filename="meeting.mp4")
        self._complete_job(uid)
        # Navigate around, then confirm the controlled routes still serve.
        self.client.get("/")
        self.client.get("/settings")
        orig = self.client.get(f"/video/{uid}/original")
        proc = self.client.get(f"/video/{uid}/processed")
        dl = self.client.get(f"/download/{uid}")
        self.assertEqual(orig.status_code, 200)
        self.assertIn(b"original-video-bytes", orig.get_data())
        self.assertEqual(proc.status_code, 200)
        self.assertIn(b"redacted-video-bytes", proc.get_data())
        self.assertEqual(dl.status_code, 200)
        self.assertIn("attachment", dl.headers.get("Content-Disposition", ""))
        self.assertIn("redacted_meeting.mp4", dl.headers.get("Content-Disposition", ""))

    def test_polling_stop_does_not_clear_completed_job(self):
        # A completed job's state persists after polling/navigation stops.
        uid = self._make_upload_with_source()
        self._complete_job(uid)
        self.assertIn(uid, server._STATE)
        self.assertEqual(server._STATE[uid]["job"].status, "complete")
        self.assertEqual(self.client.get(f"/results?job={uid}").status_code, 200)


class TestSingleViewResultsAction(_NavTestBase):
    def test_processing_page_has_no_static_view_results_button(self):
        # The duplicate static "View results" button was removed; the only one
        # is injected by app.js into #processingDone on completion.
        uid = self._make_upload_with_source()
        self._start_running_job(uid)
        body = self.client.get(f"/processing?job={uid}").get_data(as_text=True)
        # No static <a ...>View results</a> element rendered by the server (the
        # phrase may still appear in an explanatory comment — assert on the tag).
        self.assertNotIn(">View results</a>", body)
        self.assertIn('id="processingDone"', body)  # JS injection target present

    def test_app_js_injects_exactly_one_view_results_action(self):
        # Guard the "keep ONE clear action" requirement: app.js contains a single
        # "View results" action (the completion primary), so with the static one
        # gone there is exactly one overall.
        app_js = os.path.join(REPO_ROOT, "tools", "webtest", "static", "js", "app.js")
        with open(app_js, encoding="utf-8") as fh:
            self.assertEqual(fh.read().count("View results"), 1)


if __name__ == "__main__":
    unittest.main()
