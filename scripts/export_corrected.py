#!/usr/bin/env python3
"""Run best_hard.pt on paired clips → data/corrected/<clip_id>/ for the web viewer."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

import os

import numpy as np
import torch

LAB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB_ROOT / "src"))

from pose_lab.align import body_frame_from_pose, from_body_frame, to_body_frame  # noqa: E402
from pose_lab.data import apply_feature_ablation  # noqa: E402
from pose_lab.features import build_feature_sequence  # noqa: E402
from pose_lab.models import build_model  # noqa: E402
from pose_lab.skeleton import DELTA_DIM, N_TARGETS, TARGET_IDX  # noqa: E402
from pose_lab.timebase import CANONICAL_FPS, resample_to_n_frames  # noqa: E402


def _clip_ids_for_args(args: argparse.Namespace) -> list[str]:
    if args.split == "all":
        clip_ids = sorted(
            p.name for p in args.paired.iterdir() if (p / "mp_30.npy").is_file()
        )
    else:
        man = json.loads(args.manifest.read_text(encoding="utf-8"))
        clip_ids = list(man["splits"][args.split])
    if args.clip:
        want = set(args.clip)
        clip_ids = [c for c in clip_ids if c in want]
    if args.limit > 0:
        clip_ids = clip_ids[: args.limit]
    return clip_ids


def _source_grid(paired_dir: Path, n_30: int) -> tuple[float, int]:
    paired_meta: dict = {}
    pm_path = paired_dir / "meta.json"
    if pm_path.is_file():
        paired_meta = json.loads(pm_path.read_text(encoding="utf-8"))
    fps_src = float(paired_meta.get("fps_src") or CANONICAL_FPS)
    n_src = int(paired_meta.get("n_frames_src_mp") or 0)
    if n_src <= 0:
        n_src = int(round((n_30 - 1) * fps_src / CANONICAL_FPS)) + 1
    return fps_src, n_src


def _to_source_fps(corr_30: np.ndarray, fps_src: float, n_src: int) -> np.ndarray:
    if abs(fps_src - CANONICAL_FPS) < 1e-6 and n_src == corr_30.shape[0]:
        return corr_30
    corr, _ = resample_to_n_frames(corr_30, CANONICAL_FPS, fps_src, n_src)
    return corr


def _resample_existing(args: argparse.Namespace) -> None:
    """Map already-exported 30 Hz corrected joints onto the MediaPipe frame grid."""
    clip_ids = _clip_ids_for_args(args)
    print(f"[export] resample-only clips={len(clip_ids)}")
    t0 = time.time()
    for i, cid in enumerate(clip_ids, 1):
        out_dir = args.out / cid
        jpath = out_dir / "joints3d.npy"
        if not jpath.is_file():
            print(f"[{i}/{len(clip_ids)}] SKIP missing {cid}", flush=True)
            continue
        corr_30 = np.load(jpath)
        meta_path = out_dir / "meta.json"
        meta: dict = {}
        if meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        # Already on source grid?
        fps_src, n_src = _source_grid(args.paired / cid, int(corr_30.shape[0]))
        if int(meta.get("n_frames") or 0) == n_src and abs(float(meta.get("fps") or 0) - fps_src) < 0.05:
            if corr_30.shape[0] == n_src:
                print(f"[{i}/{len(clip_ids)}] {cid} already T={n_src}", flush=True)
                continue
        # If file is already source-length but meta still says 30, just fix meta.
        if corr_30.shape[0] == n_src and int(meta.get("n_frames_infer_30") or 0) == 0:
            # Ambiguous: could be source-rate already. Prefer paired n_frames_30 check.
            n_30 = int(
                (json.loads((args.paired / cid / "meta.json").read_text(encoding="utf-8")).get(
                    "n_frames_30"
                )
                if (args.paired / cid / "meta.json").is_file()
                else 0)
            )
            if n_30 and corr_30.shape[0] != n_30:
                meta.update(
                    {
                        "fps": fps_src,
                        "fps_infer": CANONICAL_FPS,
                        "n_frames": int(corr_30.shape[0]),
                        "n_frames_infer_30": n_30,
                    }
                )
                meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
                vp = out_dir / "viewer_payload.json"
                if vp.is_file():
                    vp.unlink()
                print(f"[{i}/{len(clip_ids)}] {cid} meta-fixed T={corr_30.shape[0]}", flush=True)
                continue
        corr = _to_source_fps(corr_30, fps_src, n_src)
        np.save(jpath, corr.astype(np.float32))
        meta.update(
            {
                "clip_id": cid,
                "source": "corrected",
                "fps": fps_src,
                "fps_infer": CANONICAL_FPS,
                "n_frames": int(corr.shape[0]),
                "n_frames_infer_30": int(corr_30.shape[0]),
                "resampled_unix": time.time(),
            }
        )
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        vp = out_dir / "viewer_payload.json"
        if vp.is_file():
            vp.unlink()
        print(
            f"[{i}/{len(clip_ids)}] {cid} T30={corr_30.shape[0]} -> T={corr.shape[0]} @ {fps_src:.3f}fps",
            flush=True,
        )
    print(f"[export] resample-only done elapsed={time.time() - t0:.1f}s")


def apply_delta(mp_pose: np.ndarray, delta: np.ndarray) -> np.ndarray:
    """mp_pose (J,3), delta (DELTA_DIM,) in *uncorrected* MP body frame → corrected world.

    Body frame is built once from the original MP pose (shoulders as anchor). All
    target deltas — including shoulder residuals — are applied in that same frame;
    we never rebuild the frame from already-corrected shoulders mid-apply.
    """
    R, scale, origin = body_frame_from_pose(mp_pose)
    mp_b = to_body_frame(mp_pose, R, scale, origin)
    d = np.asarray(delta, dtype=np.float64).reshape(N_TARGETS, 3)
    assert d.size == DELTA_DIM
    for k, ji in enumerate(TARGET_IDX):
        mp_b[ji] = mp_b[ji] + d[k]
    out = mp_pose.copy()
    for ji in TARGET_IDX:
        out[ji] = from_body_frame(mp_b[ji : ji + 1], R, scale, origin)[0]
    return out


@torch.no_grad()
def correct_clip(
    model: torch.nn.Module,
    device: torch.device,
    mp: np.ndarray,
    conf: np.ndarray,
    mp_2d: np.ndarray | None,
    T: int,
    gate_conf: float,
    gate_eps: float,
    *,
    zero_accel: bool = False,
    zero_2d: bool = False,
) -> np.ndarray:
    feats = build_feature_sequence(mp, conf, poses_2d_norm=mp_2d, fps=CANONICAL_FPS)
    feats = apply_feature_ablation(feats, zero_accel=zero_accel, zero_2d=zero_2d)
    out = mp.copy()
    # pad start with first window prediction repeated / causal warmup
    for t in range(mp.shape[0]):
        start = max(0, t - T + 1)
        window = feats[start : t + 1]
        if window.shape[0] < T:
            pad = np.repeat(window[:1], T - window.shape[0], axis=0)
            window = np.concatenate([pad, window], axis=0)
        x = torch.from_numpy(window[None].astype(np.float32)).to(device)
        delta = model(x)["delta"][0].cpu().numpy()
        if conf[t, TARGET_IDX].mean() >= gate_conf and float(np.linalg.norm(delta)) < gate_eps:
            continue
        out[t] = apply_delta(mp[t], delta)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--ckpt",
        type=Path,
        default=LAB_ROOT / "runs" / "20260725_222943_gru_v1" / "checkpoints" / "best_hard.pt",
    )
    ap.add_argument("--manifest", type=Path, default=LAB_ROOT / "data" / "splits" / "manifest.json")
    ap.add_argument("--split", default="test", choices=("train", "val", "test", "all"))
    ap.add_argument("--paired", type=Path, default=LAB_ROOT / "data" / "paired")
    ap.add_argument("--mediapipe", type=Path, default=LAB_ROOT / "data" / "mediapipe")
    ap.add_argument("--out", type=Path, default=LAB_ROOT / "data" / "corrected")
    ap.add_argument("--limit", type=int, default=0, help="0=all clips in split")
    ap.add_argument("--clip", action="append", default=[], help="Only these clip ids (repeatable)")
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    ap.add_argument("--no-gate", action="store_true")
    ap.add_argument(
        "--resample-only",
        action="store_true",
        help="Resample existing out/*/joints3d.npy (30 Hz) onto source fps; no model",
    )
    args = ap.parse_args()

    if args.resample_only:
        _resample_existing(args)
        return

    ckpt = torch.load(args.ckpt, map_location="cpu", weights_only=False)
    cfg = ckpt.get("cfg") or {}
    F = int(ckpt.get("F") or 101)
    T = int(ckpt.get("T") or 15)
    device = torch.device(args.device)
    model = build_model(cfg, in_dim=F).to(device)
    model.load_state_dict(ckpt["model"])
    model.eval()

    ig = cfg.get("inference_gate") or {}
    gate_conf = 0.0 if args.no_gate else float(ig.get("conf_high", 0.85))
    gate_eps = 0.0 if args.no_gate else float(ig.get("delta_eps", 0.02))
    fcfg = cfg.get("features") or {}
    zero_accel = bool(fcfg.get("zero_accel", False))
    zero_2d = bool(fcfg.get("zero_2d", False))

    clip_ids = _clip_ids_for_args(args)
    if args.clip:
        missing = set(args.clip) - set(clip_ids)
        if missing:
            print(f"[export] warn: not in split/paired: {sorted(missing)}")

    args.out.mkdir(parents=True, exist_ok=True)
    print(f"[export] clips={len(clip_ids)} T={T} F={F} gate_conf={gate_conf} eps={gate_eps}")
    t0 = time.time()
    for i, cid in enumerate(clip_ids, 1):
        d = args.paired / cid
        mp = np.load(d / "mp_30.npy")
        conf = np.load(d / "conf_30.npy")
        mp_2d = np.load(d / "mp_2d_30.npy") if (d / "mp_2d_30.npy").is_file() else None
        corr_30 = correct_clip(
            model,
            device,
            mp,
            conf,
            mp_2d,
            T,
            gate_conf,
            gate_eps,
            zero_accel=zero_accel,
            zero_2d=zero_2d,
        )

        # Viewer joints must share the source-video / MediaPipe frame grid.
        # Inference stays on paired 30 Hz; resample back for scrubbing parity.
        fps_src, n_src = _source_grid(d, int(corr_30.shape[0]))
        corr = _to_source_fps(corr_30, fps_src, n_src)

        out_dir = args.out / cid
        out_dir.mkdir(parents=True, exist_ok=True)
        np.save(out_dir / "joints3d.npy", corr.astype(np.float32))
        # video for viewer
        src = args.mediapipe / cid / "source.mp4"
        if not src.is_file():
            src = d / "source.mp4" if (d / "source.mp4").is_file() else None
        dst = out_dir / "source.mp4"
        if src and src.is_file() and not dst.exists():
            try:
                os.link(src, dst)
            except OSError:
                shutil.copy2(src, dst)

        meta = {
            "clip_id": cid,
            "source": "corrected",
            "teacher_ckpt": str(args.ckpt),
            "fps": fps_src,
            "fps_infer": CANONICAL_FPS,
            "n_frames": int(corr.shape[0]),
            "n_frames_infer_30": int(corr_30.shape[0]),
            "gate_conf": gate_conf,
            "gate_eps": gate_eps,
            "created_unix": time.time(),
        }
        (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        # drop stale payload cache
        vp = out_dir / "viewer_payload.json"
        if vp.is_file():
            vp.unlink()
        print(
            f"[{i}/{len(clip_ids)}] {cid} T30={corr_30.shape[0]} -> T={corr.shape[0]} @ {fps_src:.3f}fps",
            flush=True,
        )

    print(f"[export] done elapsed={time.time()-t0:.1f}s -> {args.out}")


if __name__ == "__main__":
    main()
