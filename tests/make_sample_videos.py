"""Generate deterministic Phase 2 test fixtures under tests/sample_videos/.

Run:  python tests/make_sample_videos.py

Produces five short, fully deterministic MP4 fixtures (no randomness, no
network, no downloads) for TESTING.md section 2:

  test_faces_basic.mp4  - one clear frontal face (tests/assets/single_frontal_face.jpg)
  test_faces_multi.mp4  - multiple visible faces (tests/assets/multiple_faces.jpg)
  test_pii_text.mp4     - mock dashboard with planted PII + audio track
  test_mixed.mp4        - face + static PII + scrolling PII (ISSUE-003) + audio track
  test_zones.mp4        - mock app with one static panel at fixed pixel coords

Video frames are drawn with OpenCV. Audio (a deterministic sine tone) is added
only to the two fixtures that need it, muxed in with the existing imageio-ffmpeg
dependency. All planted PII uses reserved/documentation values — nothing real.

These MP4s are intentionally git-ignored (tests/sample_videos/*.mp4); regenerate
them with this script rather than committing the binaries.
"""

import os
import subprocess
import tempfile

import cv2
import numpy as np
import imageio_ffmpeg

# --- fixed parameters (deterministic; modest size) ---------------------------
W, H = 960, 540          # 16:9, legible for OCR, faces stay a usable size
FPS = 10
SECONDS = 6
N_FRAMES = FPS * SECONDS  # 60

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")
OUT = os.path.join(HERE, "sample_videos")

# Planted PII (reserved / documentation values only — NOT real data).
PII_EMAIL = "john.doe@example.com"
PII_PHONE = "9876543210"
PII_IP = "192.168.1.105"
PII_CARD = "4111 1111 1111 1111"

FONT = cv2.FONT_HERSHEY_SIMPLEX


# --- small drawing / IO helpers ----------------------------------------------
def _fit_into(dst, img, x, y, w, h):
    """Resize img preserving aspect ratio and paste centered into dst[y:y+h, x:x+w]."""
    ih, iw = img.shape[:2]
    scale = min(w / iw, h / ih)
    nw, nh = max(1, int(iw * scale)), max(1, int(ih * scale))
    resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
    ox = x + (w - nw) // 2
    oy = y + (h - nh) // 2
    dst[oy:oy + nh, ox:ox + nw] = resized


def _load_asset(name):
    path = os.path.join(ASSETS, name)
    img = cv2.imread(path)
    if img is None:
        raise FileNotFoundError(f"required asset missing: {path}")
    return img


def _text(frame, s, org, scale=0.8, color=(20, 20, 20), thick=2):
    cv2.putText(frame, s, org, FONT, scale, color, thick, cv2.LINE_AA)


def _write_video(path, frame_fn, n=N_FRAMES, fps=FPS, size=(W, H)):
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    vw = cv2.VideoWriter(path, fourcc, fps, size)
    if not vw.isOpened():
        raise RuntimeError(f"could not open VideoWriter for {path!r}")
    try:
        for i in range(n):
            vw.write(frame_fn(i))
    finally:
        vw.release()


def _add_sine_audio(video_path, freq=440, n=N_FRAMES, fps=FPS):
    """Mux a deterministic sine tone into video_path in place (video copied, audio AAC)."""
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    duration = n / fps
    fd, tmp = tempfile.mkstemp(prefix="pixelveil_fixaudio_", suffix=".mp4", dir=OUT)
    os.close(fd)
    args = [
        ffmpeg, "-y", "-nostdin", "-loglevel", "error",
        "-i", video_path,
        "-f", "lavfi", "-t", f"{duration}",
        "-i", f"sine=frequency={freq}:sample_rate=44100",
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy", "-c:a", "aac", "-shortest",
        tmp,
    ]
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise RuntimeError(f"ffmpeg audio mux failed: {result.stderr.strip()}")
    os.replace(tmp, video_path)


# --- reusable mock-UI backgrounds --------------------------------------------
def _dashboard_bg():
    """Light 'admin dashboard' chrome shared by the PII fixture (static)."""
    f = np.full((H, W, 3), 240, np.uint8)
    cv2.rectangle(f, (0, 0), (W, 56), (90, 60, 40), -1)          # top bar
    _text(f, "Acme Admin  -  Customer Record", (20, 38), 0.9, (255, 255, 255), 2)
    cv2.rectangle(f, (40, 90), (W - 40, H - 40), (255, 255, 255), -1)  # card panel
    cv2.rectangle(f, (40, 90), (W - 40, H - 40), (200, 200, 200), 2)
    return f


def _pii_dashboard_frame(_i):
    f = _dashboard_bg()
    rows = [
        ("Name:", "John Doe"),
        ("Email:", PII_EMAIL),
        ("Phone:", PII_PHONE),
        ("IP Address:", PII_IP),
        ("Card:", PII_CARD),
    ]
    y = 150
    for label, value in rows:
        _text(f, label, (70, y), 0.8, (110, 110, 110), 2)
        _text(f, value, (320, y), 0.8, (20, 20, 20), 2)
        y += 62
    return f


def _mixed_frame(face_img):
    def frame_fn(i):
        f = np.full((H, W, 3), 235, np.uint8)
        cv2.rectangle(f, (0, 0), (W, 46), (70, 70, 70), -1)
        _text(f, "Support Session Recording", (16, 32), 0.8, (255, 255, 255), 2)
        # left: a real face (static)
        _fit_into(f, face_img, 20, 70, 380, 300)
        _text(f, "Caller", (20, 400), 0.7, (40, 40, 40), 2)
        # right: static PII panel
        cv2.rectangle(f, (430, 70), (W - 20, 300), (255, 255, 255), -1)
        cv2.rectangle(f, (430, 70), (W - 20, 300), (190, 190, 190), 2)
        _text(f, "Email: " + PII_EMAIL, (450, 120), 0.7, (20, 20, 20), 2)
        _text(f, "Phone: " + PII_PHONE, (450, 170), 0.7, (20, 20, 20), 2)
        # bottom: scrolling PII ticker (moves each frame -> ISSUE-003)
        ticker = f"CARD {PII_CARD}    IP {PII_IP}    "
        (tw, _), _ = cv2.getTextSize(ticker, FONT, 0.9, 2)
        speed = 12
        x = W - (i * speed) % (W + tw)
        cv2.rectangle(f, (0, H - 60), (W, H), (30, 30, 30), -1)
        _text(f, ticker, (x, H - 20), 0.9, (0, 230, 120), 2)
        return f
    return frame_fn


def _zones_frame(i):
    """Mock app whose left sidebar panel is fixed at identical pixel coords every frame."""
    f = np.full((H, W, 3), 245, np.uint8)
    cv2.rectangle(f, (0, 0), (W, 46), (60, 90, 120), -1)
    _text(f, "CRM Workspace", (16, 32), 0.8, (255, 255, 255), 2)

    # STATIC ZONE: same rectangle every frame (coords never depend on i).
    ZX, ZY, ZW, ZH = 20, 70, 260, 430
    cv2.rectangle(f, (ZX, ZY), (ZX + ZW, ZY + ZH), (210, 225, 235), -1)
    cv2.rectangle(f, (ZX, ZY), (ZX + ZW, ZY + ZH), (150, 170, 185), 2)
    _text(f, "CRM SIDEBAR", (ZX + 16, ZY + 40), 0.7, (30, 30, 30), 2)
    _text(f, "(static zone)", (ZX + 16, ZY + 74), 0.6, (90, 90, 90), 2)

    # Moving content OUTSIDE the zone, to prove the panel stays put while the
    # rest of the frame changes over time.
    _text(f, f"Ticket #{1000 + i}", (320, 140), 0.9, (20, 20, 20), 2)
    cx = 320 + (i * 9) % 560
    cv2.circle(f, (cx, 300), 26, (0, 140, 220), -1)
    return f


# --- build one fixture at a time ---------------------------------------------
def _build_static_image_video(path, asset_name):
    img = _load_asset(asset_name)
    frame = np.zeros((H, W, 3), np.uint8)
    _fit_into(frame, img, 0, 0, W, H)
    _write_video(path, lambda _i: frame.copy())


def build_all():
    os.makedirs(OUT, exist_ok=True)

    p_basic = os.path.join(OUT, "test_faces_basic.mp4")
    _build_static_image_video(p_basic, "single_frontal_face.jpg")

    p_multi = os.path.join(OUT, "test_faces_multi.mp4")
    _build_static_image_video(p_multi, "multiple_faces.jpg")

    p_pii = os.path.join(OUT, "test_pii_text.mp4")
    _write_video(p_pii, _pii_dashboard_frame)
    _add_sine_audio(p_pii, freq=440)

    p_mixed = os.path.join(OUT, "test_mixed.mp4")
    face = _load_asset("single_frontal_face.jpg")
    _write_video(p_mixed, _mixed_frame(face))
    _add_sine_audio(p_mixed, freq=330)

    p_zones = os.path.join(OUT, "test_zones.mp4")
    _write_video(p_zones, _zones_frame)

    return [p_basic, p_multi, p_pii, p_mixed, p_zones]


# --- verification / reporting ------------------------------------------------
def _has_audio(path):
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", path],
        capture_output=True, text=True,
    )
    return "Audio:" in result.stderr


def probe(path):
    cap = cv2.VideoCapture(path)
    ok = cap.isOpened()
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    duration = frames / fps if fps else 0.0
    return {
        "openable": ok,
        "resolution": f"{w}x{h}",
        "fps": round(fps, 2),
        "frames": frames,
        "duration_s": round(duration, 2),
        "size_kb": round(os.path.getsize(path) / 1024, 1),
        "audio": _has_audio(path),
    }


def main():
    paths = build_all()
    print(f"{'file':28} {'res':>9} {'fps':>5} {'frames':>7} "
          f"{'dur(s)':>7} {'size(KB)':>9} {'audio':>6}")
    for p in paths:
        m = probe(p)
        print(f"{os.path.basename(p):28} {m['resolution']:>9} {m['fps']:>5} "
              f"{m['frames']:>7} {m['duration_s']:>7} {m['size_kb']:>9} "
              f"{'yes' if m['audio'] else 'no':>6}")


if __name__ == "__main__":
    main()
