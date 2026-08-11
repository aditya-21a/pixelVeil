"""
CUDA Inference Verification — PixelVeil Diagnostic

Run this script to confirm that ORT CUDAExecutionProvider is actually
usable for inference on this machine, NOT just listed as available.

Usage:
    python tools/verify_cuda.py

Exit codes:
    0 — CUDA inference verified successfully
    1 — CUDA unavailable or inference failed (see printed reason)
"""

import sys
import os

# Allow running from the project root or from tools/
_this_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_this_dir)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# Suppress INFO logging during the probe (device_manager logs probe results).
import logging
logging.basicConfig(level=logging.WARNING)

import io
import contextlib
import time

import numpy as np

# ── 1. PyTorch ───────────────────────────────────────────────────────────────
print("\n=== PixelVeil CUDA Verification ===\n")

torch_ok = False
torch_version = "N/A"
cuda_torch = False
gpu_name = "N/A"
vram_mb = 0

try:
    import torch
    torch_version = torch.__version__
    cuda_torch = torch.cuda.is_available()
    torch_ok = True
    if cuda_torch:
        gpu_name = torch.cuda.get_device_name(0)
        props = torch.cuda.get_device_properties(0)
        vram_mb = props.total_memory // (1024 * 1024)
except ImportError:
    print("ERROR: PyTorch (torch) is not installed.")
    sys.exit(1)

print(f"PyTorch version   : {torch_version}")
print(f"torch.cuda        : {'YES' if cuda_torch else 'NO'}")
print(f"GPU               : {gpu_name}")
print(f"VRAM              : {vram_mb} MB")

# ── 2. ORT version + provider list ───────────────────────────────────────────
ort_version = "N/A"
available_providers = []
cuda_listed = False

try:
    import onnxruntime as ort
    ort_version = ort.__version__
    available_providers = ort.get_available_providers()
    cuda_listed = "CUDAExecutionProvider" in available_providers
except ImportError:
    print("\nERROR: onnxruntime / onnxruntime-gpu is not installed.")
    sys.exit(1)

print(f"\nORT version       : {ort_version}")
print(f"Listed providers  : {available_providers}")
print(f"CUDA listed       : {'YES' if cuda_listed else 'NO'}")

if not cuda_listed:
    print("\nCUDA NOT AVAILABLE — CUDAExecutionProvider not in provider list.")
    print("Install onnxruntime-gpu (not plain onnxruntime).")
    sys.exit(1)

# ── 3. Add PyTorch CUDA DLLs to Windows search path ──────────────────────────
dll_dir = None
if hasattr(os, "add_dll_directory"):
    torch_lib = os.path.join(os.path.dirname(torch.__file__), "lib")
    if os.path.isdir(torch_lib):
        os.add_dll_directory(torch_lib)
        dll_dir = torch_lib
        print(f"\nDLL search dir    : {torch_lib}")
    else:
        print(f"\nWARNING: PyTorch lib dir not found at {torch_lib}")
else:
    print("\n(Non-Windows — os.add_dll_directory not needed)")

# ── 4. Build minimal ONNX model in-memory ────────────────────────────────────
try:
    import onnx
    from onnx import helper, TensorProto

    X = helper.make_tensor_value_info("X", TensorProto.FLOAT, [1, 4])
    Y = helper.make_tensor_value_info("Y", TensorProto.FLOAT, [1, 4])
    Z = helper.make_tensor_value_info("Z", TensorProto.FLOAT, [1, 4])
    add_node = helper.make_node("Add", inputs=["X", "Y"], outputs=["Z"])
    graph = helper.make_graph([add_node], "verify_graph", [X, Y], [Z])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    onnx.checker.check_model(model)
    model_bytes = model.SerializeToString()
    print("ONNX probe model  : built OK (1-node Add graph)")
except ImportError:
    print("\nERROR: 'onnx' package not installed. Run: pip install onnx")
    sys.exit(1)

# ── 5. Create ORT session with CUDAExecutionProvider ─────────────────────────
print("\n--- Creating ORT InferenceSession with CUDAExecutionProvider ---")
t0 = time.perf_counter()

captured = io.StringIO()
try:
    with contextlib.redirect_stderr(captured):
        sess_opts = ort.SessionOptions()
        sess_opts.log_severity_level = 3  # ERROR
        session = ort.InferenceSession(
            model_bytes,
            providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
            provider_options=[{"device_id": 0}, {}],
            sess_options=sess_opts,
        )
except Exception as exc:
    print(f"\nFAIL: Could not create ORT session with CUDAExecutionProvider.")
    print(f"      {exc}")
    sys.exit(1)

session_time_ms = (time.perf_counter() - t0) * 1000

active = session.get_providers()
cuda_active = "CUDAExecutionProvider" in active
print(f"Session created   : {session_time_ms:.1f} ms")
print(f"Active providers  : {active}")
print(f"CUDA active       : {'YES' if cuda_active else 'NO (silently fell back to CPU)'}")

if not cuda_active:
    print("\nFAIL: ORT silently fell back to CPUExecutionProvider.")
    print("      CUDAExecutionProvider was listed but couldn't be initialized.")
    ort_stderr = captured.getvalue().strip()
    if ort_stderr:
        print(f"      ORT stderr: {ort_stderr}")
    sys.exit(1)

# ── 6. Run inference — warm-up then steady-state ──────────────────────────────
print("\n--- Running inference (1 warm-up + 5 steady-state) ---")
x_data = np.ones((1, 4), dtype=np.float32)
y_data = np.ones((1, 4), dtype=np.float32)
expected = x_data + y_data

# Warm-up (don't count)
try:
    _ = session.run(["Z"], {"X": x_data, "Y": y_data})
except Exception as exc:
    print(f"\nFAIL: Inference raised exception: {exc}")
    sys.exit(1)

# Steady-state
N = 5
times = []
for _ in range(N):
    t0 = time.perf_counter()
    outputs = session.run(["Z"], {"X": x_data, "Y": y_data})
    times.append((time.perf_counter() - t0) * 1000)

# Correctness check
if not np.allclose(outputs[0], expected):
    print(f"\nFAIL: CUDA inference produced wrong output.")
    print(f"      expected {expected}, got {outputs[0]}")
    sys.exit(1)

avg_ms = sum(times) / len(times)
print(f"Inference correct : YES")
print(f"Avg latency       : {avg_ms:.3f} ms (n={N}, steady-state)")

# ── 7. device_manager integration check ──────────────────────────────────────
print("\n--- device_manager integration check ---")
try:
    from core.device_manager import (
        is_cuda_available,
        get_compute_device,
        get_ort_providers,
        get_device_info,
    )
    dm_cuda = is_cuda_available()
    dm_device = get_compute_device("auto")
    dm_providers = get_ort_providers(dm_device)
    dm_info = get_device_info()

    print(f"is_cuda_available : {dm_cuda}")
    print(f"get_compute_device: {dm_device}")
    print(f"ort_providers     : {dm_providers}")
    print(f"device_info       : {dm_info}")
except Exception as exc:
    print(f"WARNING: device_manager integration check failed: {exc}")

# ── Final summary ─────────────────────────────────────────────────────────────
print("\n=== VERIFICATION RESULT ===\n")
print(f"  CUDA available          : {'YES' if cuda_torch else 'NO'}")
print(f"  ORT version             : {ort_version}")
print(f"  PyTorch version         : {torch_version}")
print(f"  GPU                     : {gpu_name}")
print(f"  VRAM                    : {vram_mb} MB")
print(f"  CUDAExecutionProvider   : {'YES (listed)' if cuda_listed else 'NO'}")
print(f"  CUDAExecutionProvider   : {'YES (active in session)' if cuda_active else 'NO (fell back to CPU)'}")
print(f"  Test inference          : {'SUCCESS' if cuda_active else 'FAILED'}")
print()

if not cuda_active:
    print("RESULT: FAIL — CUDA inference could not be verified.\n")
    sys.exit(1)

print("RESULT: PASS — CUDA inference verified end-to-end.\n")
sys.exit(0)
