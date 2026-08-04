"""Phase 2 end-to-end validation harness (TESTING.md sections 3-5).

Run:  python tests/phase2_validate.py

Runs the REAL core.video_pipeline.process_video() (no mocked detectors or
redactors) against the five fixtures in tests/sample_videos/, then inspects the
OUTPUT videos to measure what actually survived redaction:

  * faces   - residual detectable faces + blur strength inside the face region
  * PII     - whether each planted PII string is still OCR-readable in the output
  * zones   - zone interior blurred AND adjacent content NOT covered
  * mixed   - moving ticker behavior under OCR sampling (ISSUE-003)
  * integrity - frame count / resolution / fps preserved, audio present

This is a reporting artifact, not a pytest test (OCR over every output frame is
slow); it prints an honest per-video report and records every miss. It does not
change any threshold, sample-rate default, detector, regex, or core code.
"""

import os
import shutil
import sys
import tempfile

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import face_detector, ocr_detector, video_pipeline
import imageio_ffmpeg
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLES = os.path.join(HERE, "sample_videos")

EMAIL = "john.doe@example.com"
PHONE = "9876543210"
IP = "192.168.1.105"
CARD = "4111 1111 1111 1111"
ZONE = (20, 70, 260, 430)


# --- helpers -----------------------------------------------------------------
def _iter_frames(path):
    cap = cv2.VideoCapture(path)
    try:
        while True:
            ok, fr = cap.read()
            if not ok:
                break
            yield fr
    finally:
        cap.release()


def _first_frame(path):
    """Read frame 0 and fully release the capture (Windows keeps the file locked
    otherwise, which blocks temp-dir cleanup)."""
    cap = cv2.VideoCapture(path)
    try:
        ok, fr = cap.read()
        return fr if ok else None
    finally:
        cap.release()


def _meta(path):
    cap = cv2.VideoCapture(path)
    ok = cap.isOpened()
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = round(cap.get(cv2.CAP_PROP_FPS), 2)
    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    return {"openable": ok, "w": w, "h": h, "fps": fps, "frames": frames,
            "dur_s": round(frames / fps, 2) if fps else 0.0}


def _has_audio(path):
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    r = subprocess.run([ff, "-hide_banner", "-i", path],
                       capture_output=True, text=True)
    return "Audio:" in r.stderr


def _lap_var(region):
    if region.size == 0:
        return 0.0
    g = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(g, cv2.CV_64F).var())


def _ocr_joined(frame):
    dets = ocr_detector.detect_text(frame)
    return " ".join(t for t, _ in dets)


def _contains_pii(text, value):
    """Substring test tolerant to OCR spacing for numeric PII."""
    t = text.lower()
    v = value.lower()
    if v in t:
        return True
    # digit-only comparison for phone/card (OCR may regroup spaces)
    digits_v = "".join(c for c in v if c.isdigit())
    if len(digits_v) >= 7:
        digits_t = "".join(c for c in t if c.isdigit())
        return digits_v in digits_t
    return False


def _run(video, mode, ocr_sample_rate=1, zones=None):
    src = os.path.join(SAMPLES, video)
    out_dir = tempfile.mkdtemp(prefix="pv_phase2_")
    out = os.path.join(out_dir, f"{os.path.splitext(video)[0]}_{mode}_r{ocr_sample_rate}.mp4")
    summary = video_pipeline.process_video(
        src, out, mode=mode, zones=zones, ocr_sample_rate=ocr_sample_rate)
    return src, out, out_dir, summary


def _cleanup(out, out_dir):
    shutil.rmtree(out_dir, ignore_errors=True)


def _pii_survival(out_path, values, every=1):
    """Return {value: (frames_readable, frames_checked)} by OCR-ing the output."""
    counts = {v: 0 for v in values}
    checked = 0
    for i, fr in enumerate(_iter_frames(out_path)):
        if i % every != 0:
            continue
        checked += 1
        text = _ocr_joined(fr)
        for v in values:
            if _contains_pii(text, v):
                counts[v] += 1
    return {v: (counts[v], checked) for v in values}


def _face_residual(src_path, out_path):
    """Per-frame residual face detections on output + blur check in face region."""
    # face bbox from the source (static face in these fixtures)
    src0 = _first_frame(src_path)
    src_boxes = face_detector.detect_faces(src0)
    out_frames = list(_iter_frames(out_path))
    residual = sum(len(face_detector.detect_faces(f)) for f in out_frames)
    blur = None
    if src_boxes:
        x, y, w, h = src_boxes[0]
        vin = _lap_var(src0[y:y + h, x:x + w])
        vout = _lap_var(out_frames[0][y:y + h, x:x + w])
        blur = (round(vin, 1), round(vout, 1))
    return len(src_boxes), residual, len(out_frames), blur


def _zone_check(src_path, out_path, zone):
    x, y, w, h = zone
    src0 = _first_frame(src_path)
    out0 = _first_frame(out_path)
    interior_in = _lap_var(src0[y:y + h, x:x + w])
    interior_out = _lap_var(out0[y:y + h, x:x + w])
    # adjacent strip just to the RIGHT of the zone, same rows
    ax0, ax1 = x + w + 5, x + w + 45
    adj_in = _lap_var(src0[y:y + h, ax0:ax1])
    adj_out = _lap_var(out0[y:y + h, ax0:ax1])
    return {
        "interior": (round(interior_in, 1), round(interior_out, 1)),
        "adjacent": (round(adj_in, 1), round(adj_out, 1)),
    }


def line(s=""):
    print(s)


# --- per-fixture validations -------------------------------------------------
def validate_faces(video, expected):
    line(f"\n=== {video} — faces (blur mode) ===")
    src, out, out_dir, summ = _run(video, "blur")
    detected, residual, nframes, blur = _face_residual(src, out)
    line(f"  source faces (1st frame): {detected}  (expected {expected})")
    line(f"  pipeline faces_blurred total: {summ['faces_blurred']} over {summ['frames_processed']} frames")
    line(f"  residual detectable faces in OUTPUT (all frames): {residual}")
    if blur:
        line(f"  face-region Laplacian var  in={blur[0]}  out={blur[1]}  "
             f"(lower out => blurred)")
    m = _meta(out)
    line(f"  output integrity: {m['w']}x{m['h']} {m['fps']}fps {m['frames']}f "
         f"{m['dur_s']}s audio={_has_audio(out)}")
    _cleanup(out, out_dir)
    return {"video": video, "expected": expected, "detected": detected,
            "residual": residual, "blur": blur, "meta": m}


def validate_pii(video, mode, values, ocr_sample_rate=1):
    line(f"\n=== {video} — PII ({mode} mode, ocr_sample_rate={ocr_sample_rate}) ===")
    src, out, out_dir, summ = _run(video, mode, ocr_sample_rate=ocr_sample_rate)
    line(f"  pipeline pii_by_type: {dict(summ['pii_by_type'])}")
    surv = _pii_survival(out, values, every=1)
    for v in values:
        r, c = surv[v]
        flag = "  <-- STILL READABLE" if r > 0 else ""
        line(f"  {v:24} readable in {r}/{c} output frames{flag}")
    m = _meta(out)
    line(f"  output integrity: {m['w']}x{m['h']} {m['fps']}fps {m['frames']}f "
         f"{m['dur_s']}s audio={_has_audio(out)}")
    _cleanup(out, out_dir)
    return {"video": video, "mode": mode, "rate": ocr_sample_rate,
            "survival": surv, "meta": m, "summary": dict(summ["pii_by_type"])}


def validate_mixed(video, values):
    line(f"\n=== {video} — mixed + ISSUE-003 (moving ticker) ===")
    results = {}
    for rate in (1, 5):
        src, out, out_dir, summ = _run(video, "blur", ocr_sample_rate=rate)
        _, residual, nframes, blur = _face_residual(src, out)
        surv = _pii_survival(out, values, every=1)
        line(f"  -- ocr_sample_rate={rate} --")
        line(f"     faces_blurred={summ['faces_blurred']} residual_faces={residual} "
             f"face_blur(in,out)={blur}")
        line(f"     pii_by_type={dict(summ['pii_by_type'])}")
        for v in values:
            r, c = surv[v]
            kind = "STATIC" if v in (EMAIL, PHONE) else "MOVING"
            flag = "  <-- STILL READABLE" if r > 0 else ""
            line(f"     [{kind}] {v:24} readable in {r}/{c} frames{flag}")
        results[rate] = {"summary": dict(summ["pii_by_type"]), "survival": surv,
                         "residual_faces": residual}
        _cleanup(out, out_dir)
    return results


def validate_zones(video, zone):
    line(f"\n=== {video} — static zone {zone} ===")
    src, out, out_dir, summ = _run(video, "blur", zones=[zone])
    line(f"  pipeline zones_applied={summ['zones_applied']} over {summ['frames_processed']} frames")
    z = _zone_check(src, out, zone)
    line(f"  zone interior Laplacian var in={z['interior'][0]} out={z['interior'][1]} "
         f"(lower out => zone blurred)")
    line(f"  adjacent strip     Laplacian var in={z['adjacent'][0]} out={z['adjacent'][1]} "
         f"(similar => adjacent NOT covered)")
    # per-frame: zone applied on every frame?
    applied_every = summ["zones_applied"] == summ["frames_processed"]
    line(f"  zone applied on EVERY frame: {applied_every}")
    m = _meta(out)
    line(f"  output integrity: {m['w']}x{m['h']} {m['fps']}fps {m['frames']}f {m['dur_s']}s")
    _cleanup(out, out_dir)
    return {"zone": z, "applied_every": applied_every, "meta": m}


def main():
    line("PHASE 2 END-TO-END VALIDATION (real process_video, no mocks)")
    line("=" * 64)
    # source metadata
    for v in ["test_faces_basic.mp4", "test_faces_multi.mp4", "test_pii_text.mp4",
              "test_mixed.mp4", "test_zones.mp4"]:
        m = _meta(os.path.join(SAMPLES, v))
        line(f"  src {v:24} {m['w']}x{m['h']} {m['fps']}fps {m['frames']}f "
             f"{m['dur_s']}s audio={_has_audio(os.path.join(SAMPLES, v))}")

    validate_faces("test_faces_basic.mp4", expected=1)
    validate_faces("test_faces_multi.mp4", expected=3)

    validate_pii("test_pii_text.mp4", "blur", [EMAIL, PHONE, IP, CARD])
    validate_pii("test_pii_text.mp4", "fake_data", [EMAIL, PHONE, IP, CARD])

    validate_mixed("test_mixed.mp4", [EMAIL, PHONE, CARD, IP])

    validate_zones("test_zones.mp4", ZONE)

    line("\nDONE.")


if __name__ == "__main__":
    main()
