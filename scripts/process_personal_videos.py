#!/usr/bin/env python3
"""Run MediaPipe and a corrector checkpoint over standalone local videos."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch

LAB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB_ROOT / "src"))

from pose_lab.data import feature_ablation_kwargs
from pose_lab.features import build_feature_sequence
from pose_lab.io import save_viewer_payload
from pose_lab.models import build_model
from pose_lab.skeleton import LAB_BONES, LAB_JOINTS
from scripts.export_corrected import correct_clip
from scripts.run_mediapipe import ensure_model, run_one


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ckpt", type=Path, required=True)
    ap.add_argument("--video", type=Path, action="append", required=True)
    ap.add_argument("--clip-id", action="append", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    ap.add_argument("--complexity", type=int, default=1, choices=(0, 1, 2))
    args = ap.parse_args()
    if len(args.video) != len(args.clip_id):
        ap.error("--clip-id must be supplied once for every --video")

    ckpt = torch.load(args.ckpt, map_location="cpu", weights_only=False)
    cfg = ckpt.get("cfg") or {}
    model = build_model(cfg, in_dim=int(ckpt.get("F") or 113)).to(args.device)
    model.load_state_dict(ckpt["model"])
    model.eval()
    ig = cfg.get("inference_gate") or {}
    feat_kw = feature_ablation_kwargs(cfg.get("features") or {})
    model_path = ensure_model(args.complexity)

    for clip_id, video in zip(args.clip_id, args.video, strict=True):
        mp_dir = args.out / "mediapipe" / clip_id
        corr_dir = args.out / "corrected" / clip_id
        meta = run_one(model_path, video, mp_dir, args.complexity)
        mp = np.load(mp_dir / "joints3d.npy").astype(np.float32)
        mp[..., 1] *= -1.0
        mp[..., 2] *= -1.0
        conf = np.load(mp_dir / "conf.npy").astype(np.float32)
        j2 = np.load(mp_dir / "joints2d.npy").astype(np.float32)
        j2[..., 0] /= max(float(meta["width"]), 1.0)
        j2[..., 1] /= max(float(meta["height"]), 1.0)
        corr = correct_clip(
            model,
            torch.device(args.device),
            mp,
            conf,
            j2,
            int(ckpt.get("T") or 15),
            float(ig.get("conf_high", 0.85)),
            float(ig.get("delta_eps", 0.02)),
            feat_kw=feat_kw,
        )
        corr_dir.mkdir(parents=True, exist_ok=True)
        np.save(corr_dir / "joints3d.npy", corr.astype(np.float32))
        (corr_dir / "meta.json").write_text(
            json.dumps({"clip_id": clip_id, "source": str(video.resolve()), **meta}, indent=2),
            encoding="utf-8",
        )
        save_viewer_payload(
            corr_dir / "viewer_payload.json",
            video_url=f"/media/{clip_id}/source.mp4",
            joints=corr,
            fps=float(meta["fps"]),
            bones=LAB_BONES,
            joint_names=LAB_JOINTS,
            title=f"Corrected - {clip_id}",
        )
        print(f"[personal] {clip_id}: frames={corr.shape[0]} -> {corr_dir}", flush=True)


if __name__ == "__main__":
    main()