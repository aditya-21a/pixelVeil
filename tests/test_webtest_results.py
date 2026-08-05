"""
Focused tests for the Results workflow of the Flask test harness
(tools/webtest) — the Phase 3 task that renders the Results screen from the
state a completed ProcessingJob already produced: before/after video playback,
the real process_video() summary, and a download button.

process_video is always mocked here (per the task) so OCR never runs. Completed
jobs are simulated by running a fake runner through /process and then writing a
small placeholder output file at the job's output_path (the fake runner does not
write one). Video/download routes are exercised against real on-disk files.
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


class TestResultsWorkflow(unittest.TestCase):
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

    def _complete_job(self, uid, summary=None, write_output=True):
        """Run a fake job to completion via /process, optionally writing an
        actual output file (the fake runner does not create one)."""
        runner = _RecordingRunner(summary=summary or _summary())
        with mock.patch("core.video_pipeline.process_video", runner):
            self.client.post("/process", json={"id": uid})
            server._STATE[uid]["job"].join(5)
        if write_output:
            out_path = server._STATE[uid]["output_path"]
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, "wb") as fh:
                fh.write(b"\x00\x00\x00\x18ftypmp42redacted-video-bytes")
        return server._STATE[uid]["job"]

    # -- happy path -----------------------------------------------------------
    def test_completed_job_renders_results(self):
        uid = self._make_upload_with_source()
        self._complete_job(uid, summary=_summary(frames=60, faces=3))
        r = self.client.get(f"/results?job={uid}")
        self.assertEqual(r.status_code, 200)
        body = r.get_data(as_text=True)
        # before/after players point at the controlled video routes
        self.assertIn(f"/video/{uid}/original", body)
        self.assertIn(f"/video/{uid}/processed", body)
        # download button present
        self.assertIn(f"/download/{uid}", body)
        # no leftover "Flag an issue" control rendered as a button/link
        self.assertNotIn(">Flag an issue<", body)

    def test_summary_uses_actual_job_data(self):
        uid = self._make_upload_with_source()
        summary = {
            "frames_processed": 42,
            "faces_blurred": 7,
            "pii_by_type": {"EMAIL": 2, "PHONE": 1, "CARD": 0, "IP": 3},
            "zones_applied": 5,
        }
        self._complete_job(uid, summary=summary)
        body = self.client.get(f"/results?job={uid}").get_data(as_text=True)
        self.assertIn("42", body)          # frames processed
        self.assertIn("7", body)           # faces blurred
        self.assertIn("emails 2", body)
        self.assertIn("phones 1", body)
        self.assertIn("cards 0", body)
        self.assertIn("IPs 3", body)
        # total PII = 2+1+0+3 = 6
        self.assertIn("<strong>6</strong>", body)

    # -- controlled video routes ---------------------------------------------
    def test_original_video_route_serves_file(self):
        uid = self._make_upload_with_source()
        self._complete_job(uid)
        r = self.client.get(f"/video/{uid}/original")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.mimetype.startswith("video/"))
        self.assertIn(b"original-video-bytes", r.get_data())

    def test_processed_video_route_serves_file(self):
        uid = self._make_upload_with_source()
        self._complete_job(uid)
        r = self.client.get(f"/video/{uid}/processed")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.mimetype.startswith("video/"))
        self.assertIn(b"redacted-video-bytes", r.get_data())

    # -- download -------------------------------------------------------------
    def test_download_returns_processed_file_with_real_name(self):
        uid = self._make_upload_with_source(filename="meeting.mp4")
        self._complete_job(uid)
        r = self.client.get(f"/download/{uid}")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"redacted-video-bytes", r.get_data())
        # served as an attachment preserving the real output filename
        disp = r.headers.get("Content-Disposition", "")
        self.assertIn("attachment", disp)
        self.assertIn("redacted_meeting.mp4", disp)

    # -- edge cases -----------------------------------------------------------
    def test_unknown_job_handled(self):
        r = self.client.get("/results?job=does-not-exist")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Unknown job", r.get_data(as_text=True))

    def test_no_job_param_handled(self):
        r = self.client.get("/results")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Unknown job", r.get_data(as_text=True))

    def test_still_running_job_handled(self):
        uid = self._make_upload_with_source()
        gate = threading.Event()
        runner = _RecordingRunner(gate=gate)
        with mock.patch("core.video_pipeline.process_video", runner):
            self.client.post("/process", json={"id": uid})
            try:
                r = self.client.get(f"/results?job={uid}")
                self.assertEqual(r.status_code, 200)
                self.assertIn("still running", r.get_data(as_text=True))
            finally:
                gate.set()
                server._STATE[uid]["job"].join(5)

    def test_failed_job_handled(self):
        uid = self._make_upload_with_source()
        runner = _RecordingRunner(raises=RuntimeError("ffmpeg blew up"))
        with mock.patch("core.video_pipeline.process_video", runner):
            self.client.post("/process", json={"id": uid})
            server._STATE[uid]["job"].join(5)
        body = self.client.get(f"/results?job={uid}").get_data(as_text=True)
        self.assertIn("Processing failed", body)
        self.assertIn("ffmpeg blew up", body)

    def test_completed_but_output_missing_handled(self):
        uid = self._make_upload_with_source()
        # complete the job but do NOT write the output file
        self._complete_job(uid, write_output=False)
        r = self.client.get(f"/results?job={uid}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("missing", r.get_data(as_text=True))

    def test_processed_video_route_409_before_complete(self):
        uid = self._make_upload_with_source()
        gate = threading.Event()
        runner = _RecordingRunner(gate=gate)
        with mock.patch("core.video_pipeline.process_video", runner):
            self.client.post("/process", json={"id": uid})
            try:
                r = self.client.get(f"/video/{uid}/processed")
                self.assertEqual(r.status_code, 409)
            finally:
                gate.set()
                server._STATE[uid]["job"].join(5)

    def test_download_unknown_job_404(self):
        r = self.client.get("/download/does-not-exist")
        self.assertEqual(r.status_code, 404)

    def test_video_route_unknown_upload_404(self):
        self.assertEqual(self.client.get("/video/nope/original").status_code, 404)
        self.assertEqual(self.client.get("/video/nope/processed").status_code, 404)

    def test_arbitrary_filesystem_path_cannot_be_requested(self):
        # The routes are keyed by upload id, not a path. There is no route that
        # accepts a filesystem path, so a traversal-style id is just an unknown
        # id -> 404, and it can never map to a real file outside _STATE.
        for evil in ("..%2f..%2fetc%2fpasswd", "....//....//secret",
                     "%2e%2e%2fserver.py"):
            r = self.client.get(f"/download/{evil}")
            self.assertEqual(r.status_code, 404)
            r2 = self.client.get(f"/video/{evil}/original")
            self.assertEqual(r2.status_code, 404)


if __name__ == "__main__":
    unittest.main()
