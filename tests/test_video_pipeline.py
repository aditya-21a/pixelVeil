"""
Focused tests for core/video_pipeline.py — orchestration only.

Two styles are used:
  * End-to-end round trips on tiny synthetic videos written with OpenCV, to
    confirm frames are read, processed, and written and that resources are
    released (invalid-input path included).
  * Mock-based wiring tests that patch the component modules, to confirm the
    pipeline calls each existing public API in the documented order and routes
    fake-data mode through fake_data.generate() -> redactor.fake_data_region()
    without duplicating any component logic.

No large video fixtures — inputs are generated at test time.
"""

import os
import tempfile
import unittest
from unittest import mock

import numpy as np
import cv2

from core import video_pipeline


def _write_video(path, n_frames=4, w=320, h=240, fps=10.0, frame_factory=None):
    """Write a tiny mp4 with `n_frames`. frame_factory(i) may supply a frame."""
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(path, fourcc, fps, (w, h))
    assert writer.isOpened(), "could not open test VideoWriter"
    for i in range(n_frames):
        if frame_factory is not None:
            frame = frame_factory(i)
        else:
            frame = np.full((h, w, 3), 255, np.uint8)
        writer.write(frame)
    writer.release()


class TestProcessVideoRoundTrip(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.inp = os.path.join(self.tmp, "in.mp4")
        self.out = os.path.join(self.tmp, "out.mp4")

    def test_produces_output_with_same_frame_count(self):
        _write_video(self.inp, n_frames=4)
        summary = video_pipeline.process_video(self.inp, self.out, mode="blur")
        self.assertEqual(summary["frames_processed"], 4)
        self.assertTrue(os.path.exists(self.out))
        cap = cv2.VideoCapture(self.out)
        try:
            self.assertEqual(int(cap.get(cv2.CAP_PROP_FRAME_COUNT)), 4)
        finally:
            cap.release()

    def test_preserves_dimensions_and_fps(self):
        _write_video(self.inp, n_frames=3, w=320, h=240, fps=15.0)
        video_pipeline.process_video(self.inp, self.out, mode="blur")
        cap = cv2.VideoCapture(self.out)
        try:
            self.assertEqual(int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), 320)
            self.assertEqual(int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)), 240)
            self.assertAlmostEqual(cap.get(cv2.CAP_PROP_FPS), 15.0, places=1)
        finally:
            cap.release()

    def test_invalid_input_raises_and_no_output(self):
        missing = os.path.join(self.tmp, "does_not_exist.mp4")
        with self.assertRaises(ValueError):
            video_pipeline.process_video(missing, self.out, mode="blur")
        self.assertFalse(os.path.exists(self.out))

    def test_invalid_mode_raises(self):
        _write_video(self.inp, n_frames=1)
        with self.assertRaises(ValueError):
            video_pipeline.process_video(self.inp, self.out, mode="nope")

    def test_progress_callback_invoked_per_frame(self):
        _write_video(self.inp, n_frames=3)
        events = []
        video_pipeline.process_video(
            self.inp, self.out, mode="blur", progress_callback=events.append
        )
        self.assertEqual(len(events), 3)
        self.assertEqual(events[-1]["frame"], 3)
        self.assertIn("faces", events[-1])
        self.assertIn("pii", events[-1])


class TestProcessVideoOrchestration(unittest.TestCase):
    """Patch the components to assert wiring/order without real ML."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.inp = os.path.join(self.tmp, "in.mp4")
        self.out = os.path.join(self.tmp, "out.mp4")
        _write_video(self.inp, n_frames=2)

    def test_faces_always_blurred_even_in_fake_data_mode(self):
        with mock.patch.object(
            video_pipeline.face_detector, "detect_faces",
            return_value=[(10, 10, 20, 20)],
        ), mock.patch.object(
            video_pipeline.ocr_detector, "detect_text", return_value=[],
        ), mock.patch.object(
            video_pipeline.redactor, "blur_region"
        ) as blur, mock.patch.object(
            video_pipeline.redactor, "fake_data_region"
        ) as fake:
            summary = video_pipeline.process_video(
                self.inp, self.out, mode="fake_data"
            )
        # Face box blurred on every frame; never sent to fake-data.
        self.assertEqual(blur.call_count, 2)  # 2 frames, 1 face each
        self.assertEqual(fake.call_count, 0)
        self.assertEqual(summary["faces_blurred"], 2)

    def test_fake_data_mode_routes_through_generate(self):
        with mock.patch.object(
            video_pipeline.face_detector, "detect_faces", return_value=[],
        ), mock.patch.object(
            video_pipeline.ocr_detector, "detect_text",
            return_value=[("john.doe@example.com", (5, 5, 100, 20))],
        ), mock.patch.object(
            video_pipeline.fake_data, "generate", return_value="a.b@example.com",
        ) as gen, mock.patch.object(
            video_pipeline.redactor, "fake_data_region",
        ) as fake:
            video_pipeline.process_video(self.inp, self.out, mode="fake_data")
        # EMAIL classified -> generate("EMAIL") -> fake_data_region(text=...).
        gen.assert_called_with("EMAIL")
        self.assertEqual(fake.call_count, 2)  # once per frame
        # The generated string is what gets passed to the renderer.
        _args, kwargs = fake.call_args
        passed = kwargs.get("text", fake.call_args[0][2] if len(fake.call_args[0]) > 2 else None)
        self.assertEqual(passed, "a.b@example.com")

    def test_blur_mode_blurs_pii_not_fake_data(self):
        with mock.patch.object(
            video_pipeline.face_detector, "detect_faces", return_value=[],
        ), mock.patch.object(
            video_pipeline.ocr_detector, "detect_text",
            return_value=[("192.168.1.5", (5, 5, 80, 20))],
        ), mock.patch.object(
            video_pipeline.redactor, "blur_region",
        ) as blur, mock.patch.object(
            video_pipeline.redactor, "fake_data_region",
        ) as fake:
            summary = video_pipeline.process_video(self.inp, self.out, mode="blur")
        self.assertEqual(fake.call_count, 0)
        self.assertEqual(blur.call_count, 2)  # IP blurred once per frame
        self.assertEqual(summary["pii_by_type"]["IP"], 2)

    def test_non_pii_text_not_redacted(self):
        with mock.patch.object(
            video_pipeline.face_detector, "detect_faces", return_value=[],
        ), mock.patch.object(
            video_pipeline.ocr_detector, "detect_text",
            return_value=[("Dashboard", (5, 5, 80, 20))],
        ), mock.patch.object(
            video_pipeline.redactor, "blur_region",
        ) as blur:
            summary = video_pipeline.process_video(self.inp, self.out, mode="blur")
        self.assertEqual(blur.call_count, 0)
        self.assertEqual(sum(summary["pii_by_type"].values()), 0)

    def test_static_zones_applied_every_frame(self):
        with mock.patch.object(
            video_pipeline.face_detector, "detect_faces", return_value=[],
        ), mock.patch.object(
            video_pipeline.ocr_detector, "detect_text", return_value=[],
        ), mock.patch.object(
            video_pipeline.ZoneManager, "apply_zones",
        ) as apply_zones:
            summary = video_pipeline.process_video(
                self.inp, self.out, mode="blur", zones=[(0, 0, 10, 10)],
            )
        self.assertEqual(apply_zones.call_count, 2)  # once per frame
        self.assertEqual(summary["zones_applied"], 2)  # 1 zone x 2 frames


if __name__ == "__main__":
    unittest.main()
