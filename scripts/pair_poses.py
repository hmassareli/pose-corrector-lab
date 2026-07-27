#!/usr/bin/env python3
"""Pair MediaPipe ↔ teacher: same clock @ 30 Hz, trunk-align teacher, save sequences.

Does NOT build training windows yet — that is build_dataset.py.
Outputs per clip under data/paired/<clip_id>/:
  mp_30.npy              (T, J, 3) MediaPipe @ 30 Hz (viewer/world convention)
  mp_2d_30.npy           (T, J, 2) MediaPipe 2D normalized by frame W/H
  teacher_aligned_30.npy (T, J, 3) teacher translate+scale onto MP (keeps torso yaw)
  conf_30.npy            (T, J)    MP confidence resampled
  residual_30.npy        (T, 18)   shoulder/elbow/wrist Δ* in MP body frame
  meta.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import yaml

LAB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB_ROOT / "src"))

from pose_lab.align import sequence_align_teacher_to_mp  # noqa: E402
from pose_lab.io import resolve_clip_fps  # noqa: E402
from pose_lab.labels import residual_sequence  # noqa: E402
from pose_lab.skeleton import DELTA_DIM, TARGET_JOINTS  # noqa: E402
from pose_lab.timebase import CANONICAL_FPS, resample_series  # noqa: E402


def _load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _flip_mp_to_viewer(joints: np.ndarray) -> np.ndarray:
    """Match serve_viewer / io.build_viewer_payload_from_clip convention."""
    out = joints.astype(np.float64, copy=True)
    out[..., 1] *= -1.0
    out[..., 2] *= -1.0
    return out


def _common_clip_ids(mp_root: Path, te_root: Path) -> list[str]:
    mp_ids = {p.name for p in mp_root.iterdir() if (p / "joints3d.npy").is_file()}
    te_ids = {p.name for p in te_root.iterdir() if (p / "joints3d.npy").is_file()}
    return sorted(mp_ids & te_ids)


def pair_one(
    clip_id: str,
    mp_root: Path,
    te_root: Path,
    out_root: Path,
    target_fps: float,
    skip_existing: bool,
) -> dict:
    out_dir = out_root / clip_id
    need = ("residual_30.npy", "mp_2d_30.npy", "meta.json")
    if skip_existing and all((out_dir / n).is_file() for n in need):
        res = np.load(out_dir / "residual_30.npy", mmap_mode="r")
        if res.ndim == 2 and res.shape[-1] == DELTA_DIM:
            return {"clip_id": clip_id, "status": "skip"}

    mp_dir = mp_root / clip_id
    te_dir = te_root / clip_id
    mp = np.load(mp_dir / "joints3d.npy")
    te = np.load(te_dir / "joints3d.npy")
    if mp.ndim != 3 or te.ndim != 3 or mp.shape[-1] != 3 or te.shape[-1] != 3:
        raise ValueError(f"bad shapes mp={mp.shape} te={te.shape}")

    mp_meta: dict = {}
    if (mp_dir / "meta.json").is_file():
        mp_meta = json.loads((mp_dir / "meta.json").read_text(encoding="utf-8"))
    te_meta: dict = {}
    if (te_dir / "meta.json").is_file():
        te_meta = json.loads((te_dir / "meta.json").read_text(encoding="utf-8"))

    # Prefer people clip / teacher source clock; fall back to MP meta.
    fps_mp = float(mp_meta.get("fps") or 0.0) or resolve_clip_fps(mp_dir, mp_meta, n_joints=int(mp.shape[0]))
    fps_te = resolve_clip_fps(te_dir, te_meta, n_joints=int(te.shape[0]))
    # Same source video → use one clock; if they disagree a lot, take MP duration min.
    fps_src = float(fps_mp) if abs(fps_mp - fps_te) < 0.5 else float(min(fps_mp, fps_te))

    # Both on disk are OpenCV-ish; flip into the same viewer/world frame before align.
    mp_v = _flip_mp_to_viewer(mp)
    te_v = _flip_mp_to_viewer(te)

    mp_30, t_mp = resample_series(mp_v, fps_src, target_fps)
    te_30, t_te = resample_series(te_v, fps_src, target_fps)
    T = int(min(mp_30.shape[0], te_30.shape[0]))
    mp_30 = mp_30[:T].astype(np.float32)
    te_30 = te_30[:T].astype(np.float32)
    times = t_mp[:T]

    conf_path = mp_dir / "conf.npy"
    if conf_path.is_file():
        conf = np.load(conf_path).astype(np.float64)
        conf_30, _ = resample_series(conf, fps_src, target_fps)
        conf_30 = conf_30[:T].astype(np.float32)
    else:
        conf_30 = np.ones((T, mp_30.shape[1]), dtype=np.float32)

    # 2D image landmarks → normalize by crop size (already inferred by MediaPipe).
    j2_path = mp_dir / "joints2d.npy"
    if j2_path.is_file():
        j2 = np.load(j2_path).astype(np.float64)
        w = float(mp_meta.get("width") or 0.0) or 1.0
        h = float(mp_meta.get("height") or 0.0) or 1.0
        j2n = j2.copy()
        j2n[..., 0] /= w
        j2n[..., 1] /= h
        mp_2d_30, _ = resample_series(j2n, fps_src, target_fps)
        mp_2d_30 = mp_2d_30[:T].astype(np.float32)
    else:
        mp_2d_30 = np.zeros((T, mp_30.shape[1], 2), dtype=np.float32)

    te_aligned = sequence_align_teacher_to_mp(te_30, mp_30).astype(np.float32)
    residual = residual_sequence(mp_30, te_aligned).astype(np.float32)

    out_dir.mkdir(parents=True, exist_ok=True)
    np.save(out_dir / "mp_30.npy", mp_30)
    np.save(out_dir / "mp_2d_30.npy", mp_2d_30)
    np.save(out_dir / "teacher_aligned_30.npy", te_aligned)
    np.save(out_dir / "conf_30.npy", conf_30)
    np.save(out_dir / "residual_30.npy", residual)
    meta = {
        "clip_id": clip_id,
        "fps_src": fps_src,
        "fps_mp_meta": fps_mp,
        "fps_teacher_resolved": fps_te,
        "target_fps": target_fps,
        "n_frames_src_mp": int(mp.shape[0]),
        "n_frames_src_teacher": int(te.shape[0]),
        "n_frames_30": T,
        "duration_s": float(times[-1]) if T else 0.0,
        "mp_flipped_yz": True,
        "teacher_flipped_yz": True,
        "mp_2d_normalized": True,
        "mp_2d_width": float(mp_meta.get("width") or 0.0),
        "mp_2d_height": float(mp_meta.get("height") or 0.0),
        "alignment": "trunk_translate_scale_per_frame",
        "residual_targets": list(TARGET_JOINTS),
        "residual_dim": int(DELTA_DIM),
        "body_frame_from": "uncorrected_mp_pose",
        "created_unix": time.time(),
        "teacher_chunked": bool(te_meta.get("chunked", False)),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return {
        "clip_id": clip_id,
        "status": "ok",
        "T": T,
        "residual_rms": float(np.sqrt(np.mean(residual**2))),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", type=Path, default=LAB_ROOT / "configs" / "dataset.yaml")
    ap.add_argument("--limit", type=int, default=0, help="process only first N clips (0=all)")
    ap.add_argument("--clip-id", type=str, default="", help="single clip id")
    ap.add_argument("--no-skip", action="store_true", help="recompute even if residual exists")
    args = ap.parse_args()

    cfg = _load_yaml(args.config)
    paths = cfg.get("paths") or {}
    mp_root = LAB_ROOT / paths.get("mediapipe", "data/mediapipe")
    te_root = LAB_ROOT / paths.get("teacher", "data/teacher")
    out_root = LAB_ROOT / paths.get("paired", "data/paired")
    target_fps = float((cfg.get("resample") or {}).get("target_fps", CANONICAL_FPS))
    skip_existing = not args.no_skip

    if args.clip_id:
        ids = [args.clip_id]
    else:
        ids = _common_clip_ids(mp_root, te_root)
        if args.limit > 0:
            ids = ids[: args.limit]

    out_root.mkdir(parents=True, exist_ok=True)
    ok = skip = fail = 0
    t0 = time.time()
    print(f"[pair] clips={len(ids)} target_fps={target_fps} out={out_root}")
    for i, cid in enumerate(ids, 1):
        try:
            r = pair_one(cid, mp_root, te_root, out_root, target_fps, skip_existing)
            st = r["status"]
            if st == "skip":
                skip += 1
            else:
                ok += 1
            if i == 1 or i % 10 == 0 or st != "skip":
                extra = f" T={r.get('T')} rms={r.get('residual_rms', 0):.4f}" if st == "ok" else ""
                print(f"[{i}/{len(ids)}] {st} {cid}{extra}", flush=True)
        except Exception as e:
            fail += 1
            print(f"[{i}/{len(ids)}] FAIL {cid}: {e}", flush=True)

    summary = {
        "ok": ok,
        "skip": skip,
        "fail": fail,
        "total": len(ids),
        "elapsed_s": time.time() - t0,
        "out": str(out_root),
    }
    (out_root / "_pair_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"[pair] done ok={ok} skip={skip} fail={fail} elapsed={summary['elapsed_s']:.1f}s")
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
