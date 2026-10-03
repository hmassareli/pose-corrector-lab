#!/usr/bin/env python3
"""Compare the fast NLF SMPL24 and SMPL-X55 queries on still images.

This is a probe only: it does not change the viewer or runtime pose path.
It writes named root-centered points and per-query CUDA timing to JSON so the
retarget mapping can be verified before integrating any new joint.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import torch

LAB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB_ROOT / "scripts"))

from nlf_fast_path import (  # noqa: E402
    SMPLX55_JOINT_NAMES,
    estimate_joints24,
    get_joint_weights,
    load_nlf,
)


SMPL24_NAMES = [
    "pelvis", "left_hip", "right_hip", "spine1", "left_knee", "right_knee",
    "spine2", "left_ankle", "right_ankle", "spine3", "left_foot", "right_foot",
    "neck", "left_collar", "right_collar", "head", "left_shoulder", "right_shoulder",
    "left_elbow", "right_elbow", "left_wrist", "right_wrist", "left_hand", "right_hand",
]
DEFAULT_IMAGES = LAB_ROOT / "src" / "benchmark_images"
DEFAULT_MODEL = LAB_ROOT / "data" / "models" / "nlf" / "nlf_s_multi_0.2.2.torchscript"
DEFAULT_OUT = LAB_ROOT / "experiments" / "nlf_smplx55_probe" / "report.json"


def list_images(path: Path) -> list[Path]:
    return [p for p in sorted(path.iterdir()) if p.suffix.lower() in {".jpg", ".jpeg", ".png"}]


def cuda_timing(model, rgb: np.ndarray, weights: dict[str, torch.Tensor], device: str, n: int) -> dict[str, float]:
    for _ in range(5):
        estimate_joints24(model, rgb, weights, device=device, num_aug=1)
    if not device.startswith("cuda"):
        return {"mean_ms": float("nan"), "p95_ms": float("nan")}
    times: list[float] = []
    with torch.no_grad():
        for _ in range(n):
            start = torch.cuda.Event(enable_timing=True)
            end = torch.cuda.Event(enable_timing=True)
            start.record()
            estimate_joints24(model, rgb, weights, device=device, num_aug=1)
            end.record()
            torch.cuda.synchronize()
            times.append(float(start.elapsed_time(end)))
    return {
        "mean_ms": round(float(np.mean(times)), 3),
        "p95_ms": round(float(np.percentile(times, 95)), 3),
    }


def named_root_centered(points_mm: np.ndarray, names: list[str]) -> dict[str, list[float]]:
    points_m = np.asarray(points_mm, dtype=np.float64) / 1000.0
    points_m -= points_m[0:1]
    return {name: [round(float(value), 6) for value in point] for name, point in zip(names, points_m)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", type=Path, default=DEFAULT_IMAGES)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--timing-runs", type=int, default=20)
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = parser.parse_args()

    images = list_images(args.images)[: args.limit]
    if not images:
        raise SystemExit(f"no images under {args.images}")
    if not args.model.is_file():
        raise SystemExit(f"missing model: {args.model}")

    model = load_nlf(args.model, args.device)
    weights24, _ = get_joint_weights(model, "joints24")
    weights55, _ = get_joint_weights(model, "smplx55")
    items = []
    for image_path in images:
        bgr = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if bgr is None:
            continue
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        joints24 = estimate_joints24(model, rgb, weights24, device=args.device, num_aug=1)
        joints55 = estimate_joints24(model, rgb, weights55, device=args.device, num_aug=1)
        if joints24 is None or joints55 is None:
            items.append({"image": image_path.name, "ok": False})
            continue
        items.append({
            "image": image_path.name,
            "ok": True,
            "smpl24": named_root_centered(joints24, SMPL24_NAMES),
            "smplx55": named_root_centered(joints55, SMPLX55_JOINT_NAMES),
        })

    timing_image = cv2.cvtColor(cv2.imread(str(images[0])), cv2.COLOR_BGR2RGB)
    report = {
        "purpose": "probe only; no viewer integration",
        "device": args.device,
        "smpl24_names": SMPL24_NAMES,
        "smplx55_names": SMPLX55_JOINT_NAMES,
        "timing": {
            "smpl24": cuda_timing(model, timing_image, weights24, args.device, args.timing_runs),
            "smplx55": cuda_timing(model, timing_image, weights55, args.device, args.timing_runs),
        },
        "items": items,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["timing"], indent=2))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())