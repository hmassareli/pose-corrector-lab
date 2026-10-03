#!/usr/bin/env python3
"""ABSOLUTE palm error: the number the eye actually judges. No calibration.

analyze_palm_raw.py removes a constant rig offset before measuring, which answers
"does the hand TRACK the fit?" (yes: ~5 deg). But it hides the thing that is
actually wrong on screen: a CONSTANT offset between the avatar's palm and the
fit's palm is exactly "the fist is rotated 90 deg / faces sideways instead of
down". Calibrating it away makes a broken render look perfect.

So here both sides are built as the SAME anatomical frame and compared directly:

    fwd    = along the hand, wrist -> knuckles
    across = medial-lateral palm axis
    normal = fwd x across          (palm facing direction; -Y = toward the ground)

  * FIT:    across = pinky1 - index1  (real SMPL-X knuckles)
  * AVATAR: across = normal of the plane fitted to the hand + finger chain,
            transported by the hand bone's measured per-frame rotation.
            Uses the rig's real bone geometry, NOT the solver's
            `restAcrossInRoot`, so it stays non-circular.

Both use sign = -1 on the left, matching the solver's own negateAcrossLeft
convention, so the two hands are anatomically mirrored rather than mirror-image.

Usage: python scripts/absolute_palm_error.py ondisk_fix fixed
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = LAB_ROOT / "experiments" / "bake_top"
PUNCH = (440, 510)


def unit(v):
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else np.zeros(3)


def quat_to_mat(q):
    x, y, z, w = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def frame(fwd_raw, across_raw):
    across = unit(across_raw)
    fwd = unit(fwd_raw - across * float(np.dot(fwd_raw, across)))
    if np.linalg.norm(across) < 1e-9 or np.linalg.norm(fwd) < 1e-9:
        return None
    return np.column_stack([across, fwd, unit(np.cross(fwd, across))])


def ang(R):
    return float(np.degrees(np.arccos(np.clip((np.trace(R) - 1) / 2, -1, 1))))


def main() -> int:
    tags = sys.argv[1:] or ["fixed"]
    probe = json.loads((OUT_DIR / "rig_rest_probe.json").read_text(encoding="utf-8"))

    d = np.load(LAB_ROOT / "experiments" / "nlf_fit_webcam1" / "fit_smplx.npz")
    names = [str(n) for n in d["smplx55_names"]]
    idx = {n: i for i, n in enumerate(names)}
    fj = d["fit_joints"].astype(np.float64)
    flip = np.diag([1.0, -1.0, -1.0])

    # Rest geometry of the avatar (root space), independent of the solver state.
    rest = {}
    for side in ("left", "right"):
        pr = probe[side]
        chain = np.array([p for p in pr["chain"] if p], float)
        c = chain.mean(axis=0)
        _, _, Vt = np.linalg.svd(chain - c)
        n_plane = unit(Vt[2])
        ref = unit(np.cross(unit(np.array(pr["restDir"], float)), np.array([0, 1.0, 0])))
        if np.dot(n_plane, ref) < 0:
            n_plane = -n_plane
        A_rest = quat_to_mat(np.array(pr["restQuat"], float))
        rest[side] = {
            "n_local": A_rest.T @ n_plane,                              # across, hand-local
            "d_local": A_rest.T @ unit(np.array(pr["restDir"], float)),  # fwd, hand-local
        }

    for tag in tags:
        path = OUT_DIR / f"palm_raw_{tag}.npz"
        if not path.is_file():
            print(f"!! missing {path}")
            continue
        raw = np.load(path)
        print(f"\n{'='*70}\n=== ABSOLUTE palm error [{tag}] (no calibration) ===\n{'='*70}")
        for side in ("left", "right"):
            t = raw[f"{side}_t"]
            A = raw[f"{side}_av"]
            if len(t) < 8:
                continue
            sign = -1.0 if side == "left" else 1.0
            w_i, i_i, p_i = idx[f"{side}_wrist"], idx[f"{side}_index1"], idx[f"{side}_pinky1"]

            errs, fit_ny, av_ny = [], [], []
            for k, tt in enumerate(t):
                wr, ix, pk = flip @ fj[tt, w_i], flip @ fj[tt, i_i], flip @ fj[tt, p_i]
                Ff = frame((ix + pk) / 2 - wr, sign * (pk - ix))
                # Avatar: rest axes transported by the measured hand rotation.
                Fa = frame(A[k] @ rest[side]["d_local"], A[k] @ rest[side]["n_local"])
                if Ff is None or Fa is None:
                    continue
                errs.append(ang(Fa.T @ Ff))
                fit_ny.append(Ff[1, 2])
                av_ny.append(Fa[1, 2])
            errs = np.array(errs)
            fit_ny, av_ny = np.array(fit_ny), np.array(av_ny)
            wmask = (t[:len(errs)] >= PUNCH[0]) & (t[:len(errs)] <= PUNCH[1])

            print(f"\n[{side}]  {len(errs)} frames")
            print(f"  ABSOLUTE palm error : p50 {np.percentile(errs,50):6.1f}  "
                  f"p95 {np.percentile(errs,95):6.1f}  max {errs.max():6.1f} deg")
            if wmask.sum():
                print(f"  punch {PUNCH[0]}-{PUNCH[1]} palm-normal Y (-1 = facing the ground):")
                print(f"     fit    mean {fit_ny[wmask].mean():+.2f}  min {fit_ny[wmask].min():+.2f}")
                print(f"     avatar mean {av_ny[wmask].mean():+.2f}  min {av_ny[wmask].min():+.2f}")
                print(f"     mean |diff| {np.abs(fit_ny[wmask]-av_ny[wmask]).mean():.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
