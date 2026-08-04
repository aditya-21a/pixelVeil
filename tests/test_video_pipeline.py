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
import subprocess
import tempfile
import unittest
from unittest import mock

import numpy as np
import cv2
import imageio_ffmpeg

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


def _ffmpeg():
    return imageio_ffmpeg.get_ffmpeg_exe()


def _write_video_with_audio(path, n_frames=6, w=160, h=120, fps=10.0):
    """Write a tiny mp4 that actually has an audio track.

    Uses the bundled ffmpeg to synthesize a silent color+tone clip so the input
    genuinely carries an audio stream (OpenCV's VideoWriter cannot). Duration is
    derived from n_frames/fps so it stays tiny.
    """
    duration = max(n_frames / fps, 0.2)
    args = [
        _ffmpeg(), "-y", "-nostdin", "-loglevel", "error",
        "-f", "lavfi", "-i", f"color=c=white:s={w}x{h}:r={fps}:d={duration}",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
        "-pix_fmt", "yuv420p", "-shortest", path,
    ]
    subprocess.run(args, check=True, capture_output=True, text=True)


def _has_audio_stream(path):
    """Return True if `path` contains at least one audio stream (via ffmpeg)."""
    # `ffmpeg -i` prints stream info to stderr; grep for an Audio stream line.
    result = subprocess.run(
        [_ffmpeg(), "-nostdin", "-i", path],
        capture_output=True, text=True,
    )
    return "Audio:" in result.stderr


def _frame_count(path):
    cap = cv2.VideoCapture(path)
    try:
        return int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    finally:
        cap.release()


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


class TestProcessVideoOcrSampling(unittest.TestCase):
    """OCR frame sampling (every Nth frame) + PII bbox persistence between
    samples. Components are mocked so the sampling/persistence control flow is
    isolated from real ML. Faces are mocked to [] except where face behavior is
    the thing under test, so blur_region calls in most cases come only from PII.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.inp = os.path.join(self.tmp, "in.mp4")
        self.out = os.path.join(self.tmp, "out.mp4")

    def _run(self, n_frames, **kwargs):
        _write_video(self.inp, n_frames=n_frames)
        return video_pipeline.process_video(self.inp, self.out, **kwargs)

    def test_sample_rate_1_runs_ocr_every_frame(self):
        with mock.patch.object(
            video_pipeline.face_detector, "detect_faces", return_value=[],
        ), mock.patch.object(
            video_pipeline.ocr_detector, "detect_text", return_value=[],
        ) as detect_text:
            self._run(4, mode="blur", ocr_sample_rate=1)
        # rate 1 == OCR on every frame (backwards-compatible default behavior).
        self.assertEqual(detect_text.call_count, 4)

    def test_sample_rate_n_runs_ocr_only_on_sampled_frames(self):
        # frames 0..(n-1); OCR fires on indices 0, N, 2N, ...
        for n_frames, rate, expected in [(7, 3, 3), (5, 2, 3), (5, 5, 1), (6, 3, 2)]:
            with self.subTest(n_frames=n_frames, rate=rate):
                with mock.patch.object(
                    video_pipeline.face_detector, "detect_faces", return_value=[],
                ), mock.patch.object(
                    video_pipeline.ocr_detector, "detect_text", return_value=[],
                ) as detect_text:
                    self._run(n_frames, mode="blur", ocr_sample_rate=rate)
                self.assertEqual(detect_text.call_count, expected)

    def test_pii_bbox_persists_between_samples_blur_mode(self):
        bbox = (5, 5, 80, 20)
        # 5 frames, rate 5 -> only frame 0 is sampled; the IP bbox must persist
        # to frames 1..4 without re-running OCR.
        with mock.patch.object(
            video_pipeline.face_detector, "detect_faces", return_value=[],
        ), mock.patch.object(
            video_pipeline.ocr_detector, "detect_text",
            return_value=[("192.168.1.5", bbox)],
        ) as detect_text, mock.patch.object(
            video_pipeline.redactor, "blur_region",
        ) as blur:
            summary = self._run(5, mode="blur", ocr_sample_rate=5)
        self.assertEqual(detect_text.call_count, 1)   # OCR ran once
        self.assertEqual(blur.call_count, 5)          # but blurred every frame
        # Every blur used the persisted bbox (faces mocked to [] -> PII only).
        for call in blur.call_args_list:
            self.assertEqual(call.args[1], bbox)
        self.assertEqual(summary["pii_by_type"]["IP"], 5)

    def test_persisted_pii_stops_when_next_sample_is_empty(self):
        bbox = (5, 5, 80, 20)
        # rate 2, 4 frames -> samples at 0 and 2. Frame 0 sees an IP; frame 2
        # sees nothing, so the persisted region must stop being applied.
        with mock.patch.object(
            video_pipeline.face_detector, "detect_faces", return_value=[],
        ), mock.patch.object(
            video_pipeline.ocr_detector, "detect_text",
            side_effect=[[("192.168.1.5", bbox)], []],
        ) as detect_text, mock.patch.object(
            video_pipeline.redactor, "blur_region",
        ) as blur:
            summary = self._run(4, mode="blur", ocr_sample_rate=2)
        self.assertEqual(detect_text.call_count, 2)   # sampled twice
        self.assertEqual(blur.call_count, 2)          # only frames 0,1 blurred
        self.assertEqual(summary["pii_by_type"]["IP"], 2)

    def test_persisted_pii_updates_when_next_sample_changes(self):
        bbox_a = (5, 5, 80, 20)
        bbox_b = (30, 30, 120, 20)
        # rate 2, 4 frames -> sample 0 = IP@bbox_a, sample 2 = CARD@bbox_b.
        with mock.patch.object(
            video_pipeline.face_detector, "detect_faces", return_value=[],
        ), mock.patch.object(
            video_pipeline.ocr_detector, "detect_text",
            side_effect=[
                [("192.168.1.5", bbox_a)],
                [("4111 1111 1111 1111", bbox_b)],
            ],
        ), mock.patch.object(
            video_pipeline.redactor, "blur_region",
        ) as blur:
            summary = self._run(4, mode="blur", ocr_sample_rate=2)
        boxes = [call.args[1] for call in blur.call_args_list]
        self.assertEqual(boxes, [bbox_a, bbox_a, bbox_b, bbox_b])
        self.assertEqual(summary["pii_by_type"]["IP"], 2)
        self.assertEqual(summary["pii_by_type"]["CARD"], 2)

    def test_fake_data_persists_generated_value_between_samples(self):
        bbox = (5, 5, 100, 20)
        # rate 3, 3 frames -> only frame 0 sampled. The fake value must be
        # generated ONCE and reused (no per-frame regeneration -> no flicker).
        with mock.patch.object(
            video_pipeline.face_detector, "detect_faces", return_value=[],
        ), mock.patch.object(
            video_pipeline.ocr_detector, "detect_text",
            return_value=[("john.doe@example.com", bbox)],
        ), mock.patch.object(
            video_pipeline.fake_data, "generate", return_value="a.b@example.com",
        ) as gen, mock.patch.object(
            video_pipeline.redactor, "fake_data_region",
        ) as fake:
            summary = self._run(3, mode="fake_data", ocr_sample_rate=3)
        gen.assert_called_once_with("EMAIL")          # generated once
        self.assertEqual(fake.call_count, 3)          # drawn every frame
        for call in fake.call_args_list:              # same persisted string
            self.assertEqual(call.args[1], bbox)
            self.assertEqual(call.args[2], "a.b@example.com")
        self.assertEqual(summary["pii_by_type"]["EMAIL"], 3)

    def test_faces_detected_every_frame_regardless_of_sampling(self):
        with mock.patch.object(
            video_pipeline.face_detector, "detect_faces",
            return_value=[(10, 10, 20, 20)],
        ) as detect_faces, mock.patch.object(
            video_pipeline.ocr_detector, "detect_text", return_value=[],
        ) as detect_text, mock.patch.object(
            video_pipeline.redactor, "blur_region",
        ) as blur:
            summary = self._run(6, mode="blur", ocr_sample_rate=3)
        self.assertEqual(detect_faces.call_count, 6)  # face detect every frame
        self.assertEqual(detect_text.call_count, 2)   # OCR only on 0,3
        self.assertEqual(blur.call_count, 6)          # 1 face blurred per frame
        self.assertEqual(summary["faces_blurred"], 6)

    def test_zones_applied_every_frame_regardless_of_sampling(self):
        with mock.patch.object(
            video_pipeline.face_detector, "detect_faces", return_value=[],
        ), mock.patch.object(
            video_pipeline.ocr_detector, "detect_text", return_value=[],
        ), mock.patch.object(
            video_pipeline.ZoneManager, "apply_zones",
        ) as apply_zones:
            summary = self._run(
                6, mode="blur", zones=[(0, 0, 10, 10)], ocr_sample_rate=3,
            )
        self.assertEqual(apply_zones.call_count, 6)   # every frame
        self.assertEqual(summary["zones_applied"], 6)

    def test_summary_and_progress_reflect_persistence(self):
        bbox = (5, 5, 80, 20)
        events = []
        # rate 2, 4 frames -> sample 0 = IP, sample 2 = empty.
        with mock.patch.object(
            video_pipeline.face_detector, "detect_faces", return_value=[],
        ), mock.patch.object(
            video_pipeline.ocr_detector, "detect_text",
            side_effect=[[("192.168.1.5", bbox)], []],
        ), mock.patch.object(
            video_pipeline.redactor, "blur_region",
        ):
            summary = self._run(
                4, mode="blur", ocr_sample_rate=2,
                progress_callback=events.append,
            )
        # One event per frame, 1-based frame numbers, keys preserved.
        self.assertEqual(len(events), 4)
        self.assertEqual([e["frame"] for e in events], [1, 2, 3, 4])
        # pii count tracks the persisted region: present on 0,1; gone on 2,3.
        self.assertEqual([e["pii"] for e in events], [1, 1, 0, 0])
        self.assertEqual(summary["frames_processed"], 4)
        self.assertEqual(summary["pii_by_type"]["IP"], 2)

    def test_invalid_sample_rate_raises_and_no_output(self):
        _write_video(self.inp, n_frames=1)
        for bad in [0, -1, -5, 2.5, "3", None, True, False]:
            with self.subTest(rate=bad):
                with self.assertRaises(ValueError):
                    video_pipeline.process_video(
                        self.inp, self.out, mode="blur", ocr_sample_rate=bad,
                    )
                self.assertFalse(os.path.exists(self.out))


class TestProcessVideoAudioMux(unittest.TestCase):
    """OpenCV intermediate -> ffmpeg audio mux (D8). Real ffmpeg is used (the
    bundled imageio-ffmpeg binary) for the audio/no-audio round trips; the
    failure path and cleanup are checked with mocks so no bad ffmpeg call is
    actually spawned."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.inp = os.path.join(self.tmp, "in.mp4")
        self.out = os.path.join(self.tmp, "out.mp4")
        # Faces/OCR mocked off so these tests isolate the output/mux stage.
        self._patchers = [
            mock.patch.object(
                video_pipeline.face_detector, "detect_faces", return_value=[]
            ),
            mock.patch.object(
                video_pipeline.ocr_detector, "detect_text", return_value=[]
            ),
        ]
        for p in self._patchers:
            p.start()

    def tearDown(self):
        for p in self._patchers:
            p.stop()

    def _leftover_temps(self):
        return [f for f in os.listdir(self.tmp) if f.startswith("pixelveil_")]

    def test_source_with_audio_output_has_audio(self):
        _write_video_with_audio(self.inp, n_frames=6)
        self.assertTrue(_has_audio_stream(self.inp), "fixture should have audio")
        summary = video_pipeline.process_video(self.inp, self.out, mode="blur")
        self.assertEqual(summary["frames_processed"], 6)
        self.assertTrue(os.path.exists(self.out))
        # Original audio must be carried into the final output.
        self.assertTrue(_has_audio_stream(self.out))

    def test_source_without_audio_produces_valid_output(self):
        _write_video(self.inp, n_frames=4)  # OpenCV writer => no audio track
        self.assertFalse(_has_audio_stream(self.inp))
        summary = video_pipeline.process_video(self.inp, self.out, mode="blur")
        self.assertEqual(summary["frames_processed"], 4)
        self.assertTrue(os.path.exists(self.out))
        # Output is video-only but valid + playable (readable frame count).
        self.assertFalse(_has_audio_stream(self.out))
        self.assertEqual(_frame_count(self.out), 4)

    def test_processed_video_stream_intact(self):
        # Dimensions/FPS and frame count survive the OpenCV write + ffmpeg copy.
        _write_video_with_audio(self.inp, n_frames=6, w=160, h=120, fps=10.0)
        video_pipeline.process_video(self.inp, self.out, mode="blur")
        cap = cv2.VideoCapture(self.out)
        try:
            self.assertEqual(int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), 160)
            self.assertEqual(int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)), 120)
            self.assertGreaterEqual(int(cap.get(cv2.CAP_PROP_FRAME_COUNT)), 5)
        finally:
            cap.release()

    def test_temp_intermediate_cleaned_up_on_success(self):
        _write_video(self.inp, n_frames=3)
        video_pipeline.process_video(self.inp, self.out, mode="blur")
        self.assertEqual(self._leftover_temps(), [])

    def test_ffmpeg_failure_raises_and_cleans_up(self):
        _write_video(self.inp, n_frames=3)
        # Simulate ffmpeg exiting non-zero; the pipeline must surface it and
        # still delete the intermediate it created.
        fake_proc = mock.Mock(returncode=1, stderr="boom: bad codec")
        with mock.patch.object(
            video_pipeline.subprocess, "run", return_value=fake_proc
        ) as run:
            with self.assertRaises(RuntimeError) as ctx:
                video_pipeline.process_video(self.inp, self.out, mode="blur")
        self.assertTrue(run.called)
        self.assertIn("ffmpeg", str(ctx.exception).lower())
        self.assertEqual(self._leftover_temps(), [])  # no temp left behind

    def test_intermediate_cleaned_up_on_processing_error(self):
        _write_video(self.inp, n_frames=3)
        # Blow up mid-processing (after the intermediate file is created) and
        # confirm the finally-block still removes it.
        with mock.patch.object(
            video_pipeline.redactor, "blur_region",
            side_effect=RuntimeError("kaboom"),
        ):
            with mock.patch.object(
                video_pipeline.face_detector, "detect_faces",
                return_value=[(1, 1, 5, 5)],
            ):
                with self.assertRaises(RuntimeError):
                    video_pipeline.process_video(self.inp, self.out, mode="blur")
        self.assertEqual(self._leftover_temps(), [])

    def test_mux_called_with_safe_arg_list_not_shell(self):
        # process_video must pass ffmpeg a list (never a shell string) and must
        # not use shell=True.
        _write_video(self.inp, n_frames=2)
        real_run = video_pipeline.subprocess.run
        captured = {}

        def spy(args, *a, **kw):
            captured["args"] = args
            captured["kwargs"] = kw
            return real_run(args, *a, **kw)

        with mock.patch.object(video_pipeline.subprocess, "run", side_effect=spy):
            video_pipeline.process_video(self.inp, self.out, mode="blur")
        self.assertIsInstance(captured["args"], list)
        self.assertNotIn("shell", captured["kwargs"])  # no shell=True
        # Copies streams (no re-encode) and maps optional audio.
        self.assertIn("copy", captured["args"])
        self.assertIn("1:a:0?", captured["args"])


if __name__ == "__main__":
    unittest.main()
