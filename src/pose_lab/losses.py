"""Training losses for residual corrector."""

from __future__ import annotations

import torch
import torch.nn.functional as F

from .skeleton import DELTA_DIM, N_TARGETS

# Feature layout (include_2d=True): context joints xyz first.
# CONTEXT = pelvis, lh, rh, ls, rs, le, re, lw, rw, neck, head
# TARGET order LS,RS,LE,RE,LW,RW == context[3:9] → feature bytes [9:27]
_CTX_TARGET_START = 9
_CTX_TARGET_END = 9 + N_TARGETS * 3  # 27

# Indices within the 6-target block
_LS, _RS, _LE, _RE, _LW, _RW = 0, 1, 2, 3, 4, 5


def _joint_weights(
    device: torch.device,
    dtype: torch.dtype,
    shoulder_weight: float = 1.0,
    elbow_weight: float = 1.0,
    wrist_weight: float = 1.25,
) -> torch.Tensor:
    """Per-xyz weights for [LS, RS, LE, RE, LW, RW]."""
    w = (
        [shoulder_weight] * 6
        + [elbow_weight] * 6
        + [wrist_weight] * 6
    )
    return torch.tensor(w, device=device, dtype=dtype)


def huber_delta(
    pred: torch.Tensor,
    target: torch.Tensor,
    delta: float = 0.05,
    shoulder_weight: float = 1.0,
    elbow_weight: float = 1.0,
    wrist_weight: float = 1.25,
) -> torch.Tensor:
    """pred/target (B, DELTA_DIM) = [LS, RS, LE, RE, LW, RW] × xyz."""
    err = F.huber_loss(pred, target, reduction="none", delta=delta)
    w = _joint_weights(pred.device, pred.dtype, shoulder_weight, elbow_weight, wrist_weight)
    return (err * w).mean()


def passthrough_penalty(
    pred: torch.Tensor,
    target: torch.Tensor,
    conf_targets: torch.Tensor,
    conf_high: float = 0.85,
    true_eps: float = 0.02,
) -> torch.Tensor:
    """Penalize ‖pred‖ when teacher residual is tiny and conf is high."""
    n = pred.shape[-1] // 3
    td = target.view(-1, n, 3).norm(dim=-1).mean(dim=-1)  # (B,)
    conf = conf_targets.mean(dim=-1)
    easy = (td < true_eps) & (conf >= conf_high)
    if not easy.any():
        return pred.new_zeros(())
    pd = pred[easy].view(-1, n, 3).norm(dim=-1).mean(dim=-1)
    return pd.mean()


def smooth_delta_penalty(pred: torch.Tensor) -> torch.Tensor:
    """Weak magnitude regularizer (no temporal neighbors in window batch)."""
    return pred.pow(2).mean()


def confidence_weight(conf_targets: torch.Tensor) -> torch.Tensor:
    """Higher weight when MP is unsure. (B,) stopgrad."""
    w = 1.0 - conf_targets.mean(dim=-1).clamp(0.0, 1.0)
    return w.detach()


def mp_targets_from_features(features: torch.Tensor) -> torch.Tensor:
    """Extract MP body-frame target joints at the window's last frame.

    features: (B, T, F) — context block stores absolute body-frame xyz for
    pelvis…head; targets LS..RW sit at [9:27], matching residual layout.
    Returns (B, 6, 3).
    """
    last = features[:, -1, _CTX_TARGET_START:_CTX_TARGET_END]
    return last.reshape(features.shape[0], N_TARGETS, 3)


def _side_reach(joints: torch.Tensor, sh: int, el: int, wr: int) -> torch.Tensor:
    """Normalized reach ||wrist-shoulder|| / bone_chain. joints (B,6,3)."""
    se = (joints[:, el] - joints[:, sh]).norm(dim=-1)
    ew = (joints[:, wr] - joints[:, el]).norm(dim=-1)
    sw = (joints[:, wr] - joints[:, sh]).norm(dim=-1)
    return sw / (se + ew).clamp_min(1e-8)


def _elbow_angle_deg(joints: torch.Tensor, sh: int, el: int, wr: int) -> torch.Tensor:
    """Interior elbow angle in degrees (180 ≈ straight)."""
    a = joints[:, sh] - joints[:, el]
    b = joints[:, wr] - joints[:, el]
    denom = (a.norm(dim=-1) * b.norm(dim=-1)).clamp_min(1e-8)
    cos = (a * b).sum(dim=-1) / denom
    return torch.rad2deg(torch.acos(cos.clamp(-1.0, 1.0)))


def _arm_reach_error(
    te_r: torch.Tensor,
    co_r: torch.Tensor,
    *,
    reach_mode: str,
) -> torch.Tensor:
    """Per-sample reach error for one arm. te_r/co_r: (B,)."""
    if reach_mode == "hinge":
        # Penalize under-extension only (corrector reach below teacher).
        return F.relu(te_r - co_r)
    return (co_r - te_r).abs()


def _reconstruct_arm_targets(
    pred_delta: torch.Tensor,
    true_delta: torch.Tensor,
    features: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor]:
    """MP + Δ → teacher / corrector target joints (B,6,3) in body frame."""
    mp = mp_targets_from_features(features)
    te = mp + true_delta.view(-1, N_TARGETS, 3)
    co = mp + pred_delta.view(-1, N_TARGETS, 3)
    return te, co


def _extend_frac_stats(
    te: torch.Tensor,
    *,
    reach_thr: float,
    elbow_thr_deg: float,
) -> dict[str, float]:
    """Logging-only: fraction of frames where either arm looks extended."""
    te_rL = _side_reach(te, _LS, _LE, _LW)
    te_rR = _side_reach(te, _RS, _RE, _RW)
    eL = _elbow_angle_deg(te, _LS, _LE, _LW)
    eR = _elbow_angle_deg(te, _RS, _RE, _RW)
    ext_L = (te_rL > reach_thr) | (eL > elbow_thr_deg)
    ext_R = (te_rR > reach_thr) | (eR > elbow_thr_deg)
    either = ext_L | ext_R
    return {
        "extend_frac": float(either.float().mean().detach()),
        "n_extend": float(either.sum().detach()),
    }


def extension_geometry_losses(
    pred_delta: torch.Tensor,
    true_delta: torch.Tensor,
    features: torch.Tensor,
    *,
    reach_thr: float = 0.85,
    elbow_thr_deg: float = 160.0,
    reach_mode: str = "hinge",
) -> tuple[torch.Tensor, dict[str, float]]:
    """Per-arm reach loss for BOTH arms (no active-side gate, no hand-sep).

    Reconstructs MP body-frame targets from features, then applies Δ the same
    way as export_corrected.apply_delta (add in uncorrected-MP body frame).

    Each arm contributes its own teacher↔corrector reach error. Samples are
    soft-upweighted by that arm's teacher reach so high-extension frames matter
    more, but neither arm is dropped for being the "guard" side.
    """
    zero = pred_delta.new_zeros(())
    te, co = _reconstruct_arm_targets(pred_delta, true_delta, features)

    te_rL = _side_reach(te, _LS, _LE, _LW)
    te_rR = _side_reach(te, _RS, _RE, _RW)
    co_rL = _side_reach(co, _LS, _LE, _LW)
    co_rR = _side_reach(co, _RS, _RE, _RW)

    with torch.no_grad():
        stats = _extend_frac_stats(te, reach_thr=reach_thr, elbow_thr_deg=elbow_thr_deg)

    err_L = _arm_reach_error(te_rL, co_rL, reach_mode=reach_mode)
    err_R = _arm_reach_error(te_rR, co_rR, reach_mode=reach_mode)
    # Soft upweight by teacher reach; floor keeps low-reach arms in the pool.
    w_L = te_rL.detach().clamp_min(0.05)
    w_R = te_rR.detach().clamp_min(0.05)
    denom = (w_L.sum() + w_R.sum()).clamp_min(1e-8)
    l_reach = ((err_L * w_L).sum() + (err_R * w_R).sum()) / denom
    if not torch.isfinite(l_reach):
        return zero, stats
    return l_reach, stats


def elbow_angle_geometry_losses(
    pred_delta: torch.Tensor,
    true_delta: torch.Tensor,
    features: torch.Tensor,
    *,
    reach_thr: float = 0.85,
    elbow_thr_deg: float = 160.0,
) -> tuple[torch.Tensor, dict[str, float]]:
    """L1 on interior elbow angle (deg/180) vs teacher, BOTH arms.

    Angle = interior ∠(shoulder-elbow-wrist); 180° ≈ straight. Normalized by
    180 so the scale is roughly comparable to reach-ratio loss (unitless ~[0,1]).
    No active-side gate, no hand-sep, no under-extension hinge.
    """
    zero = pred_delta.new_zeros(())
    te, co = _reconstruct_arm_targets(pred_delta, true_delta, features)

    te_eL = _elbow_angle_deg(te, _LS, _LE, _LW)
    te_eR = _elbow_angle_deg(te, _RS, _RE, _RW)
    co_eL = _elbow_angle_deg(co, _LS, _LE, _LW)
    co_eR = _elbow_angle_deg(co, _RS, _RE, _RW)

    with torch.no_grad():
        stats = _extend_frac_stats(te, reach_thr=reach_thr, elbow_thr_deg=elbow_thr_deg)

    # Soft upweight by teacher reach (same spirit as reach loss).
    te_rL = _side_reach(te, _LS, _LE, _LW).detach().clamp_min(0.05)
    te_rR = _side_reach(te, _RS, _RE, _RW).detach().clamp_min(0.05)
    err_L = (co_eL - te_eL).abs() / 180.0
    err_R = (co_eR - te_eR).abs() / 180.0
    denom = (te_rL.sum() + te_rR.sum()).clamp_min(1e-8)
    l_angle = ((err_L * te_rL).sum() + (err_R * te_rR).sum()) / denom
    if not torch.isfinite(l_angle):
        return zero, stats
    return l_angle, stats


def total_loss(
    pred_delta: torch.Tensor,
    true_delta: torch.Tensor,
    conf_targets: torch.Tensor,
    motion_logits: torch.Tensor | None,
    motion_labels: torch.Tensor | None,
    cfg: dict,
    features: torch.Tensor | None = None,
) -> tuple[torch.Tensor, dict[str, float]]:
    lcfg = cfg.get("loss") or {}
    ig = cfg.get("inference_gate") or {}

    w_sample = confidence_weight(conf_targets)  # (B,)
    err = F.huber_loss(
        pred_delta,
        true_delta,
        reduction="none",
        delta=float(lcfg.get("huber_delta", 0.05)),
    )
    jw = _joint_weights(
        pred_delta.device,
        pred_delta.dtype,
        shoulder_weight=float(lcfg.get("shoulder_weight", 1.0)),
        elbow_weight=float(lcfg.get("elbow_weight", 1.0)),
        wrist_weight=float(lcfg.get("wrist_weight", 1.25)),
    )
    assert pred_delta.shape[-1] == DELTA_DIM and jw.numel() == DELTA_DIM
    per = (err * jw).mean(dim=-1)
    l_delta = (per * (0.5 + w_sample)).mean()

    l_pass = passthrough_penalty(
        pred_delta,
        true_delta,
        conf_targets,
        conf_high=float(ig.get("conf_high", 0.85)),
        true_eps=float(ig.get("delta_eps", 0.02)),
    )
    l_smooth = smooth_delta_penalty(pred_delta)

    l_aux = pred_delta.new_zeros(())
    if motion_logits is not None and motion_labels is not None and float(lcfg.get("w_aux", 0.0)) > 0:
        l_aux = F.cross_entropy(
            motion_logits,
            motion_labels,
            label_smoothing=float(lcfg.get("label_smoothing", 0.1)),
        )

    w_reach = float(lcfg.get("w_reach", 0.0))
    w_angle = float(lcfg.get("w_angle", 0.0))
    l_reach = pred_delta.new_zeros(())
    l_angle = pred_delta.new_zeros(())
    ext_stats: dict[str, float] = {"extend_frac": 0.0, "n_extend": 0.0}
    reach_thr = float(lcfg.get("reach_thr", 0.85))
    elbow_thr = float(lcfg.get("elbow_thr_deg", 160.0))
    if features is not None and w_reach > 0:
        l_reach, ext_stats = extension_geometry_losses(
            pred_delta,
            true_delta,
            features,
            reach_thr=reach_thr,
            elbow_thr_deg=elbow_thr,
            reach_mode=str(lcfg.get("reach_mode", "hinge")),
        )
    if features is not None and w_angle > 0:
        l_angle, ang_stats = elbow_angle_geometry_losses(
            pred_delta,
            true_delta,
            features,
            reach_thr=reach_thr,
            elbow_thr_deg=elbow_thr,
        )
        # Prefer angle-path extend_frac when reach is off (same definition).
        if w_reach <= 0:
            ext_stats = ang_stats

    loss = (
        float(lcfg.get("w_delta", 1.0)) * l_delta
        + float(lcfg.get("w_passthrough", 0.5)) * l_pass
        + float(lcfg.get("w_smooth", 0.05)) * l_smooth
        + float(lcfg.get("w_aux", 0.2)) * l_aux
        + w_reach * l_reach
        + w_angle * l_angle
    )
    parts = {
        "loss": float(loss.detach()),
        "l_delta": float(l_delta.detach()),
        "l_passthrough": float(l_pass.detach()),
        "l_smooth": float(l_smooth.detach()),
        "l_aux": float(l_aux.detach()),
        "l_reach": float(l_reach.detach()),
        "l_angle": float(l_angle.detach()),
        "extend_frac": ext_stats["extend_frac"],
    }
    return loss, parts
