"""Body-frame normalization and teacher↔MP trunk alignment."""

from __future__ import annotations

import numpy as np

from .skeleton import JOINT_TO_IDX, TRUNK_IDX


def _safe_norm(v: np.ndarray, eps: float = 1e-8) -> np.ndarray:
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.maximum(n, eps)


def _shoulder_width(pose: np.ndarray) -> float:
    ls = pose[JOINT_TO_IDX["left_shoulder"]]
    rs = pose[JOINT_TO_IDX["right_shoulder"]]
    w = float(np.linalg.norm(rs - ls))
    if w < 1e-4:
        lh = pose[JOINT_TO_IDX["left_hip"]]
        rh = pose[JOINT_TO_IDX["right_hip"]]
        w = float(np.linalg.norm(rh - lh)) + 1e-4
    return w


def body_frame_from_pose(pose: np.ndarray) -> tuple[np.ndarray, float, np.ndarray]:
    """Build orthonormal body frame from a single (J,3) pose.

    Returns R (3,3) with rows = body axes in world, scale, origin.
    Body coords: x_body = R @ (x_world - origin) / scale
    """
    ls = pose[JOINT_TO_IDX["left_shoulder"]]
    rs = pose[JOINT_TO_IDX["right_shoulder"]]
    lh = pose[JOINT_TO_IDX["left_hip"]]
    rh = pose[JOINT_TO_IDX["right_hip"]]
    origin = 0.5 * (ls + rs)
    # Convention: +X = left_shoulder → right_shoulder
    x_axis = _safe_norm((rs - ls).reshape(1, 3))[0]
    hip_mid = 0.5 * (lh + rh)
    # +Y roughly up along trunk (hip → shoulder)
    y_approx = origin - hip_mid
    if np.linalg.norm(y_approx) < 1e-6:
        y_approx = np.array([0.0, 1.0, 0.0])
    # orthonormalize
    z_axis = _safe_norm(np.cross(x_axis, y_approx).reshape(1, 3))[0]
    y_axis = _safe_norm(np.cross(z_axis, x_axis).reshape(1, 3))[0]
    R = np.stack([x_axis, y_axis, z_axis], axis=0)  # (3,3)
    scale = float(np.linalg.norm(rs - ls))
    if scale < 1e-4:
        scale = float(np.linalg.norm(rh - lh)) + 1e-4
    return R, scale, origin


def to_body_frame(pose: np.ndarray, R: np.ndarray, scale: float, origin: np.ndarray) -> np.ndarray:
    return ((pose - origin) @ R.T) / scale


def from_body_frame(pose_b: np.ndarray, R: np.ndarray, scale: float, origin: np.ndarray) -> np.ndarray:
    return (pose_b * scale) @ R + origin


def procrustes_trunk(src: np.ndarray, dst: np.ndarray) -> tuple[np.ndarray, float, np.ndarray]:
    """Similarity align src trunk to dst trunk. Returns R, scale, translation applied as
    aligned = scale * src @ R.T + t  (row-vector convention).

    Prefer trunk_translate_scale for pairing — full Procrustes kills torso yaw.
    """
    s = src[TRUNK_IDX].astype(np.float64)
    d = dst[TRUNK_IDX].astype(np.float64)
    mu_s = s.mean(axis=0)
    mu_d = d.mean(axis=0)
    s0 = s - mu_s
    d0 = d - mu_d
    cov = s0.T @ d0 / s.shape[0]
    U, S, Vt = np.linalg.svd(cov)
    R = Vt.T @ U.T
    if np.linalg.det(R) < 0:
        Vt[-1, :] *= -1
        R = Vt.T @ U.T
    var_s = (s0 ** 2).sum() / s.shape[0]
    scale = float(S.sum() / (var_s + 1e-12))
    t = mu_d - scale * (mu_s @ R.T)
    return R, scale, t


def apply_similarity(pose: np.ndarray, R: np.ndarray, scale: float, t: np.ndarray) -> np.ndarray:
    return scale * (pose @ R.T) + t


def trunk_translate_scale(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """Match trunk centroid + shoulder width; keep src orientation (yaw/twist).

    Kills root walk relative to dst without forcing MP trunk rotation onto teacher.
    """
    src = src.astype(np.float64, copy=False)
    dst = dst.astype(np.float64, copy=False)
    mu_s = src[TRUNK_IDX].mean(axis=0)
    mu_d = dst[TRUNK_IDX].mean(axis=0)
    scale = _shoulder_width(dst) / _shoulder_width(src)
    return (scale * (src - mu_s) + mu_d).astype(np.float32, copy=False)


def sequence_align_teacher_to_mp(teacher: np.ndarray, mp: np.ndarray) -> np.ndarray:
    """Per-frame translate+scale trunk align. Preserves teacher torso rotation."""
    if teacher.shape != mp.shape:
        raise ValueError(f"shape mismatch teacher={teacher.shape} mp={mp.shape}")
    out = np.empty_like(teacher)
    for i in range(teacher.shape[0]):
        out[i] = trunk_translate_scale(teacher[i], mp[i])
    return out
