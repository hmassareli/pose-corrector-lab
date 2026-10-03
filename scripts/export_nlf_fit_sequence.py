#!/usr/bin/env python3
"""Export NLF-S full SMPL fit (rotations + mesh) per frame of a video.

For each frame: detect_smpl_batched (YOLO + fit) → pose, betas, trans, fitted
joints3d, vertices3d; plus the fast-path x55 joints (what the game uses today)
for a contrast panel. --model-name smplx gives the full SMPL-X mesh (10475
verts, articulated hands) whose faces live in SMPLX_NEUTRAL.npz.

Saves one npz: experiments/nlf_fit_webcam1/fit_smplx.npz
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import torch

LAB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB_ROOT / "scripts"))

from nlf_fast_path import SMPLX55_JOINT_NAMES, estimate_joints24, get_joint_weights, load_nlf  # noqa: E402

DEFAULT_MODEL = LAB_ROOT / "data" / "models" / "nlf" / "nlf_s_multi_0.2.2.torchscript"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--video", type=Path, default=LAB_ROOT / "data" / "input" / "henrique_training" / "henrique_webcam_1.mp4")
    ap.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    ap.add_argument("--out", type=Path, default=LAB_ROOT / "experiments" / "nlf_fit_webcam1" / "fit_smplx.npz")
    ap.add_argument("--model-name", default="smplx", choices=("smpl", "smplx"))
    ap.add_argument("--max-frames", type=int, default=0, help="0 = all")
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = ap.parse_args()

    if not args.video.is_file():
        raise SystemExit(f"missing video: {args.video}")
    model = load_nlf(args.model, args.device)
    weights55, _ = get_joint_weights(model, "smplx55")

    cap = cv2.VideoCapture(str(args.video))
    if not cap.isOpened():
        raise SystemExit(f"cannot open {args.video}")

    verts, poses, betas, trans, fit_joints, x55, ok_flags = [], [], [], [], [], [], []
    t0 = time.perf_counter()
    idx = 0
    while True:
        if args.max_frames and idx >= args.max_frames:
            break
        ok, bgr = cap.read()
        if not ok:
            break
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
            if args.model_name == "smplx":
                box = pred["boxes"][0].detach().float()
                par = model._estimate_parametric_batched(
                    img, [box], intrinsic_matrix=None, distortion_coeffs=None,
                    extrinsic_matrix=None, world_up_vector=None, default_fov_degrees=55.0,
                    internal_batch_size=1, antialias_factor=1, num_aug=1,
                    rot_aug_max_degrees=0.0, suppress_implausible_poses=True,
                    beta_regularizer=0.1, beta_regularizer2=0.1, model_name="smplx",
                )
                pred = par
            j55 = estimate_joints24(model, rgb, weights55, device=args.device, num_aug=1)
        ok_fit = bool(pred and pred.get("pose") and len(pred["pose"]) > 0)
        ok_flags.append(ok_fit)
        if ok_fit:
            verts.append(pred["vertices3d"][0][0].detach().float().cpu().numpy().astype(np.float16))
            poses.append(pred["pose"][0][0].detach().float().cpu().numpy())
            betas.append(pred["betas"][0][0].detach().float().cpu().numpy())
            trans.append(pred["trans"][0][0].detach().float().cpu().numpy())
            fit_joints.append(pred["joints3d"][0][0].detach().float().cpu().numpy())
        else:
            n_v = 10475 if args.model_name == "smplx" else 6890
            n_p = 165 if args.model_name == "smplx" else 72
            n_j = 55 if args.model_name == "smplx" else 24
            verts.append(np.zeros((n_v, 3), dtype=np.float16))
            poses.append(np.zeros(n_p, dtype=np.float32))
            betas.append(np.zeros(10, dtype=np.float32))
            trans.append(np.zeros(3, dtype=np.float32))
            fit_joints.append(np.zeros((n_j, 3), dtype=np.float32))
        x55.append(np.asarray(j55, dtype=np.float32) if j55 is not None else np.zeros((55, 3), dtype=np.float32))
        idx += 1
        if idx % 100 == 0:
            el = time.perf_counter() - t0
            print(f"[export] {idx} frames ({el:.0f}s, {el/idx*1000:.0f} ms/f)", flush=True)
    cap.release()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        args.out,
        verts=np.stack(verts),
        pose=np.stack(poses),
        betas=np.stack(betas),
        trans=np.stack(trans),
        fit_joints=np.stack(fit_joints),
        x55=np.stack(x55),
        ok=np.asarray(ok_flags, dtype=bool),
        smplx55_names=np.asarray(SMPLX55_JOINT_NAMES),
    )
    n_ok = sum(ok_flags)
    print(f"wrote {args.out} ({idx} frames, {n_ok} fit ok) in {time.perf_counter()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
