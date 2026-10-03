#!/usr/bin/env python3
"""Export Teacher ankle→foot tips for avatar retarget (MiKaPo-style).

Reads raw GVHMR FK `joints3d_smpl.npy` (T,22,3) where indices 7/8 = ankles and
10/11 = left_foot / right_foot. Applies the same YZ flip + 30 Hz resample +
per-frame trunk translate+scale as pairing, then resamples onto the source-video
grid used by `teacher_aligned` viewer clips.

Writes `data/teacher_aligned/<clip>/foot_landmarks.json` with:
  source=teacher, heel≈ankle (no SMPL heel in FK-22), toe=SMPL foot tip.
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

from pose_lab.align import (  # noqa: E402
    apply_trunk_translate_scale,
    trunk_translate_scale_params,
)
from pose_lab.skeleton import JOINT_TO_IDX  # noqa: E402
from pose_lab.timebase import CANONICAL_FPS, resample_series, resample_to_n_frames  # noqa: E402

# SMPL-H FK-22 indices (see GVHMR SMPLH_JOINT_NAMES)
SMPL_LEFT_ANKLE, SMPL_RIGHT_ANKLE = 7, 8
SMPL_LEFT_FOOT, SMPL_RIGHT_FOOT = 10, 11


def _flip_yz(joints: np.ndarray) -> np.ndarray:
    out = joints.astype(np.float64, copy=True)
    out[..., 1] *= -1.0
    out[..., 2] *= -1.0
    return out


def export_one(
    clip_id: str,
    teacher_root: Path,
    mediapipe_root: Path,
    paired_root: Path,
    out_root: Path,
) -> dict:
    te_dir = teacher_root / clip_id
    smpl_path = te_dir / "joints3d_smpl.npy"
    te_lab_path = te_dir / "joints3d.npy"
    mp_path = mediapipe_root / clip_id / "joints3d.npy"
    if not smpl_path.is_file():
        return {"clip_id": clip_id, "status": "skip", "reason": "no joints3d_smpl"}
    if not te_lab_path.is_file() or not mp_path.is_file():
        return {"clip_id": clip_id, "status": "skip", "reason": "missing lab/mp"}

    smpl = np.load(smpl_path)
    te = np.load(te_lab_path)
    mp = np.load(mp_path)
    if smpl.ndim != 3 or smpl.shape[-1] != 3 or smpl.shape[1] < 12:
        return {"clip_id": clip_id, "status": "skip", "reason": f"bad smpl {smpl.shape}"}

    paired_meta: dict = {}
    pm_path = paired_root / clip_id / "meta.json"
    if pm_path.is_file():
        paired_meta = json.loads(pm_path.read_text(encoding="utf-8"))

    mp_meta: dict = {}
    if (mediapipe_root / clip_id / "meta.json").is_file():
        mp_meta = json.loads((mediapipe_root / clip_id / "meta.json").read_text(encoding="utf-8"))

    fps_src = float(paired_meta.get("fps_src") or mp_meta.get("fps") or CANONICAL_FPS)
    n_src = int(paired_meta.get("n_frames_src_mp") or mp.shape[0])

    te_v = _flip_yz(te)
    mp_v = _flip_yz(mp)
    # feet pack: [L_heel≈ankle, L_toe, R_heel≈ankle, R_toe]
    feet_raw = np.stack(
        [
            smpl[:, SMPL_LEFT_ANKLE],
            smpl[:, SMPL_LEFT_FOOT],
            smpl[:, SMPL_RIGHT_ANKLE],
            smpl[:, SMPL_RIGHT_FOOT],
        ],
        axis=1,
    )
    feet_v = _flip_yz(feet_raw)

    mp_30, _ = resample_series(mp_v, fps_src, CANONICAL_FPS)
    te_30, _ = resample_series(te_v, fps_src, CANONICAL_FPS)
    feet_30, _ = resample_series(feet_v, fps_src, CANONICAL_FPS)
    T = int(min(mp_30.shape[0], te_30.shape[0], feet_30.shape[0]))
    mp_30 = mp_30[:T]
    te_30 = te_30[:T]
    feet_30 = feet_30[:T]

    feet_aligned = np.empty_like(feet_30, dtype=np.float32)
    body_frames = np.empty((T, 4, 3), dtype=np.float32)
    ls, rs = JOINT_TO_IDX["left_shoulder"], JOINT_TO_IDX["right_shoulder"]
    lh, rh = JOINT_TO_IDX["left_hip"], JOINT_TO_IDX["right_hip"]
    for i in range(T):
        mu_s, mu_d, scale = trunk_translate_scale_params(te_30[i], mp_30[i])
        feet_aligned[i] = apply_trunk_translate_scale(feet_30[i], mu_s, mu_d, scale)
        te_a = apply_trunk_translate_scale(te_30[i], mu_s, mu_d, scale)
        body_frames[i] = np.stack([te_a[ls], te_a[rs], te_a[lh], te_a[rh]], axis=0)

    if abs(fps_src - CANONICAL_FPS) < 1e-6 and n_src == T:
        feet_out, body_out = feet_aligned, body_frames
    else:
        feet_out, _ = resample_to_n_frames(feet_aligned, CANONICAL_FPS, fps_src, n_src)
        body_out, _ = resample_to_n_frames(body_frames, CANONICAL_FPS, fps_src, n_src)

    out_dir = out_root / clip_id
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": "teacher",
        "names": ["left_heel", "left_toe", "right_heel", "right_toe"],
        "note": "heel≈SMPL ankle; toe=SMPL left_foot/right_foot (FK-22). Aligned like teacher_aligned.",
        "fps": fps_src,
        "n_frames": int(feet_out.shape[0]),
        "frames": feet_out.astype(np.float32).tolist(),
        "body_frames": body_out.astype(np.float32).tolist(),
        "body_names": ["left_shoulder", "right_shoulder", "left_hip", "right_hip"],
    }
    (out_dir / "foot_landmarks.json").write_text(json.dumps(payload), encoding="utf-8")
    return {"clip_id": clip_id, "status": "ok", "n_frames": int(feet_out.shape[0])}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", type=Path, default=LAB_ROOT / "data" / "splits" / "manifest.json")
    ap.add_argument("--split", default="test", choices=("train", "val", "test", "all"))
    ap.add_argument("--teacher", type=Path, default=LAB_ROOT / "data" / "teacher")
    ap.add_argument("--mediapipe", type=Path, default=LAB_ROOT / "data" / "mediapipe")
    ap.add_argument("--paired", type=Path, default=LAB_ROOT / "data" / "paired")
    ap.add_argument("--out", type=Path, default=LAB_ROOT / "data" / "teacher_aligned")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--clip", action="append", default=[])
    args = ap.parse_args()

    if args.split == "all":
        clip_ids = sorted(
            p.name for p in args.teacher.iterdir() if (p / "joints3d_smpl.npy").is_file()
        )
    else:
        man = json.loads(args.manifest.read_text(encoding="utf-8"))
        clip_ids = list(man["splits"][args.split])
    if args.clip:
        want = set(args.clip)
        clip_ids = [c for c in clip_ids if c in want]
    if args.limit > 0:
        clip_ids = clip_ids[: args.limit]

    print(f"[export_feet] clips={len(clip_ids)} -> {args.out}")
    t0 = time.time()
    ok = skip = 0
    for i, cid in enumerate(clip_ids, 1):
        try:
            r = export_one(cid, args.teacher, args.mediapipe, args.paired, args.out)
        except Exception as e:
            print(f"[{i}/{len(clip_ids)}] FAIL {cid}: {e}", flush=True)
            continue
        if r["status"] == "ok":
            ok += 1
            print(f"[{i}/{len(clip_ids)}] {cid} T={r['n_frames']}", flush=True)
        else:
            skip += 1
            print(f"[{i}/{len(clip_ids)}] SKIP {cid} ({r.get('reason')})", flush=True)
    print(f"[export_feet] done ok={ok} skip={skip} elapsed={time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
