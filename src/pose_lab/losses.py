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


def _xyz_axis_weights(
    device: torch.device,
    dtype: torch.dtype,
    *,
    z_weight: float = 1.0,
) -> torch.Tensor:
    """Per-delta channel weights emphasizing body-frame Z when z_weight>1."""
    # Layout: 6 joints × (x,y,z)
    w = torch.tensor([1.0, 1.0, float(z_weight)], device=device, dtype=dtype)
    return w.repeat(N_TARGETS)


def _align_pred_true(
    pred_delta: torch.Tensor,
    true_delta: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Broadcast last-frame true (B,D) against sequence pred (B,T,D) if needed."""
    if pred_delta.ndim == 2 and true_delta.ndim == 2:
        return pred_delta, true_delta
    if pred_delta.ndim == 3 and true_delta.ndim == 2:
        # Supervise last frame only when no y_seq provided.
        return pred_delta[:, -1], true_delta
    if pred_delta.ndim == 3 and true_delta.ndim == 3:
        return pred_delta, true_delta
    if pred_delta.ndim == 2 and true_delta.ndim == 3:
        return pred_delta, true_delta[:, -1]
    raise ValueError(f"bad shapes pred={tuple(pred_delta.shape)} true={tuple(true_delta.shape)}")


def bone_length_loss(
    pred_delta: torch.Tensor,
    true_delta: torch.Tensor,
    features: torch.Tensor,
) -> torch.Tensor:
    """L1 on upper-arm / forearm lengths (corrector vs teacher), both arms."""
    # Use last frame for geometry when sequence pred.
    if pred_delta.ndim == 3:
        pred_delta = pred_delta[:, -1]
    if true_delta.ndim == 3:
        true_delta = true_delta[:, -1]
    te, co = _reconstruct_arm_targets(pred_delta, true_delta, features)
    losses = []
    for sh, el, wr in ((_LS, _LE, _LW), (_RS, _RE, _RW)):
        te_se = (te[:, el] - te[:, sh]).norm(dim=-1)
        te_ew = (te[:, wr] - te[:, el]).norm(dim=-1)
        co_se = (co[:, el] - co[:, sh]).norm(dim=-1)
        co_ew = (co[:, wr] - co[:, el]).norm(dim=-1)
        losses.append((co_se - te_se).abs())
        losses.append((co_ew - te_ew).abs())
    return torch.stack(losses, dim=0).mean()


def velocity_loss(
    pred_delta: torch.Tensor,
    true_delta: torch.Tensor,
    features: torch.Tensor,
    *,
    fps: float = 30.0,
) -> torch.Tensor:
    """Huber on wrist/elbow velocity of corrected vs teacher (needs y_seq).

    Reconstructs body-frame joints over the window, then compares frame-to-frame
    velocity on elbows+wrists (indices 2..5 in the 6-target block).
    """
    zero = pred_delta.new_zeros(())
    if pred_delta.ndim != 3 or true_delta.ndim != 3 or features is None:
        return zero
    if pred_delta.shape[1] < 2:
        return zero
    # features: (B,T,F) — MP targets at each frame
    mp = features[:, :, _CTX_TARGET_START:_CTX_TARGET_END].reshape(
        features.shape[0], features.shape[1], N_TARGETS, 3
    )
    te = mp + true_delta.view(true_delta.shape[0], true_delta.shape[1], N_TARGETS, 3)
    co = mp + pred_delta.view(pred_delta.shape[0], pred_delta.shape[1], N_TARGETS, 3)
    # elbows + wrists only
    te_v = (te[:, 1:, 2:] - te[:, :-1, 2:]) * float(fps)
    co_v = (co[:, 1:, 2:] - co[:, :-1, 2:]) * float(fps)
    return F.huber_loss(co_v, te_v, reduction="mean", delta=0.5)


def direction_loss(
    pred_delta: torch.Tensor,
    true_delta: torch.Tensor,
    features: torch.Tensor,
    *,
    reach_thr: float = 0.70,
    fps: float = 30.0,
) -> torch.Tensor:
    """1 - cos(vel_wrist) on active extending arms (needs y_seq)."""
    zero = pred_delta.new_zeros(())
    if pred_delta.ndim != 3 or true_delta.ndim != 3 or features is None:
        return zero
    if pred_delta.shape[1] < 2:
        return zero
    mp = features[:, :, _CTX_TARGET_START:_CTX_TARGET_END].reshape(
        features.shape[0], features.shape[1], N_TARGETS, 3
    )
    te = mp + true_delta.view(*true_delta.shape[:2], N_TARGETS, 3)
    co = mp + pred_delta.view(*pred_delta.shape[:2], N_TARGETS, 3)

    def _side(sh: int, el: int, wr: int) -> torch.Tensor:
        te_r = (te[:, :, wr] - te[:, :, sh]).norm(dim=-1)
        active = te_r[:, 1:] > float(reach_thr)
        te_vel = (te[:, 1:, wr] - te[:, :-1, wr]) * float(fps)
        co_vel = (co[:, 1:, wr] - co[:, :-1, wr]) * float(fps)
        te_n = te_vel.norm(dim=-1).clamp_min(1e-6)
        co_n = co_vel.norm(dim=-1).clamp_min(1e-6)
        cos = (te_vel * co_vel).sum(dim=-1) / (te_n * co_n)
        # Only frames that are active AND moving
        moving = te_n > 0.15
        mask = active & moving
        if not mask.any():
            return zero
        return (1.0 - cos[mask]).mean()

    l_l = _side(_LS, _LE, _LW)
    l_r = _side(_RS, _RE, _RW)
    if l_l.numel() == 0 and l_r.numel() == 0:
        return zero
    return 0.5 * (l_l + l_r)


def z_extension_loss(
    pred_delta: torch.Tensor,
    true_delta: torch.Tensor,
    features: torch.Tensor,
    *,
    reach_thr: float = 0.85,
    elbow_thr_deg: float = 160.0,
    min_teacher_depth: float = 0.05,
) -> torch.Tensor:
    """One-sided wrist depth loss on teacher-extended arms.

    Depth is measured wrist-relative-to-shoulder, so whole-body translation
    does not count as punch extension. The teacher sets the Z direction and
    required magnitude; reaching farther in that direction is not penalized.
    """
    zero = pred_delta.new_zeros(())
    if features is None:
        return zero

    if pred_delta.ndim == 2:
        pred_delta = pred_delta[:, None]
    if true_delta.ndim == 2:
        true_delta = true_delta[:, None]
    if pred_delta.ndim != 3 or true_delta.ndim != 3:
        return zero

    steps = min(pred_delta.shape[1], true_delta.shape[1], features.shape[1])
    pred_delta = pred_delta[:, -steps:]
    true_delta = true_delta[:, -steps:]
    mp = features[:, -steps:, _CTX_TARGET_START:_CTX_TARGET_END].reshape(
        features.shape[0], steps, N_TARGETS, 3
    )
    te = mp + true_delta.reshape(true_delta.shape[0], steps, N_TARGETS, 3)
    co = mp + pred_delta.reshape(pred_delta.shape[0], steps, N_TARGETS, 3)

    losses = []
    for sh, el, wr in ((_LS, _LE, _LW), (_RS, _RE, _RW)):
        te_se = (te[:, :, el] - te[:, :, sh]).norm(dim=-1)
        te_ew = (te[:, :, wr] - te[:, :, el]).norm(dim=-1)
        te_sw = (te[:, :, wr] - te[:, :, sh]).norm(dim=-1)
        te_reach = te_sw / (te_se + te_ew).clamp_min(1e-8)

        a = te[:, :, sh] - te[:, :, el]
        b = te[:, :, wr] - te[:, :, el]
        denom = (a.norm(dim=-1) * b.norm(dim=-1)).clamp_min(1e-8)
        te_angle = torch.rad2deg(torch.acos(((a * b).sum(dim=-1) / denom).clamp(-1.0, 1.0)))

        te_depth = te[:, :, wr, 2] - te[:, :, sh, 2]
        co_depth = co[:, :, wr, 2] - co[:, :, sh, 2]
        active = (
            ((te_reach >= float(reach_thr)) | (te_angle >= float(elbow_thr_deg)))
            & (te_depth.abs() >= float(min_teacher_depth))
        )
        if active.any():
            direction = torch.where(te_depth >= 0, 1.0, -1.0).detach()
            co_depth_toward_teacher = co_depth * direction
            losses.append(F.relu(te_depth.abs() - co_depth_toward_teacher)[active])

    if not losses:
        return zero
    loss = torch.cat(losses).mean()
    return loss if torch.isfinite(loss) else zero


def peak_reach_loss(
    pred_delta: torch.Tensor,
    true_delta: torch.Tensor,
    features: torch.Tensor,
    *,
    reach_thr: float = 0.85,
    elbow_thr_deg: float = 160.0,
) -> torch.Tensor:
    """Penalize only teacher-extended arms that remain shorter than teacher."""
    zero = pred_delta.new_zeros(())
    if features is None:
        return zero
    if pred_delta.ndim == 2:
        pred_delta = pred_delta[:, None]
    if true_delta.ndim == 2:
        true_delta = true_delta[:, None]
    if pred_delta.ndim != 3 or true_delta.ndim != 3:
        return zero

    steps = min(pred_delta.shape[1], true_delta.shape[1], features.shape[1])
    pred_delta = pred_delta[:, -steps:]
    true_delta = true_delta[:, -steps:]
    mp = features[:, -steps:, _CTX_TARGET_START:_CTX_TARGET_END].reshape(
        features.shape[0], steps, N_TARGETS, 3
    )
    te = mp + true_delta.reshape(true_delta.shape[0], steps, N_TARGETS, 3)
    co = mp + pred_delta.reshape(pred_delta.shape[0], steps, N_TARGETS, 3)

    losses = []
    for sh, el, wr in ((_LS, _LE, _LW), (_RS, _RE, _RW)):
        te_se = (te[:, :, el] - te[:, :, sh]).norm(dim=-1)
        te_ew = (te[:, :, wr] - te[:, :, el]).norm(dim=-1)
        te_sw = (te[:, :, wr] - te[:, :, sh]).norm(dim=-1)
        co_sw = (co[:, :, wr] - co[:, :, sh]).norm(dim=-1)
        te_reach = te_sw / (te_se + te_ew).clamp_min(1e-8)
        # Use teacher bone length as the ruler. A self-normalized corrector
        # could shrink its whole arm yet still report a reach of 1.0.
        co_reach = co_sw / (te_se + te_ew).clamp_min(1e-8)
        te_angle = _elbow_angle_deg(
            te.reshape(-1, N_TARGETS, 3), sh, el, wr
        ).reshape_as(te_reach)
        active = (te_reach >= float(reach_thr)) | (te_angle >= float(elbow_thr_deg))
        if active.any():
            losses.append(F.relu(te_reach - co_reach)[active])

    if not losses:
        return zero
    loss = torch.cat(losses).mean()
    return loss if torch.isfinite(loss) else zero


def total_loss(
    pred_delta: torch.Tensor,
    true_delta: torch.Tensor,
    conf_targets: torch.Tensor,
    motion_logits: torch.Tensor | None,
    motion_labels: torch.Tensor | None,
    cfg: dict,
    features: torch.Tensor | None = None,
    true_delta_seq: torch.Tensor | None = None,
) -> tuple[torch.Tensor, dict[str, float]]:
    lcfg = cfg.get("loss") or {}
    ig = cfg.get("inference_gate") or {}

    sequence_position_mode = str(lcfg.get("sequence_position_mode", "all"))
    if sequence_position_mode not in {"all", "last"}:
        raise ValueError(
            f"loss.sequence_position_mode must be 'all' or 'last', got {sequence_position_mode!r}"
        )

    # Temporal losses can use the full sequence while position remains aligned
    # with the last frame consumed by deployed inference.
    if (
        sequence_position_mode == "all"
        and true_delta_seq is not None
        and pred_delta.ndim == 3
    ):
        true_for_pos = true_delta_seq
    else:
        true_for_pos = true_delta
    pred_pos, true_pos = _align_pred_true(pred_delta, true_for_pos)

    # Confidence: last-frame (B,) — broadcast over T if needed.
    w_sample = confidence_weight(conf_targets)  # (B,)
    err = F.huber_loss(
        pred_pos,
        true_pos,
        reduction="none",
        delta=float(lcfg.get("huber_delta", 0.05)),
    )
    jw = _joint_weights(
        pred_pos.device,
        pred_pos.dtype,
        shoulder_weight=float(lcfg.get("shoulder_weight", 1.0)),
        elbow_weight=float(lcfg.get("elbow_weight", 1.0)),
        wrist_weight=float(lcfg.get("wrist_weight", 1.25)),
    )
    aw = _xyz_axis_weights(
        pred_pos.device,
        pred_pos.dtype,
        z_weight=float(lcfg.get("z_weight", 1.0)),
    )
    assert pred_pos.shape[-1] == DELTA_DIM and jw.numel() == DELTA_DIM
    per = (err * jw * aw).mean(dim=-1)  # (B,) or (B,T)
    if per.ndim == 2:
        # Mildly upweight later frames (punch landing near window end).
        t = per.shape[1]
        tw = torch.linspace(0.5, 1.0, t, device=per.device, dtype=per.dtype)
        per = (per * tw).mean(dim=-1)
    l_delta = (per * (0.5 + w_sample)).mean()

    # Pass-through / smooth always on last-frame residual.
    pred_last = pred_delta[:, -1] if pred_delta.ndim == 3 else pred_delta
    true_last = true_delta if true_delta.ndim == 2 else true_delta[:, -1]
    l_pass = passthrough_penalty(
        pred_last,
        true_last,
        conf_targets,
        conf_high=float(ig.get("conf_high", 0.85)),
        true_eps=float(ig.get("delta_eps", 0.02)),
    )
    l_smooth = smooth_delta_penalty(pred_last)

    l_aux = pred_delta.new_zeros(())
    if motion_logits is not None and motion_labels is not None and float(lcfg.get("w_aux", 0.0)) > 0:
        l_aux = F.cross_entropy(
            motion_logits,
            motion_labels,
            label_smoothing=float(lcfg.get("label_smoothing", 0.1)),
        )

    w_reach = float(lcfg.get("w_reach", 0.0))
    w_angle = float(lcfg.get("w_angle", 0.0))
    w_bone = float(lcfg.get("w_bone_len", 0.0))  # legacy w_bone was never wired; use w_bone_len
    w_vel = float(lcfg.get("w_vel", 0.0))
    w_dir = float(lcfg.get("w_dir", 0.0))
    w_z_extend = float(lcfg.get("w_z_extend", 0.0))
    w_peak_reach = float(lcfg.get("w_peak_reach", 0.0))
    l_reach = pred_delta.new_zeros(())
    l_angle = pred_delta.new_zeros(())
    l_bone = pred_delta.new_zeros(())
    l_vel = pred_delta.new_zeros(())
    l_dir = pred_delta.new_zeros(())
    l_z_extend = pred_delta.new_zeros(())
    l_peak_reach = pred_delta.new_zeros(())
    ext_stats: dict[str, float] = {"extend_frac": 0.0, "n_extend": 0.0}
    reach_thr = float(lcfg.get("reach_thr", 0.85))
    elbow_thr = float(lcfg.get("elbow_thr_deg", 160.0))
    if features is not None and w_reach > 0:
        l_reach, ext_stats = extension_geometry_losses(
            pred_last,
            true_last,
            features,
            reach_thr=reach_thr,
            elbow_thr_deg=elbow_thr,
            reach_mode=str(lcfg.get("reach_mode", "hinge")),
        )
    if features is not None and w_angle > 0:
        l_angle, ang_stats = elbow_angle_geometry_losses(
            pred_last,
            true_last,
            features,
            reach_thr=reach_thr,
            elbow_thr_deg=elbow_thr,
        )
        if w_reach <= 0:
            ext_stats = ang_stats
    if features is not None and w_bone > 0:
        l_bone = bone_length_loss(pred_last, true_last, features)
    seq_true = true_delta_seq if true_delta_seq is not None else None
    if features is not None and w_vel > 0 and seq_true is not None and pred_delta.ndim == 3:
        l_vel = velocity_loss(pred_delta, seq_true, features)
    if features is not None and w_dir > 0 and seq_true is not None and pred_delta.ndim == 3:
        l_dir = direction_loss(
            pred_delta,
            seq_true,
            features,
            reach_thr=float(lcfg.get("dir_reach_thr", 0.70)),
        )
    z_true = seq_true if seq_true is not None and pred_delta.ndim == 3 else true_last
    if features is not None and w_z_extend > 0:
        l_z_extend = z_extension_loss(
            pred_delta,
            z_true,
            features,
            reach_thr=float(lcfg.get("z_extend_reach_thr", reach_thr)),
            elbow_thr_deg=float(lcfg.get("z_extend_elbow_thr_deg", elbow_thr)),
            min_teacher_depth=float(lcfg.get("z_extend_min_depth", 0.05)),
        )
    if features is not None and w_peak_reach > 0:
        l_peak_reach = peak_reach_loss(
            pred_delta,
            z_true,
            features,
            reach_thr=float(lcfg.get("peak_reach_thr", reach_thr)),
            elbow_thr_deg=float(lcfg.get("peak_reach_elbow_thr_deg", elbow_thr)),
        )

    loss = (
        float(lcfg.get("w_delta", 1.0)) * l_delta
        + float(lcfg.get("w_passthrough", 0.5)) * l_pass
        + float(lcfg.get("w_smooth", 0.05)) * l_smooth
        + float(lcfg.get("w_aux", 0.2)) * l_aux
        + w_reach * l_reach
        + w_angle * l_angle
        + w_bone * l_bone
        + w_vel * l_vel
        + w_dir * l_dir
        + w_z_extend * l_z_extend
        + w_peak_reach * l_peak_reach
    )
    parts = {
        "loss": float(loss.detach()),
        "l_delta": float(l_delta.detach()),
        "l_passthrough": float(l_pass.detach()),
        "l_smooth": float(l_smooth.detach()),
        "l_aux": float(l_aux.detach()),
        "l_reach": float(l_reach.detach()),
        "l_angle": float(l_angle.detach()),
        "l_bone": float(l_bone.detach()),
        "l_vel": float(l_vel.detach()),
        "l_dir": float(l_dir.detach()),
        "l_z_extend": float(l_z_extend.detach()),
        "l_peak_reach": float(l_peak_reach.detach()),
        "extend_frac": ext_stats["extend_frac"],
    }
    return loss, parts
