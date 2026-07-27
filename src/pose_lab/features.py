"""Feature tensor construction for the corrector (MediaPipe → F dims)."""

from __future__ import annotations

import numpy as np

from .align import body_frame_from_pose, to_body_frame
from .skeleton import JOINT_TO_IDX, TARGET_IDX, TARGET_JOINTS
from .timebase import CANONICAL_FPS, acceleration, velocity

CONTEXT = [
    "pelvis",
    "left_hip",
    "right_hip",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "neck",
    "head",
]
CONTEXT_IDX = [JOINT_TO_IDX[n] for n in CONTEXT]


def _angle_between(a, b, c):
    """Angle at b given points a-b-c, radians."""
    u = a - b
    v = c - b
    u = u / (np.linalg.norm(u) + 1e-8)
    v = v / (np.linalg.norm(v) + 1e-8)
    return float(np.arccos(np.clip(np.dot(u, v), -1.0, 1.0)))


def pose_to_body_sequence(poses: np.ndarray) -> tuple[np.ndarray, list]:
    """(T,J,3) world → (T,J,3) body-frame using per-frame shoulders."""
    T = poses.shape[0]
    out = np.zeros_like(poses)
    frames = []
    for t in range(T):
        R, scale, origin = body_frame_from_pose(poses[t])
        out[t] = to_body_frame(poses[t], R, scale, origin)
        frames.append((R, scale, origin))
    return out, frames


def build_feature_frame(
    pose_b: np.ndarray,
    conf: np.ndarray,
    pose_b_prev: np.ndarray | None,
    pose_b_prev2: np.ndarray | None,
    pose_2d_norm: np.ndarray | None = None,
    fps: float = CANONICAL_FPS,
) -> np.ndarray:
    """Build 1D feature vector for a single frame (body-frame pose)."""
    feats: list[float] = []

    # context xyz
    for i in CONTEXT_IDX:
        feats.extend(pose_b[i].tolist())

    # wrist/elbow in ipsilateral shoulder frame (already body frame; subtract shoulder)
    for side in ("left", "right"):
        sh = pose_b[JOINT_TO_IDX[f"{side}_shoulder"]]
        for jn in (f"{side}_elbow", f"{side}_wrist"):
            feats.extend((pose_b[JOINT_TO_IDX[jn]] - sh).tolist())

    # bone lengths + elbow angles
    for side in ("left", "right"):
        sh = pose_b[JOINT_TO_IDX[f"{side}_shoulder"]]
        el = pose_b[JOINT_TO_IDX[f"{side}_elbow"]]
        wr = pose_b[JOINT_TO_IDX[f"{side}_wrist"]]
        feats.append(float(np.linalg.norm(el - sh)))
        feats.append(float(np.linalg.norm(wr - el)))
        feats.append(_angle_between(sh, el, wr))
        feats.append(float(np.linalg.norm(wr - sh)))  # extension

    # confidence on residual targets (includes shoulders)
    for name in TARGET_JOINTS:
        feats.append(float(conf[JOINT_TO_IDX[name]]))
        feats.append(float(1.0 - conf[JOINT_TO_IDX[name]]))

    # velocity / acceleration of targets (body frame)
    if pose_b_prev is None:
        feats.extend([0.0] * (len(TARGET_IDX) * 3 * 2))  # vel + acc zeros
    else:
        for i in TARGET_IDX:
            v = (pose_b[i] - pose_b_prev[i]) * fps
            feats.extend(v.tolist())
        if pose_b_prev2 is None:
            feats.extend([0.0] * (len(TARGET_IDX) * 3))
        else:
            for i in TARGET_IDX:
                v1 = (pose_b[i] - pose_b_prev[i]) * fps
                v0 = (pose_b_prev[i] - pose_b_prev2[i]) * fps
                feats.extend(((v1 - v0) * fps).tolist())

    if pose_2d_norm is not None:
        for i in TARGET_IDX:
            feats.extend(pose_2d_norm[i, :2].tolist())

    return np.asarray(feats, dtype=np.float32)


def build_feature_sequence(
    poses: np.ndarray,
    conf: np.ndarray,
    poses_2d_norm: np.ndarray | None = None,
    fps: float = CANONICAL_FPS,
) -> np.ndarray:
    """(T,J,3), (T,J) → (T,F)."""
    pose_b, _ = pose_to_body_sequence(poses)
    frames = []
    for t in range(pose_b.shape[0]):
        prev = pose_b[t - 1] if t > 0 else None
        prev2 = pose_b[t - 2] if t > 1 else None
        p2d = poses_2d_norm[t] if poses_2d_norm is not None else None
        frames.append(build_feature_frame(pose_b[t], conf[t], prev, prev2, p2d, fps))
    return np.stack(frames, axis=0)


def feature_dim(include_2d: bool = True) -> int:
    """Return F for current schema (keeps train/infer matched)."""
    dummy_p = np.zeros((3, 16, 3))
    dummy_c = np.ones((3, 16))
    p2 = np.zeros((3, 16, 2)) if include_2d else None
    return int(build_feature_sequence(dummy_p, dummy_c, p2).shape[-1])
