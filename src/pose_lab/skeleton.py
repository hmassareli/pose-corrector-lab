"""Canonical skeleton used across teacher remap, MediaPipe pairing, and the corrector."""

from __future__ import annotations

LAB_JOINTS = [
    "pelvis",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
    "spine",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "neck",
    "head",
]

JOINT_TO_IDX = {n: i for i, n in enumerate(LAB_JOINTS)}

# Residual / correction targets. Body frame is always built from *uncorrected*
# MediaPipe shoulders — see labels.residual_targets / export_corrected.apply_delta.
TARGET_JOINTS = [
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
]
TARGET_IDX = [JOINT_TO_IDX[n] for n in TARGET_JOINTS]
N_TARGETS = len(TARGET_JOINTS)
DELTA_DIM = N_TARGETS * 3  # 18

TRUNK_JOINTS = ["left_shoulder", "right_shoulder", "left_hip", "right_hip"]
TRUNK_IDX = [JOINT_TO_IDX[n] for n in TRUNK_JOINTS]

# Bones as (parent, child) for viewer + bone-length losses
LAB_BONES = [
    ("pelvis", "left_hip"),
    ("pelvis", "right_hip"),
    ("left_hip", "left_knee"),
    ("right_hip", "right_knee"),
    ("left_knee", "left_ankle"),
    ("right_knee", "right_ankle"),
    ("pelvis", "spine"),
    ("spine", "neck"),
    ("neck", "head"),
    ("spine", "left_shoulder"),
    ("spine", "right_shoulder"),
    ("left_shoulder", "left_elbow"),
    ("right_shoulder", "right_elbow"),
    ("left_elbow", "left_wrist"),
    ("right_elbow", "right_wrist"),
]

# Approximate SMPL-H / SMPLX joint name → lab (best-effort; refined in remap)
# Indices follow common SMPL 24-joint ordering when exporting joints from vertices/J_regressor.
SMPL24_TO_LAB = {
    0: "pelvis",
    1: "left_hip",
    2: "right_hip",
    4: "left_knee",
    5: "right_knee",
    7: "left_ankle",
    8: "right_ankle",
    3: "spine",
    16: "left_shoulder",
    17: "right_shoulder",
    18: "left_elbow",
    19: "right_elbow",
    20: "left_wrist",
    21: "right_wrist",
    12: "neck",
    15: "head",
}

# MediaPipe Pose landmark indices (BlazePose 33) → lab joint
# https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker
MEDIAPIPE_TO_LAB = {
    23: "left_hip",
    24: "right_hip",
    25: "left_knee",
    26: "right_knee",
    27: "left_ankle",
    28: "right_ankle",
    11: "left_shoulder",
    12: "right_shoulder",
    13: "left_elbow",
    14: "right_elbow",
    15: "left_wrist",
    16: "right_wrist",
    0: "head",  # nose as head proxy; neck derived
}


def mediapipe_array_to_lab(mp_xyz, mp_conf=None):
    """Map MediaPipe (33,3) world/image landmarks into (J_lab,3) + conf.

    Neck/spine/pelvis are derived from shoulders/hips.
    """
    import numpy as np

    J = len(LAB_JOINTS)
    out = np.zeros((J, 3), dtype=np.float64)
    conf = np.zeros((J,), dtype=np.float64)

    for mpi, name in MEDIAPIPE_TO_LAB.items():
        li = JOINT_TO_IDX[name]
        out[li] = mp_xyz[mpi]
        if mp_conf is not None:
            conf[li] = float(mp_conf[mpi])
        else:
            conf[li] = 1.0

    ls, rs = out[JOINT_TO_IDX["left_shoulder"]], out[JOINT_TO_IDX["right_shoulder"]]
    lh, rh = out[JOINT_TO_IDX["left_hip"]], out[JOINT_TO_IDX["right_hip"]]
    out[JOINT_TO_IDX["pelvis"]] = 0.5 * (lh + rh)
    out[JOINT_TO_IDX["spine"]] = 0.5 * (0.5 * (ls + rs) + 0.5 * (lh + rh))
    out[JOINT_TO_IDX["neck"]] = 0.5 * (ls + rs)
    conf[JOINT_TO_IDX["pelvis"]] = 0.5 * (conf[JOINT_TO_IDX["left_hip"]] + conf[JOINT_TO_IDX["right_hip"]])
    conf[JOINT_TO_IDX["spine"]] = 0.5 * (
        0.5 * (conf[JOINT_TO_IDX["left_shoulder"]] + conf[JOINT_TO_IDX["right_shoulder"]])
        + conf[JOINT_TO_IDX["pelvis"]]
    )
    conf[JOINT_TO_IDX["neck"]] = 0.5 * (
        conf[JOINT_TO_IDX["left_shoulder"]] + conf[JOINT_TO_IDX["right_shoulder"]]
    )
    return out, conf


def smpl24_to_lab(joints24):
    """Map (24,3) or (T,24,3) SMPL joints to lab order."""
    import numpy as np

    x = np.asarray(joints24)
    single = x.ndim == 2
    if single:
        x = x[None, ...]
    T = x.shape[0]
    out = np.zeros((T, len(LAB_JOINTS), 3), dtype=np.float64)
    for si, name in SMPL24_TO_LAB.items():
        out[:, JOINT_TO_IDX[name]] = x[:, si]
    return out[0] if single else out


# Extra SMPL24 keypoints for Mixamo retarget (feet tips / hands) — not in LAB_JOINTS.
SMPL24_AVATAR_AUX = {
    "left_ankle": 7,
    "right_ankle": 8,
    "left_foot": 10,
    "right_foot": 11,
    "neck": 12,
    "head": 15,
    "left_shoulder": 16,
    "right_shoulder": 17,
    "left_elbow": 18,
    "right_elbow": 19,
    "left_wrist": 20,
    "right_wrist": 21,
    "left_hand": 22,
    "right_hand": 23,
}


def smpl24_avatar_aux(joints24):
    """Extract avatar retarget keypoints from SMPL24.

    Parameters
    ----------
    joints24 : (24, 3) or (T, 24, 3)
        Same space/units as caller (typically metres, pelvis-centered).

    Returns
    -------
    dict[str, ndarray]
        Single frame → each value (3,). Sequence → each value (T, 3).
    """
    import numpy as np

    x = np.asarray(joints24, dtype=np.float64)
    single = x.ndim == 2
    if single:
        x = x[None, ...]
    if x.shape[1] < 24:
        raise ValueError(f"expected ≥24 SMPL joints, got {x.shape}")
    out = {name: x[:, idx, :].copy() for name, idx in SMPL24_AVATAR_AUX.items()}
    if single:
        return {k: v[0] for k, v in out.items()}
    return out


def smpl24_avatar_aux_json(joints24) -> dict:
    """JSON-friendly single-frame aux (lists of 3 floats)."""
    aux = smpl24_avatar_aux(joints24)
    return {k: [float(c) for c in v.tolist()] for k, v in aux.items()}
