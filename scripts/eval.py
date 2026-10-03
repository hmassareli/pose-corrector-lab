#!/usr/bin/env python3
"""Evaluate a checkpoint on val/test window npz."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import torch
from torch.utils.data import DataLoader

LAB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB_ROOT / "src"))
sys.path.insert(0, str(LAB_ROOT / "scripts"))

from pose_lab.data import WindowNPZDataset, feature_ablation_kwargs  # noqa: E402
from pose_lab.logging_utils import write_json  # noqa: E402
from pose_lab.models import build_model  # noqa: E402
from train import eval_delta  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", type=Path, required=True)
    ap.add_argument("--split", choices=("val", "test"), default="test")
    ap.add_argument("--dataset-dir", type=Path, default=LAB_ROOT / "data" / "dataset")
    ap.add_argument("--batch-size", type=int, default=128)
    ap.add_argument("--device", type=str, default="cuda" if torch.cuda.is_available() else "cpu")
    args = ap.parse_args()

    ckpt = torch.load(args.ckpt, map_location="cpu", weights_only=False)
    cfg = ckpt.get("cfg") or {}
    F = int(ckpt.get("F") or 101)
    device = torch.device(args.device)
    model = build_model(cfg, in_dim=F).to(device)
    model.load_state_dict(ckpt["model"])
    fcfg = cfg.get("features") or {}
    feat_kw = feature_ablation_kwargs(fcfg)
    if any(
        feat_kw[k]
        for k in (
            "zero_accel",
            "zero_2d",
            "zero_ipsi",
            "zero_bones",
            "zero_inv_conf",
            "multilag",
        )
    ):
        print(
            "[eval] features "
            f"zero_accel={feat_kw['zero_accel']} zero_2d={feat_kw['zero_2d']} "
            f"zero_ipsi={feat_kw['zero_ipsi']} zero_bones={feat_kw['zero_bones']} "
            f"zero_inv_conf={feat_kw['zero_inv_conf']} multilag={feat_kw['multilag']}",
            flush=True,
        )
    ds = WindowNPZDataset(
        args.dataset_dir / f"{args.split}.npz",
        mirror_p=0.0,
        **feat_kw,
    )
    loader = DataLoader(ds, batch_size=args.batch_size, shuffle=False)
    metrics = eval_delta(model, loader, device)
    # Tag with split-prefixed keys for leaderboard consumers.
    metrics = {
        **metrics,
        "split": args.split,
        f"{args.split}_hard_mm": metrics.get("mpjpe_hard_mm"),
        f"{args.split}_mp_hard_mm": metrics.get("mpjpe_mp_hard_mm"),
        f"{args.split}_hard_impr_pct": metrics.get("hard_improvement_pct"),
    }
    out = args.ckpt.parent.parent / "eval" / f"{args.split}_{args.ckpt.stem}.json"
    # Keep legacy name too for quick inspection.
    legacy = args.ckpt.parent.parent / "eval" / f"{args.split}_final.json"
    write_json(out, metrics)
    write_json(legacy, metrics)
    print(json.dumps(metrics, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
