#!/usr/bin/env python3
"""Offline analysis of palm_raw_<tag>.npz dumps from check_palm_fidelity.py.

The render is slow, so it happens once and every metric is tried here.

The avatar's hand-bone frame and the fit's anatomical palm frame differ by an
unknown CONSTANT rig offset, so raw angles between them are meaningless. Two
ways to see past that:

  1. CALIBRATION-FREE (primary). Frame-to-frame relative rotation:
         d_av(t)  = angle(R_av(t)^T  R_av(t+1))
         d_fit(t) = angle(R_fit(t)^T R_fit(t+1))
     Any constant offset M cancels: (M R)^T (M R') = R^T R'. If the avatar
     tracks the fit, these two series match. This cannot be faked by a bad
     calibration, and it is what exposes whether the hand is being driven at all.

  2. KARCHER-CALIBRATED. Proper geodesic mean on SO(3) (iterative, unlike a naive
     quaternion average, which collapses when the spread is large — that is what
     produced the bogus "residual = exactly 90 deg" reading). Residual after
     removing it is the tracking error; the calibrated palm normal is then
     directly comparable to the fit's.

Usage: python scripts/analyze_palm_raw.py baseline [fixed ...]
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = LAB_ROOT / "experiments" / "bake_top"
PUNCH = (440, 510)


def log_so3(R: np.ndarray) -> np.ndarray:
    """Rotation matrix -> rotation vector."""
    c = np.clip((np.trace(R) - 1) / 2, -1, 1)
    th = float(np.arccos(c))
    if th < 1e-8:
        return np.zeros(3)
    if th > np.pi - 1e-6:
        # Near pi: recover the axis from the symmetric part.
        A = (R + np.eye(3)) / 2
        ax = np.sqrt(np.maximum(np.diag(A), 0))
        i = int(np.argmax(ax))
        if ax[i] < 1e-9:
            return np.zeros(3)
        v = A[:, i] / ax[i]
        return th * v / (np.linalg.norm(v) or 1)
    w = np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]])
    return th * w / (2 * np.sin(th))


def exp_so3(v: np.ndarray) -> np.ndarray:
    th = float(np.linalg.norm(v))
    if th < 1e-12:
        return np.eye(3)
    k = v / th
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + np.sin(th) * K + (1 - np.cos(th)) * (K @ K)


def karcher_mean(Rs: np.ndarray, iters: int = 60) -> np.ndarray:
    """Geodesic (Karcher) mean on SO(3). Robust where a quaternion average is not."""
    M = Rs[0].copy()
    for _ in range(iters):
        d = np.mean([log_so3(M.T @ R) for R in Rs], axis=0)
        M = M @ exp_so3(d)
        if np.linalg.norm(d) < 1e-10:
            break
    return M


def ang(R: np.ndarray) -> float:
    return float(np.degrees(np.arccos(np.clip((np.trace(R) - 1) / 2, -1, 1))))


def analyze(tag: str) -> None:
    path = OUT_DIR / f"palm_raw_{tag}.npz"
    if not path.is_file():
        print(f"!! missing {path}")
        return
    d = np.load(path)
    print(f"\n{'='*72}\n=== {tag} ===\n{'='*72}")
    for side in ("left", "right"):
        t = d[f"{side}_t"]
        F = d[f"{side}_fit"]
        A = d[f"{side}_av"]
        if len(t) < 8:
            print(f"[{side}] too few frames")
            continue
        # The dump builds both hands with across = pinky1 - index1. Under the
        # body's mirror symmetry that makes the LEFT frame the mirror image of
        # the right, so "normal_y < 0 = palm toward the ground" would read
        # inverted on the left. Flip across+normal (180 deg about fwd, det +1)
        # to put both hands in one anatomically consistent convention. Applied
        # post-hoc and identically to every dump, so tags stay comparable.
        if side == "left":
            F = F @ np.diag([-1.0, 1.0, -1.0])

        # Both frames are rigidly attached to the SAME hand, so with hand world
        # rotation R_t:  A_t = R_t A_0  and  F_t = R_t F_0
        #  =>  A_t = F_t . C   with  C = F_0^-1 A_0 constant, multiplying on the
        # RIGHT. (Modelling it as A = C.F is wrong and inflates the residual.)
        # E_t = F_t^T A_t is then constant iff tracking is perfect, and it is
        # invariant to BOTH frames' convention choices: F->FS gives E->S^T E and
        # A->AD gives E->ED, either of which cancels in the residual below.

        # --- 1. calibration-free: frame-to-frame rotation magnitude ----------
        # dA = A_t^T A_t+1 = C^T (F_t^T F_t+1) C, a conjugation, so the ANGLE of
        # the per-frame rotation must match the fit's exactly under perfect
        # tracking — with no calibration at all.
        d_av = np.array([ang(A[i].T @ A[i + 1]) for i in range(len(t) - 1)])
        d_fit = np.array([ang(F[i].T @ F[i + 1]) for i in range(len(t) - 1)])
        m = (d_av > 1e-6) | (d_fit > 1e-6)
        corr = float(np.corrcoef(d_av[m], d_fit[m])[0, 1]) if m.sum() > 3 else float("nan")
        mag_err = np.abs(d_av - d_fit)

        # --- 2. Karcher-calibrated (the headline metric) ---------------------
        E = np.array([F[i].T @ A[i] for i in range(len(t))])
        C = karcher_mean(E)
        resid = np.array([ang(C.T @ Ei) for Ei in E])

        # Avatar frame expressed in the fit's convention: A_t C^-1.
        cal = np.array([A[i] @ C.T for i in range(len(t))])
        w = (t >= PUNCH[0]) & (t <= PUNCH[1])
        fit_ny, av_ny = F[:, 1, 2], cal[:, 1, 2]  # row 1 (y) of column 2 (normal)

        print(f"\n[{side}]  {len(t)} frames")
        print("  -- calibration-free --")
        print(f"     per-frame rotation  fit: p50 {np.percentile(d_fit,50):5.2f}  p95 {np.percentile(d_fit,95):5.2f} deg")
        print(f"     per-frame rotation  av : p50 {np.percentile(d_av,50):5.2f}  p95 {np.percentile(d_av,95):5.2f} deg")
        print(f"     motion-magnitude corr  : {corr:+.3f}   (1.0 = ideal)")
        print(f"     motion-magnitude error : p50 {np.percentile(mag_err,50):5.2f}  p95 {np.percentile(mag_err,95):5.2f} deg")
        print("  -- Karcher-calibrated (convention-free) --")
        print(f"     rig offset (constant)  : {ang(C):5.1f} deg  (arbitrary, not a defect)")
        print(f"     TRACKING RESIDUAL      : p50 {np.percentile(resid,50):5.1f}  p95 {np.percentile(resid,95):5.1f} deg"
              f"   <- 0 = perfect")
        if w.sum():
            print(f"     punch {PUNCH[0]}-{PUNCH[1]} palm-normal Y (-1 = facing ground):")
            print(f"        fit    mean {fit_ny[w].mean():+.2f}  min {fit_ny[w].min():+.2f}")
            print(f"        avatar mean {av_ny[w].mean():+.2f}  min {av_ny[w].min():+.2f}")
            print(f"        mean |diff| {np.abs(fit_ny[w]-av_ny[w]).mean():.2f}")


def main() -> int:
    tags = sys.argv[1:] or ["baseline"]
    for tag in tags:
        analyze(tag)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
