"""
Focused tests for the Upload screen of the Flask test harness
(tools/webtest) — the Phase 3 "file picker/drag-drop, mode toggle,
zone-drawing canvas on first frame" task.

Two layers:
  * Pure-function tests for tools/webtest/upload_support.py — the validation
    allowlist, rect normalization, and (most importantly) the display->video
    pixel coordinate conversion that ZoneManager depends on, including the
    resized-frame case.
  * Flask route tests via app.test_client() — valid upload, invalid/non-video
    rejection, first-frame extraction/serving, mode selection, the Process
    Video enable/guard rule, and zone create/delete through the API. No mocks of
    OpenCV — real tiny videos are generated at test time (and one real sample
    fixture is used when present).

The web harness is not on the default import path, so we add tools/ explicitly.
Nothing here calls core.video_pipeline.process_video (not wired yet).
"""

import io
import os
import shutil
import sys
import unittest

import numpy as np
import cv2

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

from webtest import upload_support  # noqa: E402
from webtest import server  # noqa: E402


SAMPLE_DIR = os.path.join(REPO_ROOT, "tests", "sample_videos")


def _clear_uploads():
    """Remove anything the harness wrote under its uploads dir (git-ignored)."""
    server._STATE.clear()
    shutil.rmtree(server.UPLOAD_DIR, ignore_errors=True)


def _make_video_bytes(w=64, h=48, n=3, fps=10.0):
    """Encode a tiny valid mp4 in a temp file and return its raw bytes."""
    import tempfile

    fd, path = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)
    try:
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(path, fourcc, fps, (w, h))
        assert writer.isOpened(), "could not open VideoWriter for test fixture"
        for i in range(n):
            frame = np.full((h, w, 3), (i * 10) % 255, np.uint8)
            writer.write(frame)
        writer.release()
        with open(path, "rb") as fh:
            return fh.read()
    finally:
        os.remove(path)


# --------------------------------------------------------------------------- #
# Pure helpers: validation + coordinate math
# --------------------------------------------------------------------------- #
class TestValidationHelpers(unittest.TestCase):
    def test_allowed_extensions(self):
        for name in ["a.mp4", "A.MOV", "clip.mkv", "x.avi", "y.webm", "z.m4v"]:
            self.assertTrue(upload_support.is_allowed_video_filename(name), name)

    def test_rejected_extensions(self):
        for name in ["a.txt", "photo.png", "doc.pdf", "archive.zip", "noext", ""]:
            self.assertFalse(upload_support.is_allowed_video_filename(name), name)

    def test_none_filename(self):
        self.assertFalse(upload_support.is_allowed_video_filename(None))


class TestNormalizeRect(unittest.TestCase):
    def test_top_left_to_bottom_right(self):
        self.assertEqual(upload_support.normalize_rect(10, 20, 40, 60), (10, 20, 30, 40))

    def test_reversed_drag(self):
        # dragging bottom-right -> top-left yields the same box
        self.assertEqual(upload_support.normalize_rect(40, 60, 10, 20), (10, 20, 30, 40))


class TestDisplayToVideoRect(unittest.TestCase):
    def test_identity_when_same_size(self):
        rect = (10, 20, 30, 40)
        out = upload_support.display_to_video_rect(rect, (100, 100), (100, 100))
        self.assertEqual(out, (10, 20, 30, 40))

    def test_uniform_2x_upscale(self):
        # display is half the video size -> every coord doubles
        out = upload_support.display_to_video_rect((10, 20, 30, 40), (480, 270), (960, 540))
        self.assertEqual(out, (20, 40, 60, 80))

    def test_non_uniform_scale_axes_independent(self):
        # different scale per axis (x*4, y*3) must be handled independently
        out = upload_support.display_to_video_rect((10, 10, 20, 20), (100, 100), (400, 300))
        self.assertEqual(out, (40, 30, 80, 60))

    def test_clamped_to_frame(self):
        # a box running off the display edge clamps to the video bounds
        out = upload_support.display_to_video_rect((90, 90, 40, 40), (100, 100), (200, 200))
        x, y, w, h = out
        self.assertEqual((x, y), (180, 180))
        self.assertLessEqual(x + w, 200)
        self.assertLessEqual(y + h, 200)

    def test_zero_display_raises(self):
        with self.assertRaises(ValueError):
            upload_support.display_to_video_rect((0, 0, 1, 1), (0, 100), (100, 100))

    def test_zero_video_raises(self):
        with self.assertRaises(ValueError):
            upload_support.display_to_video_rect((0, 0, 1, 1), (100, 100), (100, 0))

    def test_full_frame_roundtrip_resized(self):
        # a zone covering the whole resized canvas maps to the whole video frame
        out = upload_support.display_to_video_rect((0, 0, 320, 180), (320, 180), (1920, 1080))
        self.assertEqual(out, (0, 0, 1920, 1080))


# --------------------------------------------------------------------------- #
# Flask routes
# --------------------------------------------------------------------------- #
class TestUploadRoutes(unittest.TestCase):
    def setUp(self):
        server.app.config["TESTING"] = True
        self.client = server.app.test_client()
        # isolate state between tests
        server._STATE.clear()

    def tearDown(self):
        _clear_uploads()

    def _upload(self, data_bytes, filename):
        return self.client.post(
            "/upload",
            data={"video": (io.BytesIO(data_bytes), filename)},
            content_type="multipart/form-data",
        )

    def test_valid_upload_returns_state(self):
        r = self._upload(_make_video_bytes(w=64, h=48), "clip.mp4")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertIn("id", body)
        self.assertEqual(body["width"], 64)
        self.assertEqual(body["height"], 48)
        self.assertEqual(body["mode"], "blur")
        self.assertEqual(body["zones"], [])

    def test_first_frame_extracted_and_served(self):
        r = self._upload(_make_video_bytes(w=48, h=32), "clip.mp4")
        uid = r.get_json()["id"]
        # the extracted frame file exists on disk...
        self.assertTrue(os.path.exists(server._STATE[uid]["frame_path"]))
        # ...and is served as a PNG of the right size
        fr = self.client.get("/frame/%s" % uid)
        self.assertEqual(fr.status_code, 200)
        self.assertEqual(fr.mimetype, "image/png")
        img = cv2.imdecode(np.frombuffer(fr.data, np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual((img.shape[1], img.shape[0]), (48, 32))

    def test_invalid_extension_rejected(self):
        r = self._upload(b"this is not a video", "notes.txt")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Unsupported file type", r.get_json()["error"])

    def test_video_named_file_that_is_not_decodable_rejected(self):
        # passes the extension allowlist but is not a real video -> 400
        r = self._upload(b"PK\x03\x04 not really an mp4", "fake.mp4")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Could not read", r.get_json()["error"])

    def test_missing_file_field(self):
        r = self.client.post("/upload", data={}, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 400)

    def test_mode_selection_persists(self):
        uid = self._upload(_make_video_bytes(), "clip.mp4").get_json()["id"]
        r = self.client.post("/mode", json={"id": uid, "mode": "fake_data"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(server._STATE[uid]["mode"], "fake_data")

    def test_invalid_mode_rejected(self):
        uid = self._upload(_make_video_bytes(), "clip.mp4").get_json()["id"]
        r = self.client.post("/mode", json={"id": uid, "mode": "melt"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(server._STATE[uid]["mode"], "blur")  # unchanged

    def test_process_disabled_before_upload(self):
        # no valid id -> guarded (mirrors the button being disabled in the UI)
        r = self.client.post("/process", json={"id": "does-not-exist"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("upload a valid video", r.get_json()["error"])

    def test_process_after_upload_hits_placeholder_not_pipeline(self):
        uid = self._upload(_make_video_bytes(), "clip.mp4").get_json()["id"]
        r = self.client.post("/process", json={"id": uid})
        # 501: ready, but pipeline wiring is the next task (process_video not called)
        self.assertEqual(r.status_code, 501)
        body = r.get_json()
        self.assertEqual(body["status"], "not_implemented")
        self.assertEqual(body["mode"], "blur")
        self.assertEqual(body["num_zones"], 0)

    def test_zone_create_and_delete(self):
        # video 100x80, drawn on a 50x40 canvas -> coords double
        uid = self._upload(_make_video_bytes(w=100, h=80), "clip.mp4").get_json()["id"]
        r = self.client.post("/zone", json={
            "id": uid,
            "rect": {"x": 5, "y": 10, "w": 20, "h": 15},
            "display": {"w": 50, "h": 40},
        })
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["video_rect"], [10, 20, 40, 30])  # doubled
        self.assertEqual(len(server._STATE[uid]["zones"]), 1)

        # add a second, then delete the first
        self.client.post("/zone", json={
            "id": uid,
            "rect": {"x": 0, "y": 0, "w": 10, "h": 10},
            "display": {"w": 50, "h": 40},
        })
        self.assertEqual(len(server._STATE[uid]["zones"]), 2)
        dr = self.client.post("/zone/delete", json={"id": uid, "index": 0})
        self.assertEqual(dr.status_code, 200)
        self.assertEqual(len(server._STATE[uid]["zones"]), 1)
        # the surviving zone is the one we added second
        self.assertEqual(server._STATE[uid]["zones"][0], [0, 0, 20, 20])

    def test_zone_stored_in_video_pixel_coords_for_zonemanager(self):
        # The stored zone must be usable directly by ZoneManager.add_zone().
        from core.zone_manager import ZoneManager

        uid = self._upload(_make_video_bytes(w=200, h=120), "clip.mp4").get_json()["id"]
        self.client.post("/zone", json={
            "id": uid,
            "rect": {"x": 10, "y": 10, "w": 30, "h": 20},
            "display": {"w": 100, "h": 60},  # half-size canvas -> coords double
        })
        stored = server._STATE[uid]["zones"][0]
        self.assertEqual(stored, [20, 20, 60, 40])
        # ZoneManager accepts it without complaint and applies it in-bounds
        zm = ZoneManager()
        idx = zm.add_zone(tuple(stored))
        self.assertEqual(idx, 0)
        frame = np.full((120, 200, 3), 255, np.uint8)
        zm.apply_zones(frame, mode="box")  # must not raise / go out of bounds

    def test_delete_invalid_index_rejected(self):
        uid = self._upload(_make_video_bytes(), "clip.mp4").get_json()["id"]
        r = self.client.post("/zone/delete", json={"id": uid, "index": 7})
        self.assertEqual(r.status_code, 400)

    def test_zone_zero_area_rejected(self):
        uid = self._upload(_make_video_bytes(w=100, h=80), "clip.mp4").get_json()["id"]
        r = self.client.post("/zone", json={
            "id": uid,
            "rect": {"x": 5, "y": 5, "w": 0, "h": 0},
            "display": {"w": 50, "h": 40},
        })
        self.assertEqual(r.status_code, 400)


class TestUploadWithSampleFixture(unittest.TestCase):
    """Use a real generated sample video when it is present (git-ignored)."""

    def setUp(self):
        server.app.config["TESTING"] = True
        self.client = server.app.test_client()
        server._STATE.clear()

    def tearDown(self):
        _clear_uploads()

    def test_upload_real_sample_zone_video(self):
        sample = os.path.join(SAMPLE_DIR, "test_zones.mp4")
        if not os.path.exists(sample):
            self.skipTest("sample video not generated (run tests/make_sample_videos.py)")
        with open(sample, "rb") as fh:
            data = fh.read()
        r = self.client.post(
            "/upload",
            data={"video": (io.BytesIO(data), "test_zones.mp4")},
            content_type="multipart/form-data",
        )
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        # fixtures are documented as 960x540
        self.assertEqual((body["width"], body["height"]), (960, 540))

        # The known static zone from Phase 2 validation, drawn on a half-size
        # canvas, must map back to (roughly) the documented video-pixel zone.
        uid = body["id"]
        zr = self.client.post("/zone", json={
            "id": uid,
            "rect": {"x": 10, "y": 35, "w": 130, "h": 215},
            "display": {"w": 480, "h": 270},
        })
        self.assertEqual(zr.get_json()["video_rect"], [20, 70, 260, 430])


if __name__ == "__main__":
    unittest.main()
