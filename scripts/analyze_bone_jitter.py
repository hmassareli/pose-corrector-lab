#!/usr/bin/env python3
"""Frame-to-frame jitter per bone, compared against the fit's own motion.

Lower error vs the fit does NOT imply smoother output: raising a bone's
`strength` scales its noise along with its signal before the One-Euro filter
runs. This measures the smoothness half of that trade.

  jitter(t) = angle( A_t^T A_t+1 )   for the avatar bone
  ref(t)    = the same on the fit's FK rotation for the matching joint

If the avatar's jitter sits near the fit's, the motion is as smooth as the source.
Jitter well above the fit's is the retarget adding shake of its own.

Usage: python scripts/analyze_bone_jitter.py neck04 neck075 [--bones neck,head]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB_ROOT / "scripts"))

from check_palm_fidelity import quat_to_mat  # noqa: E402
from check_body_fidelity import TWIST_JOINT  # noqa: E402
from render_bake_top import DEFAULT_NPZ, OUT_DIR, SMPLX_NPZ, build_fk  # noqa: E402


def ang(R):
    return float(np.degrees(np.arccos(np.clip((np.trace(R) - 1) / 2, -1, 1))))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("tags", nargs="+")
    ap.add_argument("--bones", default="neck,head,spine2,leftArm,rightArm")
    args = ap.parse_args()
    bones = [b.strip() for b in args.bones.split(",") if b.strip()]

    d = np.load(DEFAULT_NPZ)
    names = [str(n) for n in d["smplx55_names"]]
    idx = {n: i for i, n in enumerate(names)}
    kt = np.asarray(np.load(SMPLX_NPZ, allow_pickle=True)["kintree_table"])
    print("[fit] FK for the reference jitter...", flush=True)
    Rw = build_fk(d["pose"].astype(np.float64), kt)
    FLIP = np.diag([1.0, -1.0, -1.0])

    ref = {}
    for b in bones:
        j = TWIST_JOINT.get(b)
        if j not in idx:
            continue
        F = [FLIP @ Rw[t, idx[j]] @ FLIP.T for t in range(Rw.shape[0])]
        ref[b] = np.array([ang(F[t].T @ F[t + 1]) for t in range(len(F) - 1)])

    print()
    print(f"{'bone':<10}{'source':<10}{'jitter p50':>11}{'p95':>8}{'max':>8}")
    for b in bones:
        if b in ref:
            r = ref[b]
            print(f"{b:<10}{'FIT (ref)':<10}{np.percentile(r,50):>11.2f}"
                  f"{np.percentile(r,95):>8.2f}{r.max():>8.2f}")
        for tag in args.tags:
            p = OUT_DIR / f"bone_quats_{tag}.npz"
            if not p.is_file():
                continue
            z = np.load(p)
            if b not in z:
                continue
            Q = z[b]
            A = [quat_to_mat(q) for q in Q]
            j = np.array([ang(A[t].T @ A[t + 1]) for t in range(len(A) - 1)])
            print(f"{'':<10}{tag:<10}{np.percentile(j,50):>11.2f}"
                  f"{np.percentile(j,95):>8.2f}{j.max():>8.2f}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
