"""
Device manager for PixelVeil GPU acceleration.

This module is the single source of truth for which compute device PixelVeil
uses for inference. It exposes three modes:

    "auto"  — use CUDA if a validated CUDA inference path exists, else CPU
    "cpu"   — always CPU (forced, unconditional)
    "cuda"  — require CUDA; raise RuntimeError if CUDA cannot be initialized

Public API
----------
    get_compute_device(requested="auto") -> str
        Resolves "auto" → "cuda" or "cpu" by actual probe.
        Returns the lowercase device string that was actually selected.

    is_cuda_available() -> bool
        True only when PyTorch CUDA DLLs loaded successfully AND an ORT
        InferenceSession with CUDAExecutionProvider could actually be created.
        Does NOT rely on ort.get_available_providers() alone.

    get_ort_providers(device) -> list[str]
        Returns the ordered ORT ExecutionProvider list for a device string.

    get_device_info() -> dict
        Returns a diagnostics dict describing the selected device, GPU
        properties, per-component providers, and any fallback reason.

Design notes
------------
- The expensive CUDA probe (DLL loading + session creation) is cached at
  module level and runs at most once per process lifetime.
- On Windows, ORT 1.20.x needs the CUDA/cuDNN DLLs that PyTorch ships.
  We add PyTorch's lib/ directory via os.add_dll_directory() before
  importing ORT — this is process-scoped and does not mutate PATH
  permanently. os.add_dll_directory() is the documented Windows mechanism
  (Python 3.8+ only, which is fine since PixelVeil targets Python 3.11).
- ort.preload_dlls() was introduced AFTER ORT 1.20.x and is NOT used here.
- We never hardcode an absolute path to the PyTorch or CUDA installation;
  the path is resolved dynamically from torch.__file__.
- Privacy correctness > GPU usage > speed. The device manager only claims
  CUDA when actual inference has been verified.

See docs/DECISIONS.md for the GPU acceleration decision record (D27).
"""

import os
import sys
import contextlib
import io
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level cache — the expensive CUDA probe runs at most once.
# ---------------------------------------------------------------------------
_cuda_probe_done: bool = False
_cuda_available: bool = False
_cuda_fallback_reason: str | None = None
_device_info_cache: dict | None = None


def _add_torch_lib_to_dll_search() -> str | None:
    """Add PyTorch's lib/ directory to the Windows DLL search path.

    ORT 1.20.x on Windows requires the CUDA/cuDNN DLLs that ship with
    PyTorch. This function locates them via torch.__file__ and registers
    the directory via os.add_dll_directory() (Python 3.8+, process-scoped,
    non-permanent).

    Returns the directory path that was added, or None if torch is not
    importable or os.add_dll_directory is unavailable (non-Windows).
    """
    if not hasattr(os, "add_dll_directory"):
        # Non-Windows (Linux/macOS) — DLL search path not needed.
        return None
    try:
        import torch  # noqa: PLC0415
        torch_lib = os.path.join(os.path.dirname(torch.__file__), "lib")
        if os.path.isdir(torch_lib):
            os.add_dll_directory(torch_lib)
            logger.debug("Added PyTorch lib dir to DLL search: %s", torch_lib)
            return torch_lib
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not add PyTorch lib dir to DLL search: %s", exc)
    return None


def _probe_cuda() -> tuple[bool, str | None]:
    """Run the actual CUDA probe — used internally, called once.

    Returns (available: bool, fallback_reason: str | None).

    The probe:
    1. Imports torch and checks torch.cuda.is_available().
    2. Adds PyTorch lib/ to the DLL search path (Windows).
    3. Imports onnxruntime and checks 'CUDAExecutionProvider' is listed.
    4. Creates an InferenceSession with a minimal in-memory ONNX model and
       CUDAExecutionProvider, then calls session.get_providers() to confirm
       the provider was actually honoured (ORT silently falls back to CPU
       if the CUDA init failed internally).
    5. Runs a single inference pass to confirm end-to-end execution works.
    """
    # --- Step 1: PyTorch CUDA check ---
    try:
        import torch  # noqa: PLC0415
        if not torch.cuda.is_available():
            return False, "torch.cuda.is_available() returned False"
    except ImportError:
        return False, "PyTorch (torch) is not installed"
    except Exception as exc:  # noqa: BLE001
        return False, f"PyTorch CUDA check failed: {exc}"

    # --- Step 2: Windows DLL path ---
    _add_torch_lib_to_dll_search()

    # --- Step 3: ORT provider list ---
    try:
        import onnxruntime as ort  # noqa: PLC0415
        available_providers = ort.get_available_providers()
        if "CUDAExecutionProvider" not in available_providers:
            return False, (
                f"CUDAExecutionProvider not in ort.get_available_providers(): "
                f"{available_providers}"
            )
    except ImportError:
        return False, "onnxruntime (or onnxruntime-gpu) is not installed"
    except Exception as exc:  # noqa: BLE001
        return False, f"ORT provider query failed: {exc}"

    # --- Step 4 + 5: Create a real session and run inference ---
    try:
        import numpy as np  # noqa: PLC0415
        import onnx  # noqa: PLC0415
        from onnx import helper, TensorProto  # noqa: PLC0415

        # Build the smallest possible valid ONNX model:
        # one Add node (X + Y -> Z), two float inputs, one float output.
        X = helper.make_tensor_value_info("X", TensorProto.FLOAT, [1, 4])
        Y = helper.make_tensor_value_info("Y", TensorProto.FLOAT, [1, 4])
        Z = helper.make_tensor_value_info("Z", TensorProto.FLOAT, [1, 4])
        add_node = helper.make_node("Add", inputs=["X", "Y"], outputs=["Z"])
        graph = helper.make_graph([add_node], "cuda_probe_graph", [X, Y], [Z])
        model = helper.make_model(graph, opset_imports=[
            helper.make_opsetid("", 13)
        ])
        onnx.checker.check_model(model)
        model_bytes = model.SerializeToString()

        provider_options = [
            ("CUDAExecutionProvider", {"device_id": 0}),
            ("CPUExecutionProvider", {}),
        ]
        # Suppress ORT's noisy provider-init warnings during the probe.
        captured = io.StringIO()
        with contextlib.redirect_stderr(captured):
            sess_opts = ort.SessionOptions()
            sess_opts.log_severity_level = 3  # ERROR only
            session = ort.InferenceSession(
                model_bytes,
                providers=[p for p, _ in provider_options],
                provider_options=[o for _, o in provider_options],
                sess_options=sess_opts,
            )

        # Confirm ORT actually used CUDA (it silently falls back to CPU if
        # the CUDA init fails internally — we must check, not assume).
        active_providers = session.get_providers()
        if "CUDAExecutionProvider" not in active_providers:
            return False, (
                f"ORT silently fell back to CPU; active providers: "
                f"{active_providers}"
            )

        # Run a real inference pass.
        x_data = np.ones((1, 4), dtype=np.float32)
        y_data = np.ones((1, 4), dtype=np.float32)
        outputs = session.run(["Z"], {"X": x_data, "Y": y_data})
        expected = x_data + y_data
        if not np.allclose(outputs[0], expected):
            return False, "CUDA inference produced incorrect output"

        return True, None

    except ImportError as exc:
        return False, f"Missing dependency for CUDA probe ({exc}); install 'onnx'"
    except Exception as exc:  # noqa: BLE001
        return False, f"CUDA session/inference probe failed: {exc}"


def is_cuda_available() -> bool:
    """Return True only when actual ORT CUDA inference has been verified.

    Caches the result — the expensive probe runs at most once per process.
    Calling this function is safe from any thread; the result is idempotent.
    """
    global _cuda_probe_done, _cuda_available, _cuda_fallback_reason
    if not _cuda_probe_done:
        _cuda_available, _cuda_fallback_reason = _probe_cuda()
        _cuda_probe_done = True
        if _cuda_available:
            logger.info("CUDA inference probe: SUCCESS")
        else:
            logger.info("CUDA inference probe: UNAVAILABLE — %s", _cuda_fallback_reason)
    return _cuda_available


def get_compute_device(requested: str = "auto") -> str:
    """Resolve a compute device request to "cuda" or "cpu".

    Args:
        requested: One of "auto", "cpu", or "cuda".
            "auto"  — use CUDA if validated, else CPU (never raises)
            "cpu"   — always CPU, regardless of GPU presence
            "cuda"  — require CUDA; raises RuntimeError if unavailable

    Returns:
        "cuda" or "cpu" (lowercase).

    Raises:
        ValueError: if `requested` is not one of the three valid values.
        RuntimeError: if `requested` is "cuda" and CUDA is unavailable.
    """
    requested = requested.lower().strip()
    if requested not in ("auto", "cpu", "cuda"):
        raise ValueError(
            f"compute_device must be 'auto', 'cpu', or 'cuda'; got {requested!r}"
        )

    if requested == "cpu":
        return "cpu"

    cuda_ok = is_cuda_available()

    if requested == "auto":
        return "cuda" if cuda_ok else "cpu"

    # requested == "cuda"
    if not cuda_ok:
        global _cuda_fallback_reason
        reason = _cuda_fallback_reason or "unknown"
        raise RuntimeError(
            f"compute_device='cuda' was requested but CUDA is not available.\n"
            f"Reason: {reason}\n"
            f"To use CPU instead, set compute_device='auto' or compute_device='cpu'."
        )
    return "cuda"


def get_ort_providers(device: str) -> list:
    """Return the ordered ORT ExecutionProvider list for a device string.

    Args:
        device: "cuda" or "cpu".

    Returns:
        A list of provider name strings in priority order.

    Note:
        For "cuda", CPUExecutionProvider is always appended as a fallback
        *within ORT's session* (for ops that have no CUDA kernel). This is
        standard ORT practice and does not affect the device selection —
        the session is still considered a CUDA session.
    """
    device = device.lower()
    if device == "cuda":
        return ["CUDAExecutionProvider", "CPUExecutionProvider"]
    return ["CPUExecutionProvider"]


def get_device_info() -> dict:
    """Return a diagnostics dict describing the current compute configuration.

    Calling this triggers the CUDA probe (if not already done). The dict
    is cached after the first call.

    Returned keys:
        device              "cuda" or "cpu"
        gpu_name            GPU model name, or None
        vram_mb             Total VRAM in MB, or None
        cuda_version        CUDA runtime version string, or None
        ort_version         onnxruntime version string
        torch_version       torch version string, or None
        face_detector_provider  ORT provider string for face detection
        ocr_provider            ORT provider string for OCR
        redactor            Always "CPU" (redaction is CPU-only)
        tracker             Always "CPU" (FaceTracker is pure geometry)
        encoder             Always "CPU" (ffmpeg encoding is CPU-only)
        fallback_reason     Reason CUDA was unavailable, or None
    """
    global _device_info_cache
    if _device_info_cache is not None:
        return dict(_device_info_cache)

    cuda_ok = is_cuda_available()
    device = "cuda" if cuda_ok else "cpu"

    gpu_name = None
    vram_mb = None
    cuda_version = None
    torch_version = None

    try:
        import torch  # noqa: PLC0415
        torch_version = torch.__version__
        if cuda_ok and torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            gpu_name = props.name
            vram_mb = props.total_memory // (1024 * 1024)
            cuda_version = torch.version.cuda
    except Exception:  # noqa: BLE001
        pass

    ort_version = None
    try:
        import onnxruntime as ort  # noqa: PLC0415
        ort_version = ort.__version__
    except Exception:  # noqa: BLE001
        pass

    providers = get_ort_providers(device)
    face_detector_provider = providers[0]
    ocr_provider = providers[0]

    _device_info_cache = {
        "device": device,
        "gpu_name": gpu_name,
        "vram_mb": vram_mb,
        "cuda_version": cuda_version,
        "ort_version": ort_version,
        "torch_version": torch_version,
        "face_detector_provider": face_detector_provider,
        "ocr_provider": ocr_provider,
        "redactor": "CPU",
        "tracker": "CPU",
        "encoder": "CPU",
        "fallback_reason": _cuda_fallback_reason,
    }
    return dict(_device_info_cache)


def reset_probe_cache() -> None:
    """Reset the CUDA probe cache — for testing only.

    Allows tests to simulate CUDA availability changes by monkey-patching
    _probe_cuda and then calling this function to clear the cached result.
    NOT intended for production use.
    """
    global _cuda_probe_done, _cuda_available, _cuda_fallback_reason, _device_info_cache
    _cuda_probe_done = False
    _cuda_available = False
    _cuda_fallback_reason = None
    _device_info_cache = None
