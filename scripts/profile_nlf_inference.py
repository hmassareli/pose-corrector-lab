#!/usr/bin/env python3
"""Profile NLF-S TorchScript: full detect_smpl vs joints-only full-frame fast path.

Usage:
  python scripts/profile_nlf_inference.py --device cuda --n 40
  python scripts/profile_nlf_inference.py --clip burn_500_shots__shot_000__person_009

Writes experiments/nlf_speed/profile.json + updates NOTES latency section.
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
    cuda_ms,
    get_joint_weights,
    load_nlf,
    stage_breakdown,
)


def resolve_video(mp_dir: Path) -> Path | None:
    src = mp_dir / "source.mp4"
    if src.is_file():
        return src
    meta_path = mp_dir / "meta.json"
    if meta_path.is_file():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        p = Path(meta.get("source_video") or "")
        if p.is_file():
            return p
    return None


def first_rgb(clip_id: str, mp_root: Path) -> np.ndarray:
    vid = resolve_video(mp_root / clip_id)
    if vid is None:
        raise FileNotFoundError(f"no video for {clip_id}")
    cap = cv2.VideoCapture(str(vid))
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError(f"failed to read {vid}")
    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)


def short_clip(mp_root: Path, te_root: Path) -> str:
    rows = []
    for p in mp_root.iterdir():
        if not (p / "joints3d.npy").is_file():
            continue
        if not (te_root / p.name / "joints3d.npy").is_file():
            continue
        if not resolve_video(p):
            continue
        t = int(np.load(p / "joints3d.npy", mmap_mode="r").shape[0])
        rows.append((t, p.name))
    rows.sort()
    if not rows:
        raise RuntimeError("no short clips found")
    return rows[0][1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", type=Path, default=LAB_ROOT / "data/models/nlf/nlf_s_multi_0.2.2.torchscript")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--clip", default="")
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--out", type=Path, default=LAB_ROOT / "experiments/nlf_speed")
    args = ap.parse_args()

    if args.device.startswith("cuda") and not torch.cuda.is_available():
        raise SystemExit("CUDA required for this profile (or pass a cuda-capable env)")

    mp_root = LAB_ROOT / "data" / "mediapipe"
    te_root = LAB_ROOT / "data" / "teacher"
    clip_id = args.clip or short_clip(mp_root, te_root)
    rgb = first_rgb(clip_id, mp_root)
    print(f"[profile] clip={clip_id} frame={rgb.shape} model={args.model.name}", flush=True)

    model = load_nlf(args.model, args.device)
    breakdown = stage_breakdown(model, rgb, device=args.device, n=args.n)

    # Extra variants
    w24, _ = get_joint_weights(model, "joints24")
    w13, _ = get_joint_weights(model, "lab13")
    h, w = rgb.shape[:2]
    img = torch.from_numpy(rgb).permute(2, 0, 1).to(args.device).contiguous().unsqueeze(0)
    box = torch.tensor([[0.0, 0.0, float(w), float(h)]], device=args.device)

    with torch.inference_mode():
        for _ in range(5):
            model.estimate_poses_batched(img, [box], w13, num_aug=1)

    breakdown["estimate_lab13_fullframe_num_aug1"] = cuda_ms(
        lambda: model.estimate_poses_batched(img, [box], w13, num_aug=1), n=args.n
    )
    # Cold start: reload weights path cost once (informational)
    breakdown["variants"] = {
        "full_detect_smpl": "YOLO-x + ~1048 queries + SMPL fit",
        "estimate_joints24_fullframe": "no detector, 24 joint queries, num_aug=1, no fit",
        "estimate_lab13_fullframe": "no detector, 13 joint queries, num_aug=1, no fit",
    }
    breakdown["clip_id"] = clip_id
    breakdown["device"] = args.device
    if torch.cuda.is_available():
        breakdown["gpu"] = torch.cuda.get_device_name(0)
    breakdown["paper_ref"] = {
        "nlf_s_unbatched_fps_rtx3090": 79,
        "nlf_s_batched_fps_rtx3090": 410,
        "note": "paper FPS is crop-model throughput, not detect_smpl_batched",
    }

    args.out.mkdir(parents=True, exist_ok=True)
    out_json = args.out / "profile.json"
    out_json.write_text(json.dumps(breakdown, indent=2), encoding="utf-8")
    print(json.dumps(breakdown, indent=2))
    print(f"[profile] wrote {out_json}", flush=True)

    fast = breakdown["estimate_joints24_fullframe_num_aug1"]
    full = breakdown["detect_smpl_batched_full"]
    det = breakdown["detector_yolov8x"]
    lines = [
        "# NLF-S speed profile",
        "",
        f"Clip: `{clip_id}` · frame `{rgb.shape[0]}x{rgb.shape[1]}` · device `{args.device}`"
        + (f" · `{breakdown.get('gpu')}`" if breakdown.get("gpu") else ""),
        "",
        "## Latency (CUDA events, ms)",
        "",
        "| path | mean | p50 | p95 |",
        "|------|-----:|----:|----:|",
        f"| detect_smpl_batched (full) | {full['mean']:.1f} | {full['p50']:.1f} | {full['p95']:.1f} |",
        f"| YOLO-x detector only | {det['mean']:.1f} | {det['p50']:.1f} | {det['p95']:.1f} |",
        f"| **fast: estimate joints24 full-frame** | **{fast['mean']:.1f}** | **{fast['p50']:.1f}** | **{fast['p95']:.1f}** |",
        f"| estimate lab13 full-frame | {breakdown['estimate_lab13_fullframe_num_aug1']['mean']:.1f} | "
        f"{breakdown['estimate_lab13_fullframe_num_aug1']['p50']:.1f} | "
        f"{breakdown['estimate_lab13_fullframe_num_aug1']['p95']:.1f} |",
        "",
        f"30 FPS budget = 33.3 ms · fast_path_p95_ok = **{breakdown['fast_path_p95_ok']}**",
        "",
        "Paper (RTX 3090): NLF-S crop-only 79 FPS unbatched / 410 FPS batched — not full multi+fit.",
        "",
        "See `profile.json` for raw numbers.",
        "",
    ]
    (args.out / "PROFILE.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
