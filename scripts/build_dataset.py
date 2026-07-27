#!/usr/bin/env python3
"""Build windowed training arrays from data/paired + splits/manifest.json.

Writes:
  data/dataset/{train,val,test}.npz
  data/dataset/meta.json

Uses mp_2d_30.npy from pair_poses when present (MediaPipe image landmarks / W,H).
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

from pose_lab.align import body_frame_from_pose, to_body_frame  # noqa: E402
from pose_lab.features import build_feature_sequence, feature_dim  # noqa: E402
from pose_lab.labels import difficulty_score, motion_pseudo_label, residual_sequence  # noqa: E402
from pose_lab.skeleton import DELTA_DIM, JOINT_TO_IDX, N_TARGETS, TARGET_IDX, TARGET_JOINTS  # noqa: E402
from pose_lab.timebase import CANONICAL_FPS  # noqa: E402


def _load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _windows(n: int, T: int, stride: int) -> list[int]:
    """End indices (inclusive) for causal windows of length T."""
    if n < T:
        return []
    return list(range(T - 1, n, stride))


def build_split(
    clip_ids: list[str],
    paired_root: Path,
    T: int,
    stride: int,
    include_2d: bool,
) -> dict[str, np.ndarray]:
    xs: list[np.ndarray] = []
    ys: list[np.ndarray] = []
    confs: list[np.ndarray] = []
    motions: list[int] = []
    diffs: list[float] = []
    clip_idx: list[int] = []
    frame_end: list[int] = []
    clip_table: list[str] = []

    F = feature_dim(include_2d=include_2d)
    t0 = time.time()

    for ci, cid in enumerate(clip_ids):
        d = paired_root / cid
        mp = np.load(d / "mp_30.npy")
        te = np.load(d / "teacher_aligned_30.npy")
        conf = np.load(d / "conf_30.npy")
        # Prefer stored residual; recompute if missing / T mismatch / delta-dim mismatch
        res_path = d / "residual_30.npy"
        residual = None
        if res_path.is_file():
            residual = np.load(res_path)
            if residual.shape[0] != mp.shape[0] or residual.shape[-1] != DELTA_DIM:
                residual = None
        if residual is None:
            residual = residual_sequence(mp, te)
            np.save(res_path, residual.astype(np.float32))

        poses_2d = None
        if include_2d:
            j2_path = d / "mp_2d_30.npy"
            if not j2_path.is_file():
                raise FileNotFoundError(f"{cid}: missing mp_2d_30.npy — re-run pair_poses.py")
            poses_2d = np.load(j2_path)

        feats = build_feature_sequence(mp, conf, poses_2d_norm=poses_2d, fps=CANONICAL_FPS)
        if feats.shape[-1] != F:
            raise RuntimeError(f"{cid}: F={feats.shape[-1]} expected {F}")

        # teacher body-frame for motion pseudo-labels
        te_b = np.zeros_like(te)
        for t in range(te.shape[0]):
            R, scale, origin = body_frame_from_pose(mp[t])  # same frame as residual
            te_b[t] = to_body_frame(te[t], R, scale, origin)

        ends = _windows(mp.shape[0], T, stride)
        clip_table.append(cid)
        for end in ends:
            start = end - T + 1
            x = feats[start : end + 1]
            y = residual[end]
            c_tgt = conf[end, TARGET_IDX]
            mot = motion_pseudo_label(te_b[start : end + 1], fps=CANONICAL_FPS)
            dif = difficulty_score(y, c_tgt)
            xs.append(x.astype(np.float32))
            ys.append(y.astype(np.float32))
            confs.append(c_tgt.astype(np.float32))
            motions.append(mot)
            diffs.append(dif)
            clip_idx.append(ci)
            frame_end.append(end)

        if (ci + 1) % 20 == 0 or ci == 0 or ci + 1 == len(clip_ids):
            print(
                f"  [{ci+1}/{len(clip_ids)}] windows={len(xs)} elapsed={time.time()-t0:.1f}s",
                flush=True,
            )

    if not xs:
        return {
            "x": np.zeros((0, T, F), dtype=np.float32),
            "y": np.zeros((0, DELTA_DIM), dtype=np.float32),
            "conf_targets": np.zeros((0, N_TARGETS), dtype=np.float32),
            "motion": np.zeros((0,), dtype=np.int64),
            "difficulty": np.zeros((0,), dtype=np.float32),
            "clip_idx": np.zeros((0,), dtype=np.int32),
            "frame_end": np.zeros((0,), dtype=np.int32),
            "clip_ids": np.array([], dtype=object),
        }

    return {
        "x": np.stack(xs, axis=0),
        "y": np.stack(ys, axis=0),
        "conf_targets": np.stack(confs, axis=0),
        "motion": np.asarray(motions, dtype=np.int64),
        "difficulty": np.asarray(diffs, dtype=np.float32),
        "clip_idx": np.asarray(clip_idx, dtype=np.int32),
        "frame_end": np.asarray(frame_end, dtype=np.int32),
        "clip_ids": np.asarray(clip_table, dtype=object),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", type=Path, default=LAB_ROOT / "configs" / "dataset.yaml")
    ap.add_argument("--manifest", type=Path, default=LAB_ROOT / "data" / "splits" / "manifest.json")
    ap.add_argument("--out", type=Path, default=LAB_ROOT / "data" / "dataset")
    args = ap.parse_args()

    cfg = _load_yaml(args.config)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    paired_root = LAB_ROOT / (cfg.get("paths") or {}).get("paired", "data/paired")
    T = int(cfg.get("window_T") or manifest.get("window_T") or 15)
    stride_train = int(cfg.get("window_stride_train") or 2)
    stride_eval = int(cfg.get("window_stride_eval") or 1)
    include_2d = bool((cfg.get("features") or {}).get("include_2d", True))
    F = feature_dim(include_2d=include_2d)

    args.out.mkdir(parents=True, exist_ok=True)
    summary = {
        "T": T,
        "F": F,
        "include_2d": include_2d,
        "fps": CANONICAL_FPS,
        "target_joints": TARGET_JOINTS,
        "target_idx": TARGET_IDX,
        "delta_dim": DELTA_DIM,
        "joint_to_idx": JOINT_TO_IDX,
        "splits": {},
    }

    for split in ("train", "val", "test"):
        clips = list(manifest["splits"][split])
        stride = stride_train if split == "train" else stride_eval
        print(f"\n=== {split} clips={len(clips)} T={T} stride={stride} F={F} ===", flush=True)
        data = build_split(clips, paired_root, T, stride, include_2d)
        out_path = args.out / f"{split}.npz"
        np.savez_compressed(out_path, **data)
        n = int(data["x"].shape[0])
        hours = float(sum(
            np.load(paired_root / c / "residual_30.npy", mmap_mode="r").shape[0]
            for c in clips
        ) / CANONICAL_FPS / 3600.0) if clips else 0.0
        summary["splits"][split] = {
            "n_clips": len(clips),
            "n_windows": n,
            "hours_pose": hours,
            "stride": stride,
            "path": str(out_path.relative_to(LAB_ROOT)),
            "x_shape": list(data["x"].shape),
            "y_shape": list(data["y"].shape),
        }
        print(f"wrote {out_path} windows={n}", flush=True)

    (args.out / "meta.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\n[build_dataset] done -> {args.out / 'meta.json'}")


if __name__ == "__main__":
    main()
