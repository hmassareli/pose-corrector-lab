#!/usr/bin/env python3
"""Add per-frame residual targets `y_seq` to existing window NPZs.

Uses clip_idx / frame_end already stored in the NPZ plus residual_30.npy
from data/paired — no full feature rebuild.

Writes a new key `y_seq` with shape (N, T, DELTA_DIM) alongside existing `y`
(last frame, unchanged). Safe to re-run (overwrites y_seq only).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB_ROOT / "src"))

from pose_lab.labels import residual_sequence  # noqa: E402
from pose_lab.skeleton import DELTA_DIM  # noqa: E402


def _load_residual(paired: Path, cid: str, n_frames: int) -> np.ndarray:
    d = paired / cid
    res_path = d / "residual_30.npy"
    if res_path.is_file():
        residual = np.load(res_path)
        if residual.shape[0] == n_frames and residual.shape[-1] == DELTA_DIM:
            return residual.astype(np.float32)
    mp = np.load(d / "mp_30.npy")
    te = np.load(d / "teacher_aligned_30.npy")
    residual = residual_sequence(mp, te).astype(np.float32)
    np.save(res_path, residual)
    return residual


def augment_split(npz_path: Path, paired: Path) -> dict:
    data = dict(np.load(npz_path, allow_pickle=True))
    x = data["x"]
    n, T, _ = x.shape
    clip_ids = [str(c) for c in data["clip_ids"].tolist()]
    clip_idx = data["clip_idx"].astype(np.int32)
    frame_end = data["frame_end"].astype(np.int32)

    # Cache residuals per clip
    cache: dict[int, np.ndarray] = {}
    y_seq = np.zeros((n, T, DELTA_DIM), dtype=np.float32)
    t0 = time.time()
    for i in range(n):
        ci = int(clip_idx[i])
        end = int(frame_end[i])
        start = end - T + 1
        if ci not in cache:
            cid = clip_ids[ci]
            # Infer length from residual/mp
            d = paired / cid
            n_fr = int(np.load(d / "mp_30.npy", mmap_mode="r").shape[0])
            cache[ci] = _load_residual(paired, cid, n_fr)
        res = cache[ci]
        if end >= res.shape[0] or start < 0:
            raise RuntimeError(
                f"{npz_path.name} i={i} clip={clip_ids[ci]} "
                f"window [{start},{end}] vs residual T={res.shape[0]}"
            )
        y_seq[i] = res[start : end + 1]
        # Sanity: last frame matches stored y
        if i < 3 or i == n - 1:
            err = float(np.abs(y_seq[i, -1] - data["y"][i]).max())
            if err > 1e-4:
                print(f"[warn] y vs y_seq[-1] mismatch i={i} maxabs={err:.6f}", flush=True)
        if (i + 1) % 20000 == 0 or i == 0 or i + 1 == n:
            print(
                f"  [{i+1}/{n}] clips_cached={len(cache)} elapsed={time.time()-t0:.1f}s",
                flush=True,
            )

    data["y_seq"] = y_seq
    np.savez_compressed(npz_path, **data)
    return {
        "path": str(npz_path),
        "n": n,
        "T": T,
        "y_seq_shape": list(y_seq.shape),
        "n_clips_cached": len(cache),
        "elapsed_s": time.time() - t0,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--dataset-dir",
        type=Path,
        default=LAB_ROOT / "data" / "dataset",
    )
    ap.add_argument(
        "--paired",
        type=Path,
        default=LAB_ROOT / "data" / "paired",
    )
    ap.add_argument(
        "--splits",
        nargs="+",
        default=["train", "val"],
        help="Which NPZs to augment (test optional; large).",
    )
    args = ap.parse_args()

    summary = {}
    for split in args.splits:
        npz = args.dataset_dir / f"{split}.npz"
        if not npz.is_file():
            raise SystemExit(f"missing {npz}")
        print(f"\n=== augment {split} ===", flush=True)
        summary[split] = augment_split(npz, args.paired)
        print(json.dumps(summary[split], indent=2), flush=True)

    meta_path = args.dataset_dir / "meta.json"
    if meta_path.is_file():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["y_seq"] = True
        for split, info in summary.items():
            if split in meta.get("splits", {}):
                meta["splits"][split]["y_seq_shape"] = info["y_seq_shape"]
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print("\n[augment_npz_yseq] done", flush=True)


if __name__ == "__main__":
    main()
