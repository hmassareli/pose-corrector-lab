"""Evaluation metrics for the pose corrector."""

from __future__ import annotations

from typing import Any

import numpy as np

from .skeleton import N_TARGETS, TARGET_IDX


def mpjpe_mm(pred: np.ndarray, gt: np.ndarray, scale_m_to_mm: float = 1000.0) -> float:
    """pred/gt (..., 3) in meters (or body*scale recovered)."""
    err = np.linalg.norm(pred - gt, axis=-1)
    return float(err.mean() * scale_m_to_mm)


def jitter_energy(poses: np.ndarray, fps: float = 30.0) -> float:
    """Mean ‖acc‖ of target joints."""
    if poses.shape[0] < 3:
        return 0.0
    x = poses[:, TARGET_IDX]
    v = (x[1:] - x[:-1]) * fps
    a = (v[1:] - v[:-1]) * fps
    return float(np.linalg.norm(a, axis=-1).mean())


def bone_length_mae(poses: np.ndarray, ref_lengths: dict[str, float]) -> float:
    from .skeleton import JOINT_TO_IDX

    errs = []
    for (a, b), L in ref_lengths.items():
        d = np.linalg.norm(poses[:, JOINT_TO_IDX[a]] - poses[:, JOINT_TO_IDX[b]], axis=-1)
        errs.append(np.abs(d - L).mean())
    return float(np.mean(errs)) if errs else 0.0


def hard_mask(
    deltas: np.ndarray,
    conf: np.ndarray,
    residual_percentile: float = 80.0,
    conf_below: float = 0.5,
) -> np.ndarray:
    """deltas (T, DELTA_DIM), conf (T, N_TARGETS) on targets → bool hard mask (T,)."""
    n = deltas.shape[-1] // 3
    norms = np.linalg.norm(deltas.reshape(deltas.shape[0], n, 3), axis=-1).mean(axis=-1)
    thr = np.percentile(norms, residual_percentile) if len(norms) else 0.0
    low_conf = conf.mean(axis=-1) < conf_below
    return (norms >= thr) | low_conf


def overcorrect_rate(
    pred_delta: np.ndarray,
    true_delta: np.ndarray,
    easy_mask: np.ndarray,
    tau: float = 0.02,
    tau0: float = 0.01,
) -> float:
    if easy_mask.sum() == 0:
        return 0.0
    n = pred_delta.shape[-1] // 3
    pd = np.linalg.norm(pred_delta.reshape(-1, n, 3), axis=-1).mean(axis=-1)
    td = np.linalg.norm(true_delta.reshape(-1, n, 3), axis=-1).mean(axis=-1)
    bad = easy_mask & (pd > tau) & (td < tau0)
    return float(bad.sum() / easy_mask.sum())


def summarize_split(
    pred_abs: np.ndarray,
    gt_abs: np.ndarray,
    mp_abs: np.ndarray,
    deltas_true: np.ndarray,
    deltas_pred: np.ndarray,
    conf_targets: np.ndarray,
) -> dict[str, Any]:
    """All arrays aligned on T for target joints abs (T,N,3) or full poses (T,J,3)."""
    if pred_abs.ndim == 3 and pred_abs.shape[1] != N_TARGETS:
        pred_t = pred_abs[:, TARGET_IDX]
        gt_t = gt_abs[:, TARGET_IDX]
        mp_t = mp_abs[:, TARGET_IDX]
    else:
        pred_t, gt_t, mp_t = pred_abs, gt_abs, mp_abs

    hard = hard_mask(deltas_true, conf_targets)
    easy = ~hard
    out = {
        "n": int(len(hard)),
        "n_hard": int(hard.sum()),
        "n_easy": int(easy.sum()),
        "mpjpe_overall_mm": mpjpe_mm(pred_t, gt_t),
        "mpjpe_mp_overall_mm": mpjpe_mm(mp_t, gt_t),
        "mpjpe_hard_mm": mpjpe_mm(pred_t[hard], gt_t[hard]) if hard.any() else None,
        "mpjpe_easy_mm": mpjpe_mm(pred_t[easy], gt_t[easy]) if easy.any() else None,
        "mpjpe_mp_hard_mm": mpjpe_mm(mp_t[hard], gt_t[hard]) if hard.any() else None,
        "mpjpe_mp_easy_mm": mpjpe_mm(mp_t[easy], gt_t[easy]) if easy.any() else None,
        "jitter_pred": jitter_energy(pred_abs if pred_abs.shape[1] != N_TARGETS else pred_abs),
        "jitter_mp": jitter_energy(mp_abs if mp_abs.shape[1] != N_TARGETS else mp_abs),
        "overcorrect_rate": overcorrect_rate(deltas_pred, deltas_true, easy),
    }
    if out["mpjpe_hard_mm"] is not None and out["mpjpe_mp_hard_mm"]:
        out["hard_improvement_pct"] = 100.0 * (
            1.0 - out["mpjpe_hard_mm"] / max(out["mpjpe_mp_hard_mm"], 1e-6)
        )
    return out
