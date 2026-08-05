"""
Focused tests for the Processing workflow of the Flask test harness
(tools/webtest) — the Phase 3 batch that wires "Process Video" to
core.video_pipeline.process_video() and drives the live Processing screen.

Two layers:
  * ProcessingJob unit tests (tools/webtest/job.py) with an INJECTED fake
    runner — deterministic, never touch OpenCV/OCR. Cover the progress_callback
    wiring, cumulative counters, the technical log, completion state, and the
    controlled error state.
  * Flask route tests via app.test_client() with core.video_pipeline.process_video
    MOCKED. Cover: process rejected without a valid upload, successful job start,
    the exact input/output/mode/zones passed to process_video(), non-blocking
    (background) execution, live /job polling of progress + log, completion, the
    error surface, and duplicate-start protection.

process_video is always mocked here (per the task) so OCR never runs.
"""

import os
import shutil
import sys
import threading
import time
import unittest
from unittest import mock

import numpy as np

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

from webtest import server  # noqa: E402
from webtest.job import ProcessingJob, RUNNING, COMPLETE, ERROR  # noqa: E402


def _summary(frames=2, faces=1):
    return {
        "frames_processed": frames,
        "faces_blurred": faces,
        "pii_by_type": {"EMAIL": 1, "PHONE": 0, "CARD": 0, "IP": 0},
        "zones_applied": 0,
    }


class _RecordingRunner:
    """Stand-in for process_video: records its call, optionally drives the
    progress callback with canned events, can block on a gate, or raise."""

    def __init__(self, events=(), summary=None, raises=None, gate=None,
                 preview_events=()):
        self.events = list(events)
        self.preview_events = list(preview_events)
        self.summary = summary if summary is not None else _summary()
        self.raises = raises
        self.gate = gate
        self.calls = []

    def __call__(self, input_path, output_path, mode="blur", zones=None,
                 ocr_sample_rate=1, face_min_confidence=None,
                 progress_callback=None, preview_callback=None):
        self.calls.append({
            "input_path": input_path,
            "output_path": output_path,
            "mode": mode,
            "zones": zones,
            "ocr_sample_rate": ocr_sample_rate,
            "face_min_confidence": face_min_confidence,
            "progress_callback": progress_callback,
            "preview_callback": preview_callback,
        })
        if self.gate is not None:
            self.gate.wait(5)
        if self.raises is not None:
            raise self.raises
        for ev in self.events:
            progress_callback(ev)
        for ev in self.preview_events:
            if preview_callback is not None:
                preview_callback(ev)
        return self.summary


# --------------------------------------------------------------------------- #
# ProcessingJob unit tests (no Flask, injected runner)
# --------------------------------------------------------------------------- #
class TestProcessingJobUnit(unittest.TestCase):
    def _run_job(self, runner, mode="blur", zones=None):
        job = ProcessingJob("uid1", "/src/in.mp4", "/out/redacted_in.mp4",
                            mode, zones or [], runner=runner)
        job.start()
        job.join(5)
        return job

    def test_passes_input_output_mode_zones_to_runner(self):
        runner = _RecordingRunner()
        self._run_job(runner, mode="fake_data", zones=[(1, 2, 3, 4)])
        self.assertEqual(len(runner.calls), 1)
        call = runner.calls[0]
        self.assertEqual(call["input_path"], "/src/in.mp4")
        self.assertEqual(call["output_path"], "/out/redacted_in.mp4")
        self.assertEqual(call["mode"], "fake_data")
        self.assertEqual(call["zones"], [(1, 2, 3, 4)])
        self.assertTrue(callable(call["progress_callback"]))

    def test_progress_callback_updates_counters(self):
        runner = _RecordingRunner(events=[
            {"frame": 1, "total": 2, "faces": 1, "pii": 0},
            {"frame": 2, "total": 2, "faces": 0, "pii": 2},
        ], summary=_summary())
        job = self._run_job(runner)
        snap = job.snapshot()
        self.assertEqual(snap["status"], COMPLETE)
        self.assertEqual(snap["frame"], 2)
        self.assertEqual(snap["total"], 2)
        self.assertEqual(snap["percent"], 100)
        self.assertEqual(snap["faces"], 1)   # cumulative
        self.assertEqual(snap["pii"], 2)     # cumulative

    def test_technical_log_populated(self):
        runner = _RecordingRunner(events=[
            {"frame": 1, "total": 1, "faces": 1, "pii": 0},
        ])
        job = self._run_job(runner)
        log = "\n".join(job.snapshot()["log"])
        self.assertIn("job started", log)
        self.assertIn("frame 1/1", log)
        self.assertIn("complete", log)

    def test_completion_records_summary_and_stages_complete(self):
        runner = _RecordingRunner(summary=_summary(frames=5, faces=3))
        job = self._run_job(runner)
        snap = job.snapshot()
        self.assertEqual(snap["status"], COMPLETE)
        self.assertTrue(snap["output_ready"])
        self.assertEqual(snap["summary"]["frames_processed"], 5)
        self.assertTrue(all(s["state"] == COMPLETE for s in snap["stages"]))

    def test_pipeline_exception_becomes_controlled_error_state(self):
        runner = _RecordingRunner(raises=RuntimeError("ffmpeg blew up"))
        job = self._run_job(runner)
        snap = job.snapshot()
        self.assertEqual(snap["status"], ERROR)
        self.assertIn("ffmpeg blew up", snap["error"])
        self.assertFalse(snap["output_ready"])
        self.assertTrue(all(s["state"] == ERROR for s in snap["stages"]))

    def test_is_active_true_only_while_running(self):
        gate = threading.Event()
        runner = _RecordingRunner(gate=gate)
        job = ProcessingJob("u", "/i", "/o", "blur", [], runner=runner)
        job.start()
        try:
            self.assertTrue(job.is_active())
            self.assertEqual(job.snapshot()["status"], RUNNING)
        finally:
            gate.set()
            job.join(5)
        self.assertFalse(job.is_active())


# --------------------------------------------------------------------------- #
# Flask route tests (process_video mocked)
# --------------------------------------------------------------------------- #
class TestProcessRoutes(unittest.TestCase):
    def setUp(self):
        server.app.config["TESTING"] = True
        self.client = server.app.test_client()
        server._STATE.clear()
        server._ACTIVE_JOB_UID = None

    def tearDown(self):
        # Make sure no worker thread outlives the test.
        for st in server._STATE.values():
            job = st.get("job")
            if job is not None:
                job.join(5)
        server._STATE.clear()
        server._ACTIVE_JOB_UID = None
        shutil.rmtree(server.OUTPUT_DIR, ignore_errors=True)
        shutil.rmtree(server.UPLOAD_DIR, ignore_errors=True)

    def _fake_upload(self, mode="blur", zones=None):
        import uuid
        uid = uuid.uuid4().hex
        server._STATE[uid] = {
            "video_path": os.path.join(server.UPLOAD_DIR, uid, "clip.mp4"),
            "frame_path": os.path.join(server.UPLOAD_DIR, uid, "frame0.png"),
            "width": 100,
            "height": 80,
            "mode": mode,
            "zones": zones or [],
        }
        return uid

    def test_process_without_valid_upload_rejected(self):
        r = self.client.post("/process", json={"id": "nope"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("upload a valid video", r.get_json()["error"])

    def test_successful_job_start_returns_202(self):
        uid = self._fake_upload()
        runner = _RecordingRunner()
        with mock.patch("core.video_pipeline.process_video", runner):
            r = self.client.post("/process", json={"id": uid})
            server._STATE[uid]["job"].join(5)
        self.assertEqual(r.status_code, 202)
        body = r.get_json()
        self.assertEqual(body["id"], uid)
        self.assertIn("/job/", body["poll_url"])

    def test_correct_input_output_mode_zones_passed_to_process_video(self):
        uid = self._fake_upload(mode="fake_data", zones=[[10, 20, 30, 40]])
        runner = _RecordingRunner()
        with mock.patch("core.video_pipeline.process_video", runner):
            self.client.post("/process", json={"id": uid})
            server._STATE[uid]["job"].join(5)

        self.assertEqual(len(runner.calls), 1)
        call = runner.calls[0]
        # input is the uploaded source; output is a SEPARATE outputs/ path
        self.assertEqual(call["input_path"], server._STATE[uid]["video_path"])
        self.assertTrue(call["output_path"].startswith(server.OUTPUT_DIR))
        self.assertNotEqual(call["input_path"], call["output_path"])
        self.assertEqual(call["mode"], "fake_data")
        # zones passed as (x,y,w,h) tuples — ZoneManager's expected form
        self.assertEqual(call["zones"], [(10, 20, 30, 40)])
        self.assertEqual(call["ocr_sample_rate"], 1)
        self.assertTrue(callable(call["progress_callback"]))

    def test_processing_is_non_blocking(self):
        uid = self._fake_upload()
        gate = threading.Event()
        runner = _RecordingRunner(gate=gate)
        with mock.patch("core.video_pipeline.process_video", runner):
            start = time.monotonic()
            r = self.client.post("/process", json={"id": uid})
            elapsed = time.monotonic() - start
            try:
                # Returned promptly while the worker is still blocked in the gate.
                self.assertEqual(r.status_code, 202)
                self.assertLess(elapsed, 2.0)
                self.assertEqual(server._STATE[uid]["job"].snapshot()["status"], RUNNING)
            finally:
                gate.set()
                server._STATE[uid]["job"].join(5)
        self.assertEqual(server._STATE[uid]["job"].snapshot()["status"], COMPLETE)

    def test_job_polling_reports_progress_and_log(self):
        uid = self._fake_upload()
        runner = _RecordingRunner(events=[
            {"frame": 1, "total": 2, "faces": 1, "pii": 0},
            {"frame": 2, "total": 2, "faces": 0, "pii": 1},
        ], summary=_summary())
        with mock.patch("core.video_pipeline.process_video", runner):
            self.client.post("/process", json={"id": uid})
            server._STATE[uid]["job"].join(5)
            jr = self.client.get("/job/%s" % uid)

        self.assertEqual(jr.status_code, 200)
        snap = jr.get_json()
        self.assertEqual(snap["status"], "complete")
        self.assertEqual(snap["percent"], 100)
        self.assertEqual(snap["faces"], 1)
        self.assertEqual(snap["pii"], 1)
        self.assertEqual(len(snap["stages"]), 6)
        self.assertTrue(any("frame" in line for line in snap["log"]))

    def test_job_error_state_exposed(self):
        uid = self._fake_upload()
        runner = _RecordingRunner(raises=RuntimeError("boom"))
        with mock.patch("core.video_pipeline.process_video", runner):
            self.client.post("/process", json={"id": uid})
            server._STATE[uid]["job"].join(5)
            jr = self.client.get("/job/%s" % uid)
        snap = jr.get_json()
        self.assertEqual(snap["status"], "error")
        self.assertIn("boom", snap["error"])

    def test_duplicate_start_rejected_while_running(self):
        uid = self._fake_upload()
        other = self._fake_upload()
        gate = threading.Event()
        runner = _RecordingRunner(gate=gate)
        with mock.patch("core.video_pipeline.process_video", runner):
            first = self.client.post("/process", json={"id": uid})
            try:
                self.assertEqual(first.status_code, 202)
                # Same upload while running -> 409
                dup = self.client.post("/process", json={"id": uid})
                self.assertEqual(dup.status_code, 409)
                # A different upload while one job runs -> also 409 (one at a time)
                dup2 = self.client.post("/process", json={"id": other})
                self.assertEqual(dup2.status_code, 409)
            finally:
                gate.set()
                server._STATE[uid]["job"].join(5)

    def test_can_start_again_after_completion(self):
        uid = self._fake_upload()
        runner = _RecordingRunner()
        with mock.patch("core.video_pipeline.process_video", runner):
            self.client.post("/process", json={"id": uid})
            server._STATE[uid]["job"].join(5)
            # once the first job is done, a new start is allowed (not a duplicate)
            again = self.client.post("/process", json={"id": uid})
            server._STATE[uid]["job"].join(5)
        self.assertEqual(again.status_code, 202)
        self.assertEqual(len(runner.calls), 2)

    def test_job_status_unknown_id_404(self):
        r = self.client.get("/job/does-not-exist")
        self.assertEqual(r.status_code, 404)


class TestPreviewFeature(unittest.TestCase):
    """Diagnostic preview generation (job.py) and endpoint (server.py). The
    preview is a throttled, downscaled JPEG of the post-redaction frame with
    detection boxes overlaid; never embedded in /job polling, served separately."""

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

    def _fake_upload(self):
        import uuid
        uid = uuid.uuid4().hex
        server._STATE[uid] = {
            "video_path": os.path.join(server.UPLOAD_DIR, uid, "clip.mp4"),
            "frame_path": os.path.join(server.UPLOAD_DIR, uid, "frame0.png"),
            "width": 100, "height": 80,
            "mode": "blur", "zones": [],
        }
        return uid

    def test_preview_callback_wired_into_pipeline(self):
        uid = self._fake_upload()
        runner = _RecordingRunner()
        with mock.patch("core.video_pipeline.process_video", runner):
            self.client.post("/process", json={"id": uid})
            server._STATE[uid]["job"].join(5)
        self.assertTrue(callable(runner.calls[0]["preview_callback"]))

    def test_preview_endpoint_404_before_first_frame(self):
        uid = self._fake_upload()
        gate = threading.Event()
        runner = _RecordingRunner(gate=gate)
        with mock.patch("core.video_pipeline.process_video", runner):
            self.client.post("/process", json={"id": uid})
            try:
                # Job is running but the first preview hasn't landed yet.
                r = self.client.get(f"/job/{uid}/preview")
                self.assertEqual(r.status_code, 404)
            finally:
                gate.set()
                server._STATE[uid]["job"].join(5)

    def test_preview_endpoint_serves_jpeg_after_first_frame(self):
        uid = self._fake_upload()
        # Synthesize a minimal preview event: a 10x8 solid-blue frame.
        frame = np.full((8, 10, 3), (200, 0, 0), dtype=np.uint8)
        runner = _RecordingRunner(preview_events=[{"frame": frame}])
        with mock.patch("core.video_pipeline.process_video", runner):
            self.client.post("/process", json={"id": uid})
            server._STATE[uid]["job"].join(5)
            r = self.client.get(f"/job/{uid}/preview")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.mimetype, "image/jpeg")
        self.assertGreater(len(r.data), 100)  # real JPEG bytes

    def test_job_snapshot_reports_has_preview_and_seq(self):
        uid = self._fake_upload()
        frame = np.full((8, 10, 3), (0, 0, 0), dtype=np.uint8)
        runner = _RecordingRunner(preview_events=[{"frame": frame}])
        with mock.patch("core.video_pipeline.process_video", runner):
            self.client.post("/process", json={"id": uid})
            server._STATE[uid]["job"].join(5)
            jr = self.client.get(f"/job/{uid}")
        snap = jr.get_json()
        self.assertTrue(snap["has_preview"])
        self.assertIsInstance(snap["preview_seq"], int)
        self.assertGreaterEqual(snap["preview_seq"], 1)

    def test_preview_throttled_to_every_n_frames(self):
        # Job starts with preview_every=3 (injected), so only frames 1, 3 land.
        uid = self._fake_upload()
        frame = np.full((6, 8, 3), (50, 50, 50), dtype=np.uint8)
        events = [{"frame": frame, "frame_number": i, "total": 4} for i in range(1, 5)]
        runner = _RecordingRunner(preview_events=events)
        with mock.patch("core.video_pipeline.process_video", runner):
            job = server.ProcessingJob(uid, "in", "out", "blur", [],
                                        runner=runner, preview_every=3)
            server._STATE[uid]["job"] = job
            job.start()
            job.join(5)
        # seq incremented only on frames 1, 3 (4 is skipped by throttle), then
        # frame 4 as the final => 3 updates.
        _jpeg, seq = job.preview_jpeg()
        self.assertEqual(seq, 3)


if __name__ == "__main__":
    unittest.main()
