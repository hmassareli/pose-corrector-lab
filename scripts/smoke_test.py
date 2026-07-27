#!/usr/bin/env python3
"""Quick sanity checks for lab core modules."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB_ROOT / "src"))

from pose_lab.features import build_feature_sequence, feature_dim
from pose_lab.labels import motion_pseudo_label, residual_sequence
from pose_lab.metrics import summarize_split
from pose_lab.skeleton import DELTA_DIM, TARGET_IDX
from pose_lab.timebase import resample_series


def main() -> None:
    T, J = 30, 16
    mp = np.random.randn(T, J, 3).astype(np.float64) * 0.01
    te = mp + np.random.randn(T, J, 3) * 0.005
    conf = np.clip(np.random.rand(T, J), 0.2, 1.0)
    p2 = np.zeros((T, J, 2))
    feats = build_feature_sequence(mp, conf, p2)
    assert feats.shape[0] == T
    assert feats.shape[1] == feature_dim(include_2d=True)
    print("F =", feats.shape[1])
    d = residual_sequence(mp, te)
    assert d.shape == (T, DELTA_DIM)
    print("motion label", motion_pseudo_label(mp))
    rs, _ = resample_series(mp, src_fps=60, dst_fps=30)
    assert rs.shape[0] in (15, 16)
    print("resample 60->30 T", rs.shape[0])
    summary = summarize_split(
        te, te, mp, d, np.zeros_like(d), conf[:, TARGET_IDX]
    )
    print("metrics keys", sorted(summary.keys()))
    print("SMOKE OK")


if __name__ == "__main__":
    main()
