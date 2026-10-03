#!/usr/bin/env python3
"""NLF-S accelerated feature engines + async latest-frame-wins pose pipeline.

Replaces ONLY the expensive backbone stage (EffNetV2-S) of the NLF fast path with
a pluggable engine; warp, decode and reconstruct always run the model's own
(cheap) compiled methods. Backends, all from the SAME fp16/fp32 ONNX export:

  torch  — the original TorchScript path (reference; very slow on CPU)
  trt    — TensorRT engine (NVIDIA GPUs; fastest)
  dml    — onnxruntime-directml (any DirectX 12 GPU: AMD/Intel/NVIDIA iGPU)
  ov     — OpenVINO (Intel CPU + iGPU via the GPU plugin)
  ort    — onnxruntime CPU (anywhere, no GPU)

Backend selection is MEASURED, not heuristic: `calibrate_backend` benches every
loadable backend on the real pose path and picks the fastest (TRT tie-break
within 20% for CUDA robustness), cached by hardware fingerprint. At runtime
`AsyncPoseWorker` monitors latency/drops and hot-swaps via `set_backend` when
degraded (1.5x baseline); hard failures (e.g. a DML driver TDR) auto-fallback
to the next-fastest candidate after 2 consecutive errors.

The `AsyncPoseWorker` runs decode/detect/infer off the asyncio event loop with
latest-frame-wins semantics: when the queue is full the oldest frame is dropped,
so a slow stage never grows the backlog (bounded latency, game-loop pattern).
YOLO detection runs on its own thread so its spike never blocks the pose path.

Validated end-to-end against `estimate_poses_batched` (0.0002 mm with the ORT
backend); quality vs teacher identical to the fast-path reference.
"""

from __future__ import annotations

import importlib.util
import json
import os
import queue
import sys
import threading
import time
from collections import deque
from pathlib import Path

import numpy as np
import torch

LAB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB_ROOT / "scripts"))

EXPERIMENTS = LAB_ROOT / "experiments" / "autoresearch"
ONNX16 = EXPERIMENTS / "nlf_features_fp16.onnx"
ONNX32 = EXPERIMENTS / "nlf_features_fp32.onnx"
ENGINE = EXPERIMENTS / "nlf_features_fp16.engine"
BACKEND_CACHE = EXPERIMENTS / "backend_choice.json"


# ---------------------------------------------------------------------------
# NLF helpers (exact reimplementation, validated 0.0002 mm vs the model)
# ---------------------------------------------------------------------------


def im_to_linear(x: torch.Tensor) -> torch.Tensor:
    """Exact NLF im_to_linear (isarandi/nlf multiperson_model.py): uint8 -> fp16 (x/255)^2.2."""
    if x.dtype == torch.uint8:
        return x.to(dtype=torch.float16).mul_(1.0 / 255.0).pow_(2.2)
    return x.to(dtype=torch.float16).pow_(2.2)


def intr_from_fov(fov_deg: float, hw, device="cpu") -> torch.Tensor:
    """Exact NLF intrinsic_matrix_from_field_of_view: focal from the LARGER side,
    principal point at ((w-1)/2, (h-1)/2). -> [1,3,3] fp32."""
    imshape = torch.tensor([float(hw[0]), float(hw[1])], dtype=torch.float32, device=device)
    fov_rad = fov_deg * torch.tensor(torch.pi / 180, dtype=torch.float32, device=device)
    focal = torch.max(imshape) / (torch.tan(fov_rad / 2) * 2)
    return (
        torch.stack(
            [focal, torch.tensor(0, dtype=torch.float32, device=device), (imshape[1] - 1) / 2,
             torch.tensor(0, dtype=torch.float32, device=device), focal, (imshape[0] - 1) / 2,
             torch.tensor(0, dtype=torch.float32, device=device), torch.tensor(0, dtype=torch.float32, device=device),
             torch.tensor(1, dtype=torch.float32, device=device)],
            dim=-1,
        )
        .unflatten(-1, (3, 3))
        .unsqueeze(0)
    )


def resolve_backend(kind: str, device: str) -> str:
    """Resolve a requested backend name. `auto` consults the calibration cache
    first (fast path), then falls back to the heuristic order. Real measured
    calibration (with model+weights) happens in `calibrate_backend`."""
    if kind != "auto":
        return kind
    cached = load_backend_choice()
    if cached and cached.get("fingerprint") == hardware_fingerprint():
        name = cached.get("backend")
        if name in available_backends(device):
            return name
    if str(device).startswith("cuda") and importlib.util.find_spec("tensorrt") is not None and ENGINE.is_file():
        return "trt"
    if importlib.util.find_spec("onnxruntime") is not None:
        try:
            import onnxruntime as ort  # noqa: F401

            if "DmlExecutionProvider" in ort.get_available_providers():
                return "dml"
        except Exception:
            pass
    if importlib.util.find_spec("openvino") is not None:
        return "ov"
    return "ort"


# ---------------------------------------------------------------------------
# Adaptive backend selection: measured calibration + per-hardware cache
# ---------------------------------------------------------------------------


def _pkg_version(name: str) -> str:
    try:
        return str(getattr(__import__(name), "__version__", "?"))
    except Exception:
        return "none"


def hardware_fingerprint() -> str:
    """String that changes whenever a hardware/software knob that affects backend
    speed changes: GPU model, CPU count, runtime package versions, ONNX/engine
    file identity. Cache hits are only valid for the exact same fingerprint."""
    parts = [os.cpu_count() and f"cpu{os.cpu_count()}"]
    try:
        if torch.cuda.is_available():
            parts.append(f"gpu:{torch.cuda.get_device_name(0)}")
    except Exception:
        pass
    for mod in ("tensorrt", "onnxruntime", "openvino"):
        parts.append(f"{mod}={_pkg_version(mod)}")
    for p in (ONNX16, ONNX32, ENGINE):
        try:
            st = p.stat()
            parts.append(f"{p.name}:{st.st_size}:{int(st.st_mtime)}")
        except Exception:
            parts.append(f"{p.name}:missing")
    return "|".join(parts)


def load_backend_choice() -> dict | None:
    try:
        if BACKEND_CACHE.is_file():
            return json.loads(BACKEND_CACHE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


def save_backend_choice(backend: str, baseline: dict, fingerprint: str) -> None:
    try:
        BACKEND_CACHE.parent.mkdir(parents=True, exist_ok=True)
        BACKEND_CACHE.write_text(
            json.dumps(
                {
                    "fingerprint": fingerprint,
                    "backend": backend,
                    "baseline": baseline,
                    "calibrated_at": time.time(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception as e:
        sys.stderr.write(f"[nlf_engine] cache write failed: {e}\n")


def available_backends(device: str) -> list[str]:
    """Candidates actually loadable on this machine, best-first heuristic.
    TRT needs the pre-built engine (building takes minutes; never during bench)."""
    out: list[str] = []
    has_cuda = str(device).startswith("cuda") and torch.cuda.is_available()
    if has_cuda and importlib.util.find_spec("tensorrt") is not None and ENGINE.is_file():
        out.append("trt")
    if importlib.util.find_spec("onnxruntime") is not None and ONNX16.is_file():
        try:
            import onnxruntime as ort  # noqa: F401

            if "DmlExecutionProvider" in ort.get_available_providers():
                out.append("dml")
        except Exception:
            pass
    if importlib.util.find_spec("openvino") is not None and ONNX32.is_file():
        out.append("ov")
    if importlib.util.find_spec("onnxruntime") is not None and ONNX32.is_file():
        out.append("ort")
    out.append("torch")
    return out


def calibrate_backend(
    model,
    weights: dict[str, torch.Tensor],
    device: str,
    n_iters: int = 8,
    use_cache: bool = True,
) -> tuple[str, "NlfFeatureEngine", dict]:
    """Bench every loadable backend on the real pose path and return the fastest.

    Returns (backend_name, ready_engine, baseline_ms). The returned engine is
    the winning candidate itself (no double construction). Results are cached by
    hardware fingerprint so steady-state boots skip the ~10-25 s probe
    (cache hit is ~1 s: engine construction only, no benching).

    Baseline = {'p50': ms, 'p95': ms, 'mean': ms} of the FULL pose path
    (warp + features + decode), which is what the runtime monitor compares
    against to decide when a live rebalance is worth it.
    """
    key = hardware_fingerprint()
    if use_cache:
        cached = load_backend_choice()
        if cached and cached.get("fingerprint") == key:
            name = cached.get("backend")
            base = dict((cached.get("baseline") or {}).get(name) or {})
            # Same TRT tie-break as fresh calibration, so an old cache cannot
            # resurrect a within-noise DML pick over the native CUDA path.
            bl_all = cached.get("baseline") or {}
            if name != "trt" and "trt" in bl_all and bl_all["trt"].get("p50"):
                if bl_all["trt"]["p50"] <= 1.2 * float(base.get("p50") or float("inf")):
                    name, base = "trt", dict(bl_all["trt"])
            try:
                eng = NlfFeatureEngine(model, weights, name, device)
                eng.baseline = base
                sys.stderr.write(f"[nlf_engine] cached backend: {name} (baseline p50 {base.get('p50', float('nan')):.1f} ms)\n")
                return name, eng, base
            except Exception as e:
                sys.stderr.write(f"[nlf_engine] cached backend {name} failed ({e}); recalibrating\n")

    # Hardware-class cut, two levels:
    #  1) GPU tier (trt/dml) exists -> those are the only realistic contenders;
    #     bench them fully. CPU backends (ov/ort) get a 3-iteration sanity bench
    #     just to rank the fallback order (they lose by 3-4x on any GPU EP).
    #  2) torch (the reference path) is NEVER benched: it cannot win whenever any
    #     ONNX engine is loadable (21-54 ms vs ~9 ms here; ~7 s/frame on CPU), and
    #     its bench is pathologically slow — first CUDA call pays an ~18 s JIT/
    #     autotune cost. It is ranked last for the hard-failure fallback instead.
    # On a CPU-only box (no trt/dml) everyone realistic is benched fully.
    cands = available_backends(device)
    gpu_tier = [b for b in cands if b in ("trt", "dml")]
    cpu_tier = [b for b in cands if b not in ("trt", "dml") and b != "torch"]
    full, quick = (gpu_tier, cpu_tier) if gpu_tier else (cpu_tier, [])
    results: dict[str, dict] = {}
    engines: dict[str, NlfFeatureEngine] = {}
    for name in full + quick:
        try:
            eng = NlfFeatureEngine(model, weights, name, device)
            engines[name] = eng
            ms = eng.bench_ms(n=n_iters if name in full else 3)
            results[name] = ms
            tag = "" if name in full else " (quick)"
            sys.stderr.write(
                f"[nlf_engine] calibrate {name}: p50 {ms['p50']:.1f} ms | p95 {ms['p95']:.1f} ms{tag}\n"
            )
        except Exception as e:
            sys.stderr.write(f"[nlf_engine] calibrate {name} failed: {e}\n")
    if not results:
        # Only the reference path is loadable — use it without benching.
        engines["torch"] = NlfFeatureEngine(model, weights, "torch", device)
        results["torch"] = {"p50": 1e9, "mean": 1e9, "p95": 1e9}
    best_name = min(results, key=lambda n: results[n]["p50"])
    # Tie-break toward TRT when within 20%: it is the native CUDA path and avoids
    # the DX12/CUDA-sharing flakiness DML can hit under concurrent load (TDRs).
    # Measurements are noisy (TRT measured 9.3-10.7 ms across sessions), so a
    # small margin is worth the robustness. No-op on machines without CUDA.
    if "trt" in results and best_name != "trt" and results["trt"]["p50"] <= 1.2 * results[best_name]["p50"]:
        best_name = "trt"
    best_engine = engines[best_name]
    # Ranked fallback order for hard-failure auto-switching (fastest first).
    best_engine._ranked = sorted(results, key=lambda n: results[n]["p50"]) + [
        n for n in available_backends(device) if n not in results
    ]
    best_engine.baseline = dict(results[best_name])
    save_backend_choice(best_name, results, key)
    engines.clear()  # drop non-winner sessions (DML GPU alloc, OV model, TRT ctx)
    sys.stderr.write(
        f"[nlf_engine] calibrated: {best_name} (p50 {best_engine.baseline['p50']:.1f} ms)\n"
    )
    return best_name, best_engine, best_engine.baseline


def build_trt_engine(onnx_path: Path, engine_path: Path, workspace_gb: int = 2) -> None:
    """Build a TensorRT engine from the fp16 ONNX (TRT 10/11 API). One-time cost."""
    import tensorrt as trt

    logger = trt.Logger(trt.Logger.WARNING)
    builder = trt.Builder(logger)
    network = builder.create_network()  # explicit batch is the default in TRT 10/11
    parser = trt.OnnxParser(network, logger)
    if not parser.parse_from_file(str(onnx_path)):
        for i in range(parser.num_errors):
            print(parser.get_error(i))
        raise RuntimeError("ONNX parse failed")
    config = builder.create_builder_config()
    config.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE, workspace_gb << 30)
    t0 = time.time()
    serialized = builder.build_serialized_network(network, config)
    if serialized is None:
        raise RuntimeError("engine build failed")
    engine_path.parent.mkdir(parents=True, exist_ok=True)
    engine_path.write_bytes(bytes(serialized))
    print(f"[nlf_engine] TRT engine built in {time.time() - t0:.0f}s -> {engine_path}", flush=True)


class _TrtRunner:
    """Minimal TensorRT runner: crops [N,3,256,256] fp16 CUDA -> features fp16 CUDA.

    Cross-stream sync both ways (TRT waits for the producer, the consumer waits
    for TRT) — otherwise the decode can race and read garbage/NaN.
    """

    def __init__(self, engine_bytes: bytes):
        import tensorrt as trt

        logger = trt.Logger(trt.Logger.WARNING)
        runtime = trt.Runtime(logger)
        self.engine = runtime.deserialize_cuda_engine(engine_bytes)
        self.ctx = self.engine.create_execution_context()
        self.in_name = self.engine.get_tensor_name(0)
        self.out_name = self.engine.get_tensor_name(1)
        self.stream = torch.cuda.Stream()
        # An IExecutionContext is not thread-safe; the HTTP path (main thread)
        # and the WS worker thread can both run the engine.
        self._lock = threading.Lock()

    def run(self, crops: torch.Tensor) -> torch.Tensor:
        with self._lock:
            n = crops.shape[0]
            self.ctx.set_input_shape(self.in_name, tuple(crops.shape))
            out = torch.empty(n, 512, 8, 8, dtype=torch.float16, device=crops.device)
            self.stream.wait_stream(torch.cuda.current_stream())
            with torch.cuda.stream(self.stream):
                self.ctx.set_tensor_address(self.in_name, crops.data_ptr())
                self.ctx.set_tensor_address(self.out_name, out.data_ptr())
                ok = self.ctx.execute_async_v3(stream_handle=self.stream.cuda_stream)
                assert ok
            torch.cuda.current_stream().wait_stream(self.stream)
        return out


# ---------------------------------------------------------------------------
# Feature engine
# ---------------------------------------------------------------------------


class NlfFeatureEngine:
    """num_aug=1, single-box NLF core with a pluggable features backend.

    warp / decode / reconstruct run the model's own compiled methods; only the
    backbone (EffNetV2-S, ~95% of the FLOPs) goes through the engine.
    """

    def __init__(self, model, weights: dict[str, torch.Tensor], backend: str = "auto", device: str | None = None):
        self.model = model
        self.cm = model.crop_model
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.backend = resolve_backend(backend, self.device)
        self._runner = None
        # Protects backend/_runner swaps from in-flight _run_core reads (the
        # HTTP path and the WS worker thread can run the engine concurrently).
        self._swap_lock = threading.Lock()
        self.baseline: dict = {}
        # Hard-failure auto-fallback state: consecutive failures poison a backend
        # and switch to the next-fastest candidate (e.g. a DML driver TDR).
        self._consecutive_failures = 0
        self._poisoned: set[str] = set()
        self._ranked: list[str] = []
        self.update_weights(weights)
        self._init_backend()

    # -- weights -----------------------------------------------------------

    def update_weights(self, weights: dict[str, torch.Tensor]) -> None:
        """Refresh the decode weight dict (e.g. after switching to dense query).
        Kept on CPU fp32; moved to the features' device on demand in _decode (CPU
        engines like ort/ov/dml produce CPU features even when a GPU is present)."""
        self._weights = {k: v.detach().float() for k, v in weights.items()}
        self._w16 = {k: v.half() for k, v in self._weights.items()}
        self._w_cache: dict[str, dict[str, torch.Tensor]] = {}
        self._w16_cache: dict[str, dict[str, torch.Tensor]] = {}

    # -- backend init ------------------------------------------------------

    def _init_backend(self) -> None:
        b = self.backend
        if b == "torch":
            return
        if not ONNX16.is_file() and not ONNX32.is_file():
            raise FileNotFoundError("missing ONNX exports — run experiments/autoresearch/export_features.py first")
        if b == "trt":
            if not ENGINE.is_file():
                build_trt_engine(ONNX16, ENGINE)
            self._runner = _TrtRunner(ENGINE.read_bytes())
        elif b == "dml":
            import onnxruntime as ort

            self._runner = ort.InferenceSession(
                str(ONNX16),
                providers=["DmlExecutionProvider", "CPUExecutionProvider"],
                sess_options=ort.SessionOptions(),
            )
        elif b == "ov":
            import openvino as ov

            core = ov.Core()
            m = core.read_model(str(ONNX32))
            self._runner = core.compile_model(m, "CPU", config={"NUM_STREAMS": "1"})
        elif b == "ort":
            import onnxruntime as ort

            self._runner = ort.InferenceSession(
                str(ONNX32), providers=["CPUExecutionProvider"], sess_options=ort.SessionOptions()
            )
        else:
            raise ValueError(f"unknown backend: {b}")

    # -- warp --------------------------------------------------------------

    def warp(self, rgb_u8_hwc: np.ndarray, box=None) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """(crops [1,1,3,256,256], new_intrinsic [1,1,3,3], R [1,1,3,3])."""
        dev = self.device
        h, w = rgb_u8_hwc.shape[:2]
        img = torch.from_numpy(np.ascontiguousarray(rgb_u8_hwc)).permute(2, 0, 1).unsqueeze(0).to(dev)
        lin = im_to_linear(img)
        if str(dev) == "cpu":
            # CPU fp16 emulation diverges badly from native GPU fp16 in the warp
            # (pow/grid_sample): run the warp in fp32 on CPU (63x closer, validated).
            lin = lin.float()
        intr = intr_from_fov(55.0, (h, w), device=dev)
        dist = torch.zeros(1, 5, device=dev)
        camspace_up = torch.einsum(
            "c,bCc->bC",
            [
                torch.tensor([0.0, -1.0, 0.0], dtype=torch.float32, device=dev),
                torch.eye(4, device=dev)[:3, :3].unsqueeze(0),
            ],
        )
        if box is None:
            box = torch.tensor([[0.0, 0.0, float(w), float(h)]], device=dev)
        else:
            box = box.detach().to(dev).float()
            if box.shape[-1] == 4:  # estimate_poses_batched convention: xywh, no conf
                box = torch.cat([box, torch.ones(box.shape[0], 1, device=dev)], dim=-1)
        image_ids = torch.tensor([0], device=dev)
        rotflip = torch.eye(3, dtype=torch.float32, device=dev).unsqueeze(0)
        scales = torch.tensor([1.0], dtype=torch.float32, device=dev)
        # ptu.linspace(0.6, 1.0, num=1) returns mean([0.6, 1.0]) = 0.8 (not 0.6!)
        gammas = torch.tensor([0.8], dtype=torch.float32, device=dev)
        crops, new_intr, R = self.model._get_crops(
            lin, intr, dist, camspace_up, box, image_ids, rotflip, scales, gammas, 1
        )
        return crops, new_intr, R

    # -- decode + reconstruct (shared, fp32) --------------------------------

    def _decode(self, feats: torch.Tensor, new_intr: torch.Tensor) -> torch.Tensor:
        dev = str(feats.device)
        w = self._w_cache.get(dev)
        if w is None:
            w = {k: v.to(feats.device) for k, v in self._weights.items()}
            self._w_cache[dev] = w
        flip = torch.zeros(feats.shape[0], dtype=torch.bool, device=feats.device)
        c2d, c3d, unc = self.cm.heatmap_head.decode_features_multi_same_weights(feats, w, flip)
        poses, _ = self.cm.heatmap_head.reconstruct_absolute(c2d, c3d, unc, new_intr.reshape(-1, 3, 3).to(feats.device))
        return poses

    def set_backend(self, backend: str) -> None:
        """Hot-swap the features backend (runtime rebalance). Weight/device caches
        adapt automatically; in-flight calls finish on the old runner."""
        with self._swap_lock:
            if backend == self.backend:
                return
            self.backend = backend
            self._runner = None
            self._consecutive_failures = 0
            self._init_backend()

    def _next_fallback(self, current: str) -> str | None:
        """Next-fastest backend not currently poisoned (ranked by calibration)."""
        if not self._ranked:
            self._ranked = available_backends(self.device)
        for nb in self._ranked:
            if nb != current and nb not in self._poisoned:
                return nb
        return None

    def _dispatch(self, b: str, runner, crops: torch.Tensor, new_intr: torch.Tensor) -> torch.Tensor:
        """Run features+decode for one backend. Exceptions bubble to _run_core,
        which decides whether to poison the backend and auto-fallback."""
        if b == "torch":
            crops_flat = crops.reshape(-1, 3, 256, 256).half()
            intr_flat = new_intr.reshape(-1, 3, 3).half()
            dev = str(crops_flat.device)
            w16 = self._w16_cache.get(dev)
            if w16 is None:
                w16 = {k: v.to(crops_flat.device) for k, v in self._w16.items()}
                self._w16_cache[dev] = w16
            flip = torch.zeros(crops_flat.shape[0], dtype=torch.bool, device=self.device)
            poses, _ = self.cm.predict_multi_same_weights(crops_flat, intr_flat, w16, flip)
            return poses
        if b == "trt":
            crops_flat = crops.reshape(-1, 3, 256, 256).contiguous()
            feats = runner.run(crops_flat)  # fp16 CUDA
            return self._decode(feats.float(), new_intr)
        # CPU engines: DML takes fp16 crops (fp16 ONNX), OV/ORT take fp32.
        crops_cpu = crops.reshape(-1, 3, 256, 256).cpu()
        if b == "dml":
            feats = np.asarray(runner.run(None, {"crops": crops_cpu.half().numpy()})[0])
        elif b == "ov":
            # OpenVINO CompiledModel is callable; returns {output_name: ndarray}.
            out = runner({"crops": crops_cpu.float().numpy()})
            feats = np.asarray(out if isinstance(out, np.ndarray) else next(iter(out.values())))
        else:
            feats = np.asarray(runner.run(None, {"crops": crops_cpu.float().numpy()})[0])
        feats_t = torch.from_numpy(feats).float()
        return self._decode(feats_t, new_intr)

    def _run_core(self, crops: torch.Tensor, new_intr: torch.Tensor) -> torch.Tensor:
        n_cases = crops.shape[1]
        with self._swap_lock:
            b = self.backend
            runner = self._runner
        try:
            out = self._dispatch(b, runner, crops, new_intr)
            self._consecutive_failures = 0
            return out
        except Exception as e:
            self._consecutive_failures += 1
            if self._consecutive_failures >= 2:
                nb = self._next_fallback(b)
                if nb is not None:
                    self._poisoned.add(b)
                    sys.stderr.write(
                        f"[nlf_engine] backend {b} failed ({type(e).__name__}) — auto-switching to {nb}\n"
                    )
                    self.set_backend(nb)
            raise

    def bench_ms(self, n: int = 10, warmup: int = 3) -> dict:
        """Full pose path (warp + features + decode) on a synthetic 960x540 frame
        with a center box — the same work the live path does per frame."""
        frame = np.full((540, 960, 3), 128, dtype=np.uint8)
        box = torch.tensor([[192.0, 108.0, 576.0, 324.0]], dtype=torch.float32)
        for _ in range(warmup):
            self.infer(frame, box)
        ts = []
        for _ in range(n):
            t0 = time.perf_counter()
            self.infer(frame, box)
            ts.append((time.perf_counter() - t0) * 1000.0)
        a = np.asarray(ts)
        return {
            "p50": float(np.median(a)),
            "mean": float(a.mean()),
            "p95": float(np.percentile(a, 95)),
        }

    # -- full pose ---------------------------------------------------------

    def infer(self, rgb_u8_hwc: np.ndarray, box=None) -> np.ndarray:
        """rgb uint8 HWC -> poses [n_joints,3] in mm (same space as estimate_joints24)."""
        with torch.inference_mode():
            crops, new_intr, R = self.warp(rgb_u8_hwc, box)
            poses_flat = self._run_core(crops, new_intr)
            n_cases = crops.shape[1]
            n_joints = poses_flat.shape[-2]
            poses = poses_flat.reshape(n_cases, -1, 3).float()  # [n_cases, n_joints, 3]
            # R comes from _get_crops as [1,1,3,3]; squeeze to a single rotation.
            Rf = R.float().to(poses.device).reshape(3, 3)
            p = torch.matmul(poses, Rf)[0]  # [n_joints, 3]
        return p.detach().float().cpu().numpy()

    def status(self) -> dict:
        return {"backend": self.backend, "device": self.device, "baseline": self.baseline}


# ---------------------------------------------------------------------------
# Async latest-frame-wins pose pipeline (decode / detect / infer off the loop)
# ---------------------------------------------------------------------------


class AsyncPoseWorker:
    """Feeds JPEG frames from the WS handler; emits pose dicts out the other side.

    - decode + infer run on one worker thread (never the asyncio event loop)
    - YOLO detection runs on its own thread; its spike never blocks the pose path
    - latest-frame-wins: full queues drop the OLDEST frame -> bounded latency

    Attach an asyncio loop for async delivery (`await worker.get()`), or poll
    `drain()` in a plain loop (headless bench / tests).
    """

    def __init__(self, runtime, max_pending: int = 2, max_out: int = 2, max_side: int = 1280):
        self.runtime = runtime
        self.max_side = max_side
        self._in: queue.Queue[tuple[int, bytes]] = queue.Queue(maxsize=max_pending)
        self._out: queue.Queue[dict] = queue.Queue(maxsize=max_out)
        self._det_jobs: queue.Queue[np.ndarray] = queue.Queue(maxsize=1)
        self._last_detected: np.ndarray | None = None
        self._det_lock = threading.Lock()
        self._loop = None
        self._aq = None
        self._started = False
        self.dropped = 0
        # Runtime rebalance monitor: rolling latency window + drop rate.
        self._ms_window: deque[float] = deque(maxlen=90)
        self._check_every = 45
        self._frames_since_check = 0
        self._submitted_since_check = 0
        self._dropped_since_check = 0

    def attach_loop(self, loop) -> None:
        import asyncio

        self._loop = loop
        self._aq = asyncio.Queue()

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        threading.Thread(target=self._worker_loop, name="nlp-pose", daemon=True).start()
        threading.Thread(target=self._det_loop, name="nlp-detect", daemon=True).start()

    # -- producer side -----------------------------------------------------

    def submit(self, frame_id: int, jpeg_bytes: bytes) -> None:
        self._submitted_since_check += 1
        if self._in.full():
            try:
                self._in.get_nowait()  # latest-frame-wins: drop the oldest
            except queue.Empty:
                pass
            self.dropped += 1
            self._dropped_since_check += 1
        try:
            self._in.put_nowait((frame_id, jpeg_bytes))
        except queue.Full:
            self.dropped += 1  # worker fully backed up; skip this frame entirely
            self._dropped_since_check += 1

    def pending(self) -> int:
        """Frames queued but not yet processed (for quiescence detection in tests)."""
        return self._in.qsize()

    def _submit_detect(self, rgb: np.ndarray) -> None:
        if self._det_jobs.full():
            return
        try:
            self._det_jobs.put_nowait(rgb)
        except queue.Full:
            pass

    # -- consumer side -----------------------------------------------------

    def _push(self, result: dict) -> None:
        if self._aq is not None:
            self._loop.call_soon_threadsafe(self._aq.put_nowait, result)
            return
        if self._out.full():
            try:
                self._out.get_nowait()
            except queue.Empty:
                pass
        try:
            self._out.put_nowait(result)
        except queue.Full:
            pass

    async def get(self) -> dict:
        """Async result (requires attach_loop)."""
        return await self._aq.get()

    def drain(self) -> list[dict]:
        out = []
        while True:
            try:
                out.append(self._out.get_nowait())
            except queue.Empty:
                break
        return out

    # -- worker loops ------------------------------------------------------

    def _warm_thread(self) -> None:
        """Warm the worker thread's CUDA context + engine before the first real
        frame (thread-local torch init makes the first warp/decode ~0.2-0.7 s).
        Runs once per connection at thread start; failure is non-fatal."""
        try:
            import numpy as np

            eng = self.runtime._engine
            if eng is not None:
                dummy = np.zeros((256, 256, 3), dtype=np.uint8)
                with torch.inference_mode():
                    crops, new_intr, _ = eng.warp(dummy, None)
                    eng._run_core(crops, new_intr)
        except Exception:
            pass

    def _det_loop(self) -> None:
        import cv2  # noqa: F401

        while True:
            rgb = self._det_jobs.get()
            detector = self.runtime._detector
            if detector is None:
                # Runtime not loaded yet (lazy warmup) — publish nothing.
                self._det_jobs.task_done()
                continue
            try:
                det = detector.detect_xywh(rgb)
            except Exception as e:
                sys.stderr.write(f"[nlf_engine] detect error: {e}\n")
                det = None
            with self._det_lock:
                self._last_detected = det

    def _monitor(self, runtime, result: dict) -> None:
        """Feed the latency window; periodically ask the runtime to rebalance if
        the active backend is degraded vs its calibrated baseline."""
        ms = result.get("server_ms")
        if ms is not None:
            self._ms_window.append(float(ms))
        self._frames_since_check += 1
        if self._frames_since_check < self._check_every:
            return
        self._frames_since_check = 0
        submitted = self._submitted_since_check
        dropped = self._dropped_since_check
        self._submitted_since_check = 0
        self._dropped_since_check = 0
        if not self._ms_window:
            return
        arr = np.asarray(list(self._ms_window))
        drop_rate = dropped / submitted if submitted > 0 else 0.0
        rb = getattr(runtime, "rebalance_if_degraded", None)
        if rb is not None:
            try:
                rb(float(arr.mean()), float(np.percentile(arr, 95)), drop_rate)
            except Exception as e:
                sys.stderr.write(f"[nlf_engine] rebalance check failed: {e}\n")

    def _worker_loop(self) -> None:
        import cv2

        runtime = self.runtime
        device = runtime._device
        # The engine is set lazily by the 'warmup' WS message; wait for it, then
        # warm this thread's CUDA context so the FIRST real frame is fast (a cold
        # worker thread costs ~1 s on its first warp/decode). The viewer sends
        # frames one at a time and waits for each pose, so this warm completes
        # before the first frame arrives.
        for _ in range(1200):  # up to ~60 s
            if runtime._engine is not None:
                break
            time.sleep(0.05)
        self._warm_thread()
        while True:
            frame_id, jpeg = self._in.get()
            t0 = time.perf_counter()
            try:
                bgr = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
                if bgr is None:
                    raise ValueError("jpeg decode failed")
                h, w = bgr.shape[:2]
                m = max(h, w)
                if m > self.max_side:
                    s = self.max_side / float(m)
                    bgr = cv2.resize(bgr, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
                    h, w = bgr.shape[:2]
                rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

                # Async detection: if a new box is due, queue YOLO on its own
                # thread and keep using the latest published box for this frame.
                tracker = runtime._tracker
                if tracker.needs_detect():
                    self._submit_detect(rgb)
                with self._det_lock:
                    det = self._last_detected
                xywh = tracker.update(h, w, det)
                box = tracker.as_torch(xywh, device)
                result = runtime.infer_rgb(rgb, box=box, skip_detect=True)
            except Exception as e:
                # Sanitize: some providers (e.g. DML on a pt-BR Windows) embed
                # non-UTF-8 mojibake in errors that breaks json.dumps/WS send.
                err = f"{type(e).__name__}: {e}"
                result = {"ok": False, "error": err.encode("utf-8", "replace").decode("utf-8", "replace")}
            result["frame_id"] = frame_id
            result["type"] = "pose"
            result["server_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
            self._push(result)
            self._monitor(runtime, result)
