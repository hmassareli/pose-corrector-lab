#!/usr/bin/env python3
"""Measure the isolated NLF-S fit-head cost.

The question: how much does adding SMPL rotations (pose/betas/trans) to the
runtime cost, beyond what the runtime already does?

Three estimation paths on the SAME image + box (no YOLO, torch, same GPU):

  1. nonparam fast    — _estimate_poses_batched with 24-joint weights
  2. nonparam dense   — _estimate_poses_batched with x55+surface1024 weights
                        (the query set the runtime dense mode already runs)
  3. parametric       — _estimate_parametric_batched (canonical query + SMPL fit)

  pure_fit_ms     = parametric - dense      (what adding rotations costs)
  dense_query_ms  = dense - fast            (the extra canonical points)
  full_nonparam   = parametric - fast

Sanity: parametric pose/betas/trans must match detect_smpl_batched's fitted
outputs on the same frame (proves _estimate_parametric_batched IS the fit).

Probe only — no runtime change.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import torch

LAB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB_ROOT / "scripts"))

from nlf_fast_path import get_joint_weights, load_nlf, x55_plus_surface_weights  # noqa: E402

DEFAULT_IMAGES = LAB_ROOT / "src" / "benchmark_images"
DEFAULT_MODEL = LAB_ROOT / "data" / "models" / "nlf" / "nlf_s_multi_0.2.2.torchscript"
DEFAULT_OUT = LAB_ROOT / "experiments" / "nlf_fit_head_cost" / "report.json"

NONPARAM_ARGS = dict(
    intrinsic_matrix=None,
    distortion_coeffs=None,
    extrinsic_matrix=None,
    world_up_vector=None,
    default_fov_degrees=55.0,
    internal_batch_size=1,
    antialias_factor=1,
    num_aug=1,
    rot_aug_max_degrees=0.0,
    suppress_implausible_poses=True,
)

PARAM_ARGS = dict(
    intrinsic_matrix=None,
    distortion_coeffs=None,
    extrinsic_matrix=None,
    world_up_vector=None,
    default_fov_degrees=55.0,
    internal_batch_size=1,
    antialias_factor=1,
    num_aug=1,
    rot_aug_max_degrees=0.0,
    suppress_implausible_poses=True,
    beta_regularizer=0.1,
    beta_regularizer2=0.1,
)


def bench(fn, n: int = 10, warm: int = 3, device: str = "cpu") -> dict[str, float]:
    with torch.inference_mode():
        for _ in range(warm):
            fn()
        if device.startswith("cuda"):
            torch.cuda.synchronize()
        times: list[float] = []
        for _ in range(n):
            t0 = time.perf_counter()
            fn()
            if device.startswith("cuda"):
                torch.cuda.synchronize()
            times.append((time.perf_counter() - t0) * 1000.0)
    a = np.asarray(times)
    return {
        "mean_ms": round(float(a.mean()), 3),
        "p50_ms": round(float(np.median(a)), 3),
        "p95_ms": round(float(np.percentile(a, 95)), 3),
    }


def first_tensor_list(obj, key: str):
    """Return first element tensor (B=1 assumed) as cpu numpy, or None."""
    v = obj.get(key)
    if not v or not isinstance(v, (list, tuple)):
        return None
    t = v[0]
    if isinstance(t, torch.Tensor):
        return t.detach().float().cpu().numpy()
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    ap.add_argument("--image", type=Path, default=DEFAULT_IMAGES / "WIN_20260801_13_57_25_Pro.jpg")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--timing-runs", type=int, default=10)
    ap.add_argument("--model-name", default="smpl", choices=("smpl", "smplx"))
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = ap.parse_args()

    if not args.model.is_file():
        raise SystemExit(f"missing model: {args.model}")
    bgr = cv2.imread(str(args.image), cv2.IMREAD_COLOR)
    if bgr is None:
        raise SystemExit(f"cannot read {args.image}")
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    img = (
        torch.from_numpy(np.ascontiguousarray(rgb))
        .permute(2, 0, 1)
        .to(args.device)
        .contiguous()
        .unsqueeze(0)
    )
    model = load_nlf(args.model, args.device)
    weights24, _ = get_joint_weights(model, "joints24")
    wdense, n_x55, n_surf = x55_plus_surface_weights(model)

    # Internal methods expect xywh+conf (5 cols) for NMS; the public wrapper
    # adds the conf column itself (same convention as nlf_engine.warp). A
    # full-frame box gets rejected by the plausibility filter (batch 0), so we
    # use the detector's person box from a warmup detect_smpl_batched call.
    with torch.inference_mode():
        warm = model.detect_smpl_batched(img)
    det_box = warm["boxes"][0].detach().float()  # (1,5) xywh+conf
    box = det_box.to(args.device)

    def run_fast():
        return model._estimate_poses_batched(img, [box], weights24, **NONPARAM_ARGS)

    def run_dense():
        return model._estimate_poses_batched(img, [box], wdense, **NONPARAM_ARGS)

    def run_param():
        return model._estimate_parametric_batched(img, [box], **PARAM_ARGS, model_name=args.model_name)

    # Sanity: parametric == detect_smpl_batched fitted outputs on the same frame.
    sanity: dict = {}
    with torch.inference_mode():
        full = model.detect_smpl_batched(img)
        par = run_param()
    for key in ("pose", "betas", "trans", "joints3d", "vertices3d"):
        a = first_tensor_list(full, key)
        b = first_tensor_list(par, key)
        if a is not None and b is not None and a.shape == b.shape:
            max_diff = float(np.abs(a - b).max())
            sanity[key] = {
                "shape": list(a.shape),
                "max_abs_diff": round(max_diff, 6),
                "match": max_diff < 1e-3,
            }
        else:
            sanity[key] = {
                "full": None if a is None else list(a.shape),
                "param": None if b is None else list(b.shape),
                "match": False,
            }
    par_keys = sorted(par.keys()) if isinstance(par, dict) else []

    timing = {
        "nonparam_fast_24q": bench(run_fast, n=args.timing_runs, device=args.device),
        "nonparam_dense_1079q": bench(run_dense, n=args.timing_runs, device=args.device),
        "parametric": bench(run_param, n=args.timing_runs, device=args.device),
    }

    def sub(a: dict, b: dict) -> dict:
        return {k: round(float(a[k]) - float(b[k]), 3) for k in ("mean_ms", "p50_ms", "p95_ms")}

    report = {
        "purpose": "isolate NLF-S fit-head cost (rotations) vs what the runtime already does",
        "device": args.device,
        "model_name": args.model_name,
        "image": str(args.image),
        "box": [0.0, 0.0, float(w), float(h)],
        "n_x55": n_x55,
        "n_surf": n_surf,
        "sanity_vs_detect_smpl": sanity,
        "parametric_output_keys": par_keys,
        "timing_ms": timing,
        "deltas_ms": {
            "dense_query_extra (dense - fast)": sub(timing["nonparam_dense_1079q"], timing["nonparam_fast_24q"]),
            "PURE_FIT_HEAD (parametric - dense)": sub(timing["parametric"], timing["nonparam_dense_1079q"]),
            "full_rotations_vs_fast (parametric - fast)": sub(timing["parametric"], timing["nonparam_fast_24q"]),
        },
        "note": (
            "All three paths are torch/CUDA with the same 960x540 frame and full-frame box, "
            "no YOLO. The runtime already runs the dense query set via TRT/DML engines "
            "(features-only TRT ~1.9 ms vs ~27 ms torch), so the GPU-fit-head cost in a "
            "real engine is expected lower than this torch number."
        ),
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(
        {
            "sanity_vs_detect_smpl": sanity,
            "timing_ms": timing,
            "deltas_ms": report["deltas_ms"],
        },
        indent=2,
    ))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
