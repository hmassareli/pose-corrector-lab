#!/usr/bin/env python3
"""Deep probe: full NLF-S SMPL fit params on the boxing benchmark sequence.

Runs detect_smpl_batched (YOLO + fit) on every benchmark image and records:

  - pose   (1,72)  SMPL axis-angle params: global_orient(3) + 23 body joints(69)
  - betas  (1,10)  SMPL shape params
  - trans  (1,3)   root translation
  - joints3d (1,24,3)  fitted SMPL joints (same params, same space)

and the fast-path joints (estimate_poses_batched) for the same image, then
reports sanity stats: pose-norm range across the sequence, betas consistency,
trans range, and fitted-vs-fast joint distance. Also times both paths fairly
(inside torch.inference_mode).

This validates whether the rotation params are usable signal for retarget /
avatar (spine, shoulder, elbow, wrist, hip articulation) — probe only.
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
DEFAULT_OUT = LAB_ROOT / "experiments" / "nlf_rotations_fit" / "report.json"

SMPL24_NAMES = [
    "pelvis", "left_hip", "right_hip", "spine1", "left_knee", "right_knee",
    "spine2", "left_ankle", "right_ankle", "spine3", "left_foot", "right_foot",
    "neck", "left_collar", "right_collar", "head", "left_shoulder", "right_shoulder",
    "left_elbow", "right_elbow", "left_wrist", "right_wrist", "left_hand", "right_hand",
]
# SMPL body joints whose axis-angle block (pose) drives articulation.
ROT_JOINT_NAMES = ["global_orient"] + [
    "left_hip", "right_hip", "spine1", "left_knee", "right_knee", "spine2",
    "left_ankle", "right_ankle", "spine3", "left_foot", "right_foot", "neck",
    "left_collar", "right_collar", "head", "left_shoulder", "right_shoulder",
    "left_elbow", "right_elbow", "left_wrist", "right_wrist", "left_hand",
    "right_hand",
]


def list_images(path: Path) -> list[Path]:
    return [p for p in sorted(path.iterdir()) if p.suffix.lower() in {".jpg", ".jpeg", ".png"}]


def bench(fn, n: int, warm: int = 3, device: str = "cpu") -> dict[str, float]:
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
    return {"mean_ms": round(float(a.mean()), 3), "p95_ms": round(float(np.percentile(a, 95)), 3)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    ap.add_argument("--images", type=Path, default=DEFAULT_IMAGES)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--timing-runs", type=int, default=10)
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = ap.parse_args()

    images = list_images(args.images)
    if args.limit > 0:
        images = images[: args.limit]
    if not images:
        raise SystemExit(f"no images under {args.images}")
    if not args.model.is_file():
        raise SystemExit(f"missing model: {args.model}")

    model = load_nlf(args.model, args.device)
    weights24, _ = get_joint_weights(model, "joints24")

    items = []
    pose_norms = []
    betas_rows = []
    fitted_vs_fast = []
    for image_path in images:
        bgr = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if bgr is None:
            continue
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        img = (
            torch.from_numpy(np.ascontiguousarray(rgb))
            .permute(2, 0, 1)
            .to(args.device)
            .contiguous()
            .unsqueeze(0)
        )
        with torch.inference_mode():
            pred = model.detect_smpl_batched(img)
            fast = estimate_joints24(model, rgb, weights24, device=args.device, num_aug=1)
        if not pred or not pred.get("pose") or len(pred["pose"]) == 0:
            items.append({"image": image_path.name, "ok": False})
            continue
        pose = pred["pose"][0][0].detach().float().cpu().numpy()          # (72,)
        betas = pred["betas"][0][0].detach().float().cpu().numpy()        # (10,)
        trans = pred["trans"][0][0].detach().float().cpu().numpy()        # (3,)
        joints3d = pred["joints3d"][0][0].detach().float().cpu().numpy()  # (24,3)
        ok_fast = fast is not None
        if ok_fast:
            dist = float(np.linalg.norm(joints3d - fast, axis=-1).mean())
            fitted_vs_fast.append(dist)
        pose_norms.append(float(np.linalg.norm(pose)))
        betas_rows.append(betas.tolist())
        items.append(
            {
                "image": image_path.name,
                "ok": True,
                "pose": [round(float(x), 6) for x in pose],
                "betas": [round(float(x), 6) for x in betas],
                "trans": [round(float(x), 6) for x in trans],
                "joints3d": [[round(float(c), 4) for c in j] for j in joints3d],
                "fast_joints3d": (
                    [[round(float(c), 4) for c in j] for j in fast] if ok_fast else None
                ),
                "fitted_vs_fast_mean_mm": round(dist, 3) if ok_fast else None,
            }
        )

    # Timing on the first image (both paths, fair inference-mode bench).
    first = cv2.cvtColor(cv2.imread(str(images[0]), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
    img0 = (
        torch.from_numpy(np.ascontiguousarray(first))
        .permute(2, 0, 1)
        .to(args.device)
        .contiguous()
        .unsqueeze(0)
    )
    timing = {
        "fast_joints24": bench(
            lambda: estimate_joints24(model, first, weights24, device=args.device, num_aug=1),
            n=args.timing_runs,
            device=args.device,
        ),
        "full_detect_smpl": bench(
            lambda: model.detect_smpl_batched(img0),
            n=args.timing_runs,
            device=args.device,
        ),
    }

    pose_norms = np.asarray(pose_norms)
    ok_items = [i for i in items if i.get("ok")]
    rot_per_joint = {}
    if ok_items:
        pose_mat = np.stack([np.asarray(i["pose"], dtype=np.float64) for i in ok_items])  # (N,72)
        for k, name in enumerate(ROT_JOINT_NAMES):
            blocks = pose_mat[:, 3 * k : 3 * k + 3]
            rot_per_joint[name] = round(
                float(np.degrees(np.linalg.norm(blocks, axis=-1).mean())), 2
            )

    report = {
        "purpose": "deep probe: NLF-S full fit rotation params on boxing sequence",
        "device": args.device,
        "n_images": len(items),
        "n_ok": sum(1 for i in items if i.get("ok")),
        "rot_joint_names": ROT_JOINT_NAMES,
        "pose_axis_angle_per_joint": [
            f"{ROT_JOINT_NAMES[k]} = pose[{3*k}:{3*k+3}]" for k in range(24)
        ],
        "timing_ms": timing,
        "stats": {
            "pose_norm_mean": round(float(pose_norms.mean()), 4) if len(pose_norms) else None,
            "pose_norm_min": round(float(pose_norms.min()), 4) if len(pose_norms) else None,
            "pose_norm_max": round(float(pose_norms.max()), 4) if len(pose_norms) else None,
            "pose_global_orient_deg": {
                "min": round(float(np.degrees(np.linalg.norm(i["pose"][0:3]))), 2)
                for i in items
                if i.get("ok")
            } or None,
            "betas_std": (
                round(float(np.std(np.asarray(betas_rows), axis=0).mean()), 4)
                if betas_rows
                else None
            ),
            "trans_range_mm": (
                {
                    "x": round(float(np.ptp([i["trans"][0] for i in items if i.get("ok")])), 3),
                    "y": round(float(np.ptp([i["trans"][1] for i in items if i.get("ok")])), 3),
                    "z": round(float(np.ptp([i["trans"][2] for i in items if i.get("ok")])), 3),
                }
                if items
                else None
            ),
            "fitted_vs_fast_joint_mean_mm": (
                round(float(np.mean(fitted_vs_fast)), 3) if fitted_vs_fast else None
            ),
            "per_joint_rotation_norm_mean_deg": rot_per_joint,
        },
        "items": items,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(json.dumps(
        {
            "n_ok": report["n_ok"],
            "timing_ms": timing,
            "stats": report["stats"],
        },
        indent=2,
    ))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
