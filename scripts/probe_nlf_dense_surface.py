#!/usr/bin/env python3
"""Query every NLF SMPL point and summarize its 1,024 surface points by body region."""

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

from nlf_fast_path import estimate_joints24, load_nlf  # noqa: E402
from probe_nlf_smplx55 import SMPL24_NAMES  # noqa: E402


def root_centered(points_mm: np.ndarray, root_mm: np.ndarray) -> np.ndarray:
    return (np.asarray(points_mm, dtype=np.float64) - root_mm[None, :]) / 1000.0


def as_named(points_m: np.ndarray) -> dict[str, list[float]]:
    return {
        name: [round(float(value), 6) for value in point]
        for name, point in zip(SMPL24_NAMES, points_m)
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", type=Path, default=LAB_ROOT / "src" / "benchmark_images")
    parser.add_argument("--out", type=Path, default=LAB_ROOT / "experiments" / "nlf_dense_surface" / "report.json")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = parser.parse_args()

    images = [path for path in sorted(args.images.iterdir()) if path.suffix.lower() in {".jpg", ".jpeg", ".png"}]
    if args.limit is not None:
        images = images[: args.limit]
    if not images:
        raise SystemExit(f"no images under {args.images}")

    model = load_nlf(LAB_ROOT / "data" / "models" / "nlf" / "nlf_s_multi_0.2.2.torchscript", args.device)
    canonical = model.cano_all["smpl"]
    surface_canonical = canonical[:-24]
    joint_canonical = canonical[-24:]
    assignments = torch.cdist(surface_canonical, joint_canonical).argmin(dim=1).cpu().numpy()
    region_indices = [np.flatnonzero(assignments == index) for index in range(24)]
    if any(len(indices) == 0 for indices in region_indices):
        raise RuntimeError("a canonical body region has no assigned surface points")
    weights = model.get_weights_for_canonical_points(canonical.contiguous())

    items = []
    for image_path in images:
        bgr = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if bgr is None:
            items.append({"image": image_path.name, "ok": False})
            continue
        dense_mm = estimate_joints24(model, cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), weights, device=args.device, num_aug=1)
        if dense_mm is None or dense_mm.shape != (1048, 3):
            items.append({"image": image_path.name, "ok": False})
            continue
        root_mm = dense_mm[1024]
        surface_m = root_centered(dense_mm[:1024], root_mm)
        joints_m = root_centered(dense_mm[1024:], root_mm)
        surface_regions = np.stack([surface_m[indices].mean(axis=0) for indices in region_indices])
        items.append({
            "image": image_path.name,
            "ok": True,
            "smpl24": as_named(joints_m),
            "surface_regions": as_named(surface_regions),
        })
        print(f"[ok] {image_path.name}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({
        "method": "all 1024 SMPL surface points assigned to nearest canonical SMPL24 joint; each region is its predicted centroid",
        "surface_point_count": 1024,
        "region_sizes": {name: int(len(indices)) for name, indices in zip(SMPL24_NAMES, region_indices)},
        "items": items,
    }, indent=2), encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())