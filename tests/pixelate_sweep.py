import os
import sys
import cv2
import numpy as np

# ---------------------------------------------------------------------------
# Make the repo root importable so core.* works when run from any directory.
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT  = os.path.dirname(SCRIPT_DIR)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from core import face_detector
from core.redactor import _get_face_mask_and_box   # internal, read-only

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
INPUT_IMAGE = os.path.join(SCRIPT_DIR, "assets", "test_pixelate.png")
OUTPUT_DIR  = os.path.join(SCRIPT_DIR, "assets", "test_pixelate_results")

# ---------------------------------------------------------------------------
# Sweep parameters (production mappings are NOT modified)
# ---------------------------------------------------------------------------
INTENSITY_LABELS = ["low", "medium", "high"]
FACTOR_VALUES    = list(range(4, 21))   # 4 .. 20 inclusive -> 17 values each


# ---------------------------------------------------------------------------
# Pixelation with a raw factor — identical to production pipeline except the
# intensity->factor lookup is replaced by the sweep's explicit value.
# ---------------------------------------------------------------------------
def _pixelate_factor(frame, bbox, factor):
    """Apply the oval-mask pixelation to bbox using a raw downscale factor.

    Mirrors redact_face(method='pixelate') exactly:
      1. _get_face_mask_and_box  - same expansion + feathering geometry
      2. thumbnail-and-upscale   - same INTER_LINEAR + INTER_NEAREST
      3. alpha-blend with mask   - same float32 compositing
    Only `factor` (ROI downscale divisor) is swapped in for the sweep.
    Larger factor -> smaller thumbnail -> larger visible blocks.
    """
    roi_data = _get_face_mask_and_box(frame.shape, bbox)
    if roi_data[0] is None:
        return frame
    (rx, ry, rw, rh), mask = roi_data
    roi    = frame[ry:ry + rh, rx:rx + rw]
    dw     = max(1, rw // factor)
    dh     = max(1, rh // factor)
    small  = cv2.resize(roi,   (dw, dh), interpolation=cv2.INTER_LINEAR)
    effect = cv2.resize(small, (rw, rh), interpolation=cv2.INTER_NEAREST)
    m      = mask[:, :, np.newaxis]
    frame[ry:ry + rh, rx:rx + rw] = ((m * effect) + ((1.0 - m) * roi)).astype(np.uint8)
    return frame


# ---------------------------------------------------------------------------
# Sweep
# ---------------------------------------------------------------------------
def main():
    # Load source image
    if not os.path.isfile(INPUT_IMAGE):
        sys.exit("ERROR: input image not found:\n  " + INPUT_IMAGE)
    src = cv2.imread(INPUT_IMAGE)
    if src is None:
        sys.exit("ERROR: cv2.imread failed for:\n  " + INPUT_IMAGE)
    print("Loaded: %s  (%dx%d px)" % (INPUT_IMAGE, src.shape[1], src.shape[0]))

    # Detect faces
    bboxes = face_detector.detect_faces(src)
    if not bboxes:
        sys.exit("ERROR: no faces detected in the input image. "
                 "Use a clearer frontal-face image or lower min_confidence.")
    print("Faces detected: %d" % len(bboxes))
    for i, b in enumerate(bboxes):
        print("  face %d: x=%d y=%d w=%d h=%d" % (i + 1, b[0], b[1], b[2], b[3]))

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    total = len(INTENSITY_LABELS) * len(FACTOR_VALUES)
    print("\nGenerating %d images -> %s\n" % (total, OUTPUT_DIR))

    # Print table header
    print("%-22s %-10s %-8s %s" % ("filename", "label", "factor", "status"))
    print("-" * 55)

    ok_count = 0
    for label in INTENSITY_LABELS:
        for v in FACTOR_VALUES:
            frame = src.copy()
            for bbox in bboxes:
                _pixelate_factor(frame, bbox, factor=v)
            fname    = "%s_%d.png" % (label, v)
            out_path = os.path.join(OUTPUT_DIR, fname)
            ok       = cv2.imwrite(out_path, frame)
            status   = "OK" if ok else "FAILED"
            print("%-22s %-10s %-8d %s" % (fname, label, v, status))
            if ok:
                ok_count += 1

    print("\n%d/%d images written to:\n  %s" % (ok_count, total, OUTPUT_DIR))
    if ok_count < total:
        sys.exit(1)


if __name__ == "__main__":
    main()
