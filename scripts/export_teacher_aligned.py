#!/usr/bin/env python3
"""Copy paired teacher_aligned_30.npy → data/teacher_aligned/<clip>/ for the web viewer.

Resamples 30 Hz paired poses onto the source-video / MediaPipe frame grid so the
viewer scrubber matches MediaPipe frame indices.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB_ROOT / "src"))

from pose_lab.timebase import CANONICAL_FPS, resample_to_n_frames  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", type=Path, default=LAB_ROOT / "data" / "splits" / "manifest.json")
    ap.add_argument("--split", default="test", choices=("train", "val", "test", "all"))
    ap.add_argument("--paired", type=Path, default=LAB_ROOT / "data" / "paired")
    ap.add_argument("--mediapipe", type=Path, default=LAB_ROOT / "data" / "mediapipe")
    ap.add_argument("--out", type=Path, default=LAB_ROOT / "data" / "teacher_aligned")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--clip", action="append", default=[], help="Only these clip ids (repeatable)")
    args = ap.parse_args()

    if args.split == "all":
        clip_ids = sorted(
            p.name for p in args.paired.iterdir() if (p / "teacher_aligned_30.npy").is_file()
        )
    else:
        man = json.loads(args.manifest.read_text(encoding="utf-8"))
        clip_ids = list(man["splits"][args.split])
    if args.clip:
        want = set(args.clip)
        clip_ids = [c for c in clip_ids if c in want]
    if args.limit > 0:
        clip_ids = clip_ids[: args.limit]

    args.out.mkdir(parents=True, exist_ok=True)
    print(f"[export_ta] clips={len(clip_ids)} -> {args.out}")
    t0 = time.time()
    for i, cid in enumerate(clip_ids, 1):
        src_npy = args.paired / cid / "teacher_aligned_30.npy"
        if not src_npy.is_file():
            print(f"[{i}/{len(clip_ids)}] SKIP missing {cid}", flush=True)
            continue
        te_30 = np.load(src_npy)
        paired_meta: dict = {}
        pm_path = args.paired / cid / "meta.json"
        if pm_path.is_file():
            paired_meta = json.loads(pm_path.read_text(encoding="utf-8"))
        fps_src = float(paired_meta.get("fps_src") or CANONICAL_FPS)
        n_src = int(paired_meta.get("n_frames_src_mp") or 0)
        if n_src <= 0:
            n_src = int(round((te_30.shape[0] - 1) * fps_src / CANONICAL_FPS)) + 1
        if abs(fps_src - CANONICAL_FPS) < 1e-6 and n_src == te_30.shape[0]:
            te = te_30
        else:
            te, _ = resample_to_n_frames(te_30, CANONICAL_FPS, fps_src, n_src)

        out_dir = args.out / cid
        out_dir.mkdir(parents=True, exist_ok=True)
        np.save(out_dir / "joints3d.npy", te.astype(np.float32))
        meta = {
            "clip_id": cid,
            "fps": fps_src,
            "fps_infer": CANONICAL_FPS,
            "n_frames": int(te.shape[0]),
            "n_frames_infer_30": int(te_30.shape[0]),
            "source": "teacher_aligned",
            "alignment": "trunk_translate_scale_per_frame",
            "created_unix": time.time(),
        }
        (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        vp = out_dir / "viewer_payload.json"
        if vp.is_file():
            vp.unlink()
        src_vid = args.mediapipe / cid / "source.mp4"
        dst_vid = out_dir / "source.mp4"
        if src_vid.is_file() and not dst_vid.exists():
            try:
                os.link(src_vid, dst_vid)
            except OSError:
                shutil.copy2(src_vid, dst_vid)
        print(
            f"[{i}/{len(clip_ids)}] {cid} T30={te_30.shape[0]} -> T={te.shape[0]} @ {fps_src:.3f}fps",
            flush=True,
        )

    print(f"[export_ta] done elapsed={time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
