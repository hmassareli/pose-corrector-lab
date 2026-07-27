"""Residual targets and weak motion pseudo-labels."""

from __future__ import annotations

import numpy as np

from .align import body_frame_from_pose, to_body_frame
from .skeleton import DELTA_DIM, JOINT_TO_IDX, TARGET_IDX
from .timebase import CANONICAL_FPS, velocity

MOTION_LABELS = [
    "idle_guard",
    "extend_L",
    "extend_R",
    "hookish",
    "uppercutish",
    "retract",
    "other",
]


def residual_targets(mp_pose: np.ndarray, teacher_pose: np.ndarray) -> np.ndarray:
    """Δ* in MediaPipe body frame for target joints. mp/teacher: (J,3) already trunk-aligned.

    Body frame is built from the *uncorrected* MP pose (shoulders/hips). Shoulder
    residuals are expressed in that same frame — do not rebuild the frame from
    already-corrected shoulders when applying deltas (avoids double-counting yaw).
    """
    R, scale, origin = body_frame_from_pose(mp_pose)
    mp_b = to_body_frame(mp_pose, R, scale, origin)
    te_b = to_body_frame(teacher_pose, R, scale, origin)
    deltas = []
    for i in TARGET_IDX:
        deltas.append(te_b[i] - mp_b[i])
    out = np.concatenate(deltas, axis=0).astype(np.float32)
    assert out.shape[0] == DELTA_DIM
    return out


def residual_sequence(mp: np.ndarray, teacher: np.ndarray) -> np.ndarray:
    """(T,J,3)×2 → (T, DELTA_DIM)."""
    return np.stack([residual_targets(mp[t], teacher[t]) for t in range(mp.shape[0])], axis=0)


def motion_pseudo_label(pose_b: np.ndarray, fps: float = CANONICAL_FPS) -> int:
    """Heuristic class from body-frame pose window ending at last frame.

    pose_b: (T,J,3) body-frame teacher or MP (prefer teacher).
    """
    if pose_b.shape[0] < 2:
        return MOTION_LABELS.index("other")
    t = -1
    lw = pose_b[t, JOINT_TO_IDX["left_wrist"]]
    rw = pose_b[t, JOINT_TO_IDX["right_wrist"]]
    ls = pose_b[t, JOINT_TO_IDX["left_shoulder"]]
    rs = pose_b[t, JOINT_TO_IDX["right_shoulder"]]
    le = pose_b[t, JOINT_TO_IDX["left_elbow"]]
    re = pose_b[t, JOINT_TO_IDX["right_elbow"]]

    v = velocity(pose_b[:, [JOINT_TO_IDX["left_wrist"], JOINT_TO_IDX["right_wrist"]]], fps)
    vl = v[t, 0]
    vr = v[t, 1]
    speed_l = float(np.linalg.norm(vl))
    speed_r = float(np.linalg.norm(vr))

    ext_l = float(np.linalg.norm(lw - ls))
    ext_r = float(np.linalg.norm(rw - rs))
    # extension rate
    prev = pose_b[-2]
    dext_l = ext_l - float(np.linalg.norm(prev[JOINT_TO_IDX["left_wrist"]] - prev[JOINT_TO_IDX["left_shoulder"]]))
    dext_r = ext_r - float(np.linalg.norm(prev[JOINT_TO_IDX["right_wrist"]] - prev[JOINT_TO_IDX["right_shoulder"]]))

    # retract: negative extension rate, moderate speed toward shoulder
    if dext_l < -0.02 and speed_l > 0.3:
        return MOTION_LABELS.index("retract")
    if dext_r < -0.02 and speed_r > 0.3:
        return MOTION_LABELS.index("retract")

    # uppercutish: strong +Y velocity on a wrist
    if vl[1] > 0.8 and speed_l > 0.6:
        return MOTION_LABELS.index("uppercutish")
    if vr[1] > 0.8 and speed_r > 0.6:
        return MOTION_LABELS.index("uppercutish")

    # hookish: high lateral speed, elbow flexed
    ang_l = np.linalg.norm(lw - le) + np.linalg.norm(le - ls)
    # crude flexion: wrist not far from shoulder relative to chain
    if speed_l > 0.7 and abs(vl[0]) > abs(vl[2]) and ext_l < 0.85:
        return MOTION_LABELS.index("hookish")
    if speed_r > 0.7 and abs(vr[0]) > abs(vr[2]) and ext_r < 0.85:
        return MOTION_LABELS.index("hookish")

    if dext_l > 0.025 and speed_l > 0.45:
        return MOTION_LABELS.index("extend_L")
    if dext_r > 0.025 and speed_r > 0.45:
        return MOTION_LABELS.index("extend_R")

    if speed_l < 0.25 and speed_r < 0.25 and ext_l < 0.75 and ext_r < 0.75:
        return MOTION_LABELS.index("idle_guard")

    return MOTION_LABELS.index("other")


def difficulty_score(delta: np.ndarray, conf_targets: np.ndarray) -> float:
    """Scalar hard-ish score for sampling / metrics."""
    return float(np.linalg.norm(delta) + 0.5 * (1.0 - float(conf_targets.mean())))
