"""
Focused tests for the Settings screen of the Flask test harness
(tools/webtest) — the Phase 3 batch that makes the OCR sample rate,
face-detection confidence, and the four PII regex patterns FUNCTIONAL: an
edited value must actually change what a subsequently started job does.

Two layers:
  * settings_store / route tests: the page renders current + default values,
    valid saves apply, invalid input (OCR rate, confidence, regex) is rejected
    with 400 WITHOUT corrupting the last valid configuration, and reset restores
    defaults.
  * Integration tests: a saved OCR sample rate and face confidence reach
    core.video_pipeline.process_video() (mocked, so OCR never runs), and a saved
    PII regex actually changes core.pii_matcher matching. The core-level proof
    that face_min_confidence reaches face_detector.detect_faces lives in
    tests/test_video_pipeline.py (TestFaceMinConfidence).

Settings are process-global (settings_store + core.pii_matcher module state), so
every test restores defaults in tearDown — an override must never leak into
another test or another test file.
"""

import os
import shutil
import sys
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

from core import face_detector  # noqa: E402
from core import pii_matcher  # noqa: E402
from webtest import server, settings_store  # noqa: E402

# Reuse the deterministic fake process_video from the processing tests so OCR /
# OpenCV never run here.
from test_webtest_processing import _RecordingRunner  # noqa: E402


class _SettingsTestBase(unittest.TestCase):
    def setUp(self):
        server.app.config["TESTING"] = True
        self.client = server.app.test_client()
        server._STATE.clear()
        server._ACTIVE_JOB_UID = None
        # Start every test from a known-default configuration.
        settings_store.reset_settings()

    def tearDown(self):
        for st in server._STATE.values():
            job = st.get("job")
            if job is not None:
                job.join(5)
        server._STATE.clear()
        server._ACTIVE_JOB_UID = None
        # CRITICAL: restore process-global settings so nothing leaks into other
        # tests / files (settings_store also resets pii_matcher's patterns).
        settings_store.reset_settings()
        # Some tests start a (mocked) job, which creates outputs/<uid>; clean up.
        shutil.rmtree(server.OUTPUT_DIR, ignore_errors=True)
        shutil.rmtree(server.UPLOAD_DIR, ignore_errors=True)


class TestSettingsRoutes(_SettingsTestBase):
    def test_page_renders_current_and_default_values(self):
        r = self.client.get("/settings")
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        # Current OCR rate + the four PII pattern inputs are rendered.
        self.assertIn('id="ocrRate"', html)
        for pii_type in pii_matcher.PII_TYPES:
            self.assertIn('id="pattern%s"' % pii_type, html)
        # The default face confidence is shown somewhere on the page.
        self.assertIn("%.2f" % face_detector.DEFAULT_MIN_CONFIDENCE, html)

    def test_values_endpoint_reports_defaults(self):
        s = self.client.get("/settings/values").get_json()
        self.assertEqual(s["ocr_sample_rate"], settings_store.DEFAULT_OCR_SAMPLE_RATE)
        self.assertAlmostEqual(s["face_min_confidence"],
                               float(face_detector.DEFAULT_MIN_CONFIDENCE))
        self.assertEqual(s["pii_patterns"], pii_matcher.get_default_patterns())
        self.assertIn("defaults", s)

    def test_valid_save_applies(self):
        r = self.client.post("/settings", json={
            "ocr_sample_rate": 5,
            "face_min_confidence": 0.7,
            "pii_patterns": {"EMAIL": r"custom@example\.com"},
        })
        self.assertEqual(r.status_code, 200)
        s = r.get_json()
        self.assertEqual(s["ocr_sample_rate"], 5)
        self.assertAlmostEqual(s["face_min_confidence"], 0.7)
        self.assertEqual(s["pii_patterns"]["EMAIL"], r"custom@example\.com")
        # Untouched types keep their defaults.
        self.assertEqual(s["pii_patterns"]["PHONE"],
                         pii_matcher.get_default_patterns()["PHONE"])

    def test_invalid_ocr_rate_rejected(self):
        for bad in (0, -3, "1.5", "abc"):
            with self.subTest(bad=bad):
                r = self.client.post("/settings", json={"ocr_sample_rate": bad})
                self.assertEqual(r.status_code, 400)
                self.assertIn("error", r.get_json())
        # Nothing changed.
        self.assertEqual(settings_store.get_settings()["ocr_sample_rate"],
                         settings_store.DEFAULT_OCR_SAMPLE_RATE)

    def test_invalid_confidence_rejected(self):
        for bad in (-0.1, 1.5, "high"):
            with self.subTest(bad=bad):
                r = self.client.post("/settings",
                                     json={"face_min_confidence": bad})
                self.assertEqual(r.status_code, 400)
        self.assertAlmostEqual(
            settings_store.get_settings()["face_min_confidence"],
            float(face_detector.DEFAULT_MIN_CONFIDENCE))

    def test_invalid_regex_rejected_without_corrupting_current(self):
        # First set a valid custom EMAIL pattern.
        ok = self.client.post("/settings",
                              json={"pii_patterns": {"EMAIL": r"foo@bar\.com"}})
        self.assertEqual(ok.status_code, 200)
        # Now a bad regex must be rejected and NOT replace the valid one.
        bad = self.client.post("/settings",
                               json={"pii_patterns": {"EMAIL": r"("}})
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(pii_matcher.get_patterns()["EMAIL"], r"foo@bar\.com")

    def test_reset_restores_defaults(self):
        self.client.post("/settings", json={
            "ocr_sample_rate": 9,
            "face_min_confidence": 0.9,
            "pii_patterns": {"PHONE": r"NOPE"},
        })
        r = self.client.post("/settings/reset")
        self.assertEqual(r.status_code, 200)
        s = r.get_json()
        self.assertEqual(s["ocr_sample_rate"], settings_store.DEFAULT_OCR_SAMPLE_RATE)
        self.assertAlmostEqual(s["face_min_confidence"],
                               float(face_detector.DEFAULT_MIN_CONFIDENCE))
        self.assertEqual(s["pii_patterns"], pii_matcher.get_default_patterns())
        # And matching is back to shipped behavior.
        self.assertTrue(pii_matcher.is_phone("555-123-4567"))


class TestSettingsAffectProcessing(_SettingsTestBase):
    def _fake_upload(self, mode="blur", zones=None):
        import uuid
        uid = uuid.uuid4().hex
        server._STATE[uid] = {
            "video_path": os.path.join(server.UPLOAD_DIR, uid, "clip.mp4"),
            "frame_path": os.path.join(server.UPLOAD_DIR, uid, "frame0.png"),
            "width": 100, "height": 80,
            "mode": mode, "zones": zones or [],
        }
        return uid

    def test_saved_ocr_rate_and_confidence_reach_process_video(self):
        # Save non-default tuning, then start a job with process_video mocked.
        self.client.post("/settings", json={
            "ocr_sample_rate": 4, "face_min_confidence": 0.8,
        })
        uid = self._fake_upload()
        runner = _RecordingRunner()
        with mock.patch("core.video_pipeline.process_video", runner):
            self.client.post("/process", json={"id": uid})
            server._STATE[uid]["job"].join(5)

        self.assertEqual(len(runner.calls), 1)
        call = runner.calls[0]
        self.assertEqual(call["ocr_sample_rate"], 4)
        self.assertEqual(call["face_min_confidence"], 0.8)

    def test_default_job_uses_pipeline_defaults(self):
        # With no save, a job uses the shipped defaults (rate=1, confidence=None
        # meaning "detector default"): unchanged behavior.
        uid = self._fake_upload()
        runner = _RecordingRunner()
        with mock.patch("core.video_pipeline.process_video", runner):
            self.client.post("/process", json={"id": uid})
            server._STATE[uid]["job"].join(5)
        call = runner.calls[0]
        self.assertEqual(call["ocr_sample_rate"], 1)
        self.assertAlmostEqual(call["face_min_confidence"],
                               float(face_detector.DEFAULT_MIN_CONFIDENCE))

    def test_saved_regex_actually_changes_pii_matching(self):
        # A phone-shaped string matches by default...
        self.assertTrue(pii_matcher.is_phone("555-123-4567"))
        # ...saving a pattern that only matches a literal makes it miss, and the
        # pipeline's classifier (which calls is_phone) changes with it.
        r = self.client.post("/settings",
                             json={"pii_patterns": {"PHONE": r"CALLME"}})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(pii_matcher.is_phone("555-123-4567"))
        self.assertTrue(pii_matcher.is_phone("please CALLME now"))


if __name__ == "__main__":
    unittest.main()
