#!/usr/bin/env python3
"""Probe: does the NLF-S TorchScript model expose SMPL rotation parameters?

The fast path (estimate_poses_batched) reads only `poses3d` (joints). The full
API (detect_smpl_batched) does YOLO + SMPL fit internally. This probe answers:

  1. What does detect_smpl_batched return beyond joints (keys + shapes)?
  2. What does estimate_poses_batched return beyond poses3d?
  3. Are rotation params (axis-angle / rot6d / betas / global_orient / body_pose /
     hand_pose / expression / transl / verts) present in any output?
  4. What does the full path cost vs the fast path on the same image?

Probe only: no viewer or runtime change. Writes a JSON report under experiments/.
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

from nlf_fast_path import estimate_joints24, get_joint_weights, load_nlf  # noqa: E402

DEFAULT_IMAGES = LAB_ROOT / "src" / "benchmark_images"
DEFAULT_MODEL = LAB_ROOT / "data" / "models" / "nlf" / "nlf_s_multi_0.2.2.torchscript"
DEFAULT_OUT = LAB_ROOT / "experiments" / "nlf_rotations_probe" / "report.json"

# Keys that would carry rotation / shape / mesh info if present.
ROTATION_HINT_KEYS = (
    "rot", "pose", "orient", "beta", "shape", "transl", "trans", "scale",
    "verts", "vert", "faces", "param", "global", "expression", "jaw", "hand",
    "fit", "smpl", "posed", "canonical",
)


def list_images(path: Path) -> list[Path]:
    return [p for p in sorted(path.iterdir()) if p.suffix.lower() in {".jpg", ".jpeg", ".png"}]


def describe(v, depth: int = 0) -> dict:
    """JSON-safe description of a TorchScript output value (cap depth/size)."""
    if depth > 4:
        return {"kind": "depth-limit"}
    if isinstance(v, torch.Tensor):
        return {"kind": "tensor", "shape": list(v.shape), "dtype": str(v.dtype), "device": str(v.device)}
    if isinstance(v, (list, tuple)):
        return {"kind": type(v).__name__, "len": len(v), "items": [describe(x, depth + 1) for x in v[:4]]}
    if isinstance(v, dict):
        return {
            "kind": "dict",
            "keys": {str(k): describe(x, depth + 1) for k, x in list(v.items())[:10]},
        }
    if isinstance(v, (int, float, str, bool)) or v is None:
        return {"kind": type(v).__name__, "value": v}
    return {"kind": type(v).__name__}


def find_rotation_hints(obj, path: str = "", hits: list | None = None) -> list:
    """Recursively collect paths whose key/name suggests rotation/params."""
    if hits is None:
        hits = []
    low = str(path).lower()
    if any(h in low for h in ROTATION_HINT_KEYS):
        hits.append(path)
    if isinstance(obj, dict):
        for k, v in obj.items():
            find_rotation_hints(v, f"{path}.{k}" if path else str(k), hits)
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj[:8]):
            find_rotation_hints(v, f"{path}[{i}]", hits)
    return hits


def bench(fn, n: int, warm: int = 3, device: str = "cpu") -> dict[str, float]:
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
    return {"mean_ms": round(float(a.mean()), 3), "p95_ms": round(float(np.percentile(a, 95)), 3)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    ap.add_argument("--images", type=Path, default=DEFAULT_IMAGES)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--limit", type=int, default=2)
    ap.add_argument("--timing-runs", type=int, default=10)
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = ap.parse_args()

    images = list_images(args.images)[: args.limit]
    if not images:
        raise SystemExit(f"no images under {args.images}")
    if not args.model.is_file():
        raise SystemExit(f"missing model: {args.model}")

    model = load_nlf(args.model, args.device)
    report: dict = {
        "model": str(args.model),
        "device": args.device,
        "images": [p.name for p in images],
        "purpose": "probe only; find SMPL rotation params in NLF-S outputs",
    }

    # 1. Module attributes in the TorchScript schema.
    attrs = sorted(a for a in dir(model) if not a.startswith("__"))
    report["module_attrs"] = attrs

    # 2. cano_all structure (canonical points + possibly layers).
    try:
        cano = model.cano_all
        report["cano_all"] = {str(k): describe(v) for k, v in cano.items()}
    except Exception as e:
        report["cano_all_error"] = f"{type(e).__name__}: {e}"

    bgr = cv2.imread(str(images[0]), cv2.IMREAD_COLOR)
    if bgr is None:
        raise SystemExit(f"cannot read {images[0]}")
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    img = (
        torch.from_numpy(np.ascontiguousarray(rgb))
        .permute(2, 0, 1)
        .to(args.device)
        .contiguous()
        .unsqueeze(0)
    )

    # 3. Full API: detect_smpl_batched.
    try:
        pred = model.detect_smpl_batched(img)
        report["detect_smpl_batched"] = {
            "keys": [str(k) for k in pred.keys()],
            "detail": {str(k): describe(v) for k, v in pred.items()},
        }
        report["detect_smpl_batched_rotation_hints"] = sorted(
            set(find_rotation_hints(pred, "detect_smpl_batched"))
        )
    except Exception as e:
        report["detect_smpl_batched_error"] = f"{type(e).__name__}: {e}"

    # 4. Fast path: estimate_poses_batched raw dict (not just poses3d).
    try:
        weights24, _ = get_joint_weights(model, "joints24")
        box = torch.tensor(
            [[0.0, 0.0, float(rgb.shape[1]), float(rgb.shape[0])]],
            device=args.device,
            dtype=torch.float32,
        )
        est = model.estimate_poses_batched(img, [box], weights24, num_aug=1)
        report["estimate_poses_batched"] = {
            "keys": [str(k) for k in est.keys()],
            "detail": {str(k): describe(v) for k, v in est.items()},
        }
        report["estimate_poses_batched_rotation_hints"] = sorted(
            set(find_rotation_hints(est, "estimate_poses_batched"))
        )
    except Exception as e:
        report["estimate_poses_batched_error"] = f"{type(e).__name__}: {e}"

    # 5. Timing: fast path vs full path (same first image).
    timing: dict = {}
    try:
        weights24, _ = get_joint_weights(model, "joints24")
        timing["fast_joints24"] = bench(
            lambda: estimate_joints24(model, rgb, weights24, device=args.device, num_aug=1),
            n=args.timing_runs,
            device=args.device,
        )
    except Exception as e:
        timing["fast_joints24_error"] = f"{type(e).__name__}: {e}"
    try:
        timing["full_detect_smpl"] = bench(
            lambda: model.detect_smpl_batched(img),
            n=args.timing_runs,
            device=args.device,
        )
    except Exception as e:
        timing["full_detect_smpl_error"] = f"{type(e).__name__}: {e}"
    report["timing"] = timing

    # 6. Verdict.
    hints = (
        report.get("detect_smpl_batched_rotation_hints", [])
        + report.get("estimate_poses_batched_rotation_hints", [])
    )
    report["verdict"] = {
        "rotation_param_paths_found": bool(hints),
        "paths": hints,
        "fast_path_only_joints": "poses3d" in report.get("estimate_poses_batched", {}).get("keys", [])
        and len(report.get("estimate_poses_batched", {}).get("keys", [])) == 1,
        "note": (
            "Paths are matched by name only; a hit still needs manual shape check "
            "before use (e.g. axis-angle (B,J,3) vs rot6d (B,J,6) vs quaternion)."
        ),
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"verdict": report["verdict"], "timing": timing, "module_attrs": attrs}, indent=2))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
