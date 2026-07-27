"""Window dataset from data/dataset/*.npz."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import torch
from torch.utils.data import Dataset

from .labels import MOTION_LABELS
from .skeleton import DELTA_DIM, N_TARGETS

# Feature layout from features.build_feature_frame (include_2d=True → F=113)
# Targets: LS,RS,LE,RE,LW,RW
_CONTEXT = 11 * 3  # 33
_IPSI = 4 * 3  # 12  (elbow/wrist relative to ipsilateral shoulder)
_BONES = 8
_CONF = N_TARGETS * 2  # 12
_VEL = N_TARGETS * 3  # 18
_ACC = N_TARGETS * 3  # 18
_2D = N_TARGETS * 2  # 12
_F_WITH_2D = _CONTEXT + _IPSI + _BONES + _CONF + _VEL + _ACC + _2D  # 113


def mirror_residual(y: np.ndarray) -> np.ndarray:
    """(DELTA_DIM,) LS,RS,LE,RE,LW,RW → swap L/R sides, negate body X."""
    y = y.reshape(N_TARGETS, 3).copy()
    for a, b in ((0, 1), (2, 3), (4, 5)):
        y[[a, b]] = y[[b, a]]
    y[:, 0] *= -1.0
    return y.reshape(DELTA_DIM)


def mirror_features(x: np.ndarray) -> np.ndarray:
    """Mirror a (T, F) or (F,) feature vector built with include_2d=True."""
    single = x.ndim == 1
    if single:
        x = x[None]
    assert x.shape[-1] == _F_WITH_2D, f"expected F={_F_WITH_2D}, got {x.shape[-1]}"
    out = x.copy()

    def neg_x_block(sl: slice, n_joints: int) -> None:
        block = out[..., sl].reshape(out.shape[0], n_joints, 3)
        block[..., 0] *= -1.0
        out[..., sl] = block.reshape(out.shape[0], n_joints * 3)

    def swap_joint_pairs(sl: slice, pairs: list[tuple[int, int]], n_joints: int, width: int) -> None:
        block = out[..., sl].reshape(out.shape[0], n_joints, width)
        for a, b in pairs:
            tmp = block[:, a].copy()
            block[:, a] = block[:, b]
            block[:, b] = tmp
        out[..., sl] = block.reshape(out.shape[0], n_joints * width)

    # context: pelvis, lh, rh, ls, rs, le, re, lw, rw, neck, head
    neg_x_block(slice(0, 33), 11)
    swap_joint_pairs(slice(0, 33), [(1, 2), (3, 4), (5, 6), (7, 8)], 11, 3)

    # ipsilateral relative: L_el, L_wr, R_el, R_wr
    o = 33
    neg_x_block(slice(o, o + 12), 4)
    swap_joint_pairs(slice(o, o + 12), [(0, 2), (1, 3)], 4, 3)

    # bones: L4, R4
    o = 45
    bones = out[..., o : o + 8].reshape(out.shape[0], 2, 4).copy()
    bones[:, [0, 1]] = bones[:, [1, 0]]
    out[..., o : o + 8] = bones.reshape(out.shape[0], 8)

    # conf pairs: ls,rs,le,re,lw,rw
    o = 53
    conf = out[..., o : o + _CONF].reshape(out.shape[0], N_TARGETS, 2).copy()
    for a, b in ((0, 1), (2, 3), (4, 5)):
        conf[:, [a, b]] = conf[:, [b, a]]
    out[..., o : o + _CONF] = conf.reshape(out.shape[0], _CONF)

    # vel / acc targets LS,RS,LE,RE,LW,RW
    for o0 in (53 + _CONF, 53 + _CONF + _VEL):
        neg_x_block(slice(o0, o0 + _VEL), N_TARGETS)
        swap_joint_pairs(slice(o0, o0 + _VEL), [(0, 1), (2, 3), (4, 5)], N_TARGETS, 3)

    # 2d: ls,rs,le,re,lw,rw — horizontal flip in image: x' = 1 - x
    o = 53 + _CONF + _VEL + _ACC
    p2 = out[..., o : o + _2D].reshape(out.shape[0], N_TARGETS, 2).copy()
    for a, b in ((0, 1), (2, 3), (4, 5)):
        p2[:, [a, b]] = p2[:, [b, a]]
    p2[..., 0] = 1.0 - p2[..., 0]
    out[..., o : o + _2D] = p2.reshape(out.shape[0], _2D)

    return out[0] if single else out


def mirror_motion_label(label: int) -> int:
    name = MOTION_LABELS[int(label)]
    if name == "extend_L":
        return MOTION_LABELS.index("extend_R")
    if name == "extend_R":
        return MOTION_LABELS.index("extend_L")
    return int(label)


# Slice offsets into F=113 feature vector (include_2d=True).
_OFF_VEL = _CONTEXT + _IPSI + _BONES + _CONF  # 65
_OFF_ACC = _OFF_VEL + _VEL  # 83
_OFF_2D = _OFF_ACC + _ACC  # 101


def apply_feature_ablation(
    x: np.ndarray,
    *,
    zero_accel: bool = False,
    zero_2d: bool = False,
) -> np.ndarray:
    """Zero selected feature blocks in-place-safe copy (keeps F=113 for same GRU)."""
    if not zero_accel and not zero_2d:
        return x
    out = np.array(x, dtype=np.float32, copy=True)
    if zero_accel:
        out[..., _OFF_ACC:_OFF_2D] = 0.0
    if zero_2d:
        out[..., _OFF_2D:_OFF_2D + _2D] = 0.0
    return out


class WindowNPZDataset(Dataset):
    def __init__(
        self,
        npz_path: str | Path,
        *,
        mirror_p: float = 0.0,
        hard_only: bool = False,
        hard_percentile: float = 80.0,
        conf_below: float = 0.5,
        zero_accel: bool = False,
        zero_2d: bool = False,
    ):
        data = np.load(npz_path, allow_pickle=True)
        self.x = data["x"].astype(np.float32)
        self.y = data["y"].astype(np.float32)
        self.conf = data["conf_targets"].astype(np.float32)
        self.motion = data["motion"].astype(np.int64)
        self.difficulty = data["difficulty"].astype(np.float32)
        self.mirror_p = float(mirror_p)
        self.zero_accel = bool(zero_accel)
        self.zero_2d = bool(zero_2d)

        self.indices = np.arange(len(self.x))
        if hard_only and len(self.indices):
            from .metrics import hard_mask

            mask = hard_mask(self.y, self.conf, hard_percentile, conf_below)
            self.indices = np.nonzero(mask)[0]
            if len(self.indices) == 0:
                self.indices = np.arange(len(self.x))

    def __len__(self) -> int:
        return int(len(self.indices))

    def __getitem__(self, i: int) -> dict[str, torch.Tensor]:
        idx = int(self.indices[i])
        x = self.x[idx]
        y = self.y[idx]
        conf = self.conf[idx]
        motion = int(self.motion[idx])
        if self.mirror_p > 0 and np.random.rand() < self.mirror_p:
            x = mirror_features(x)
            y = mirror_residual(y)
            motion = mirror_motion_label(motion)
        x = apply_feature_ablation(x, zero_accel=self.zero_accel, zero_2d=self.zero_2d)
        return {
            "x": torch.from_numpy(np.ascontiguousarray(x)),
            "y": torch.from_numpy(np.ascontiguousarray(y)),
            "conf": torch.from_numpy(np.ascontiguousarray(conf)),
            "motion": torch.tensor(motion, dtype=torch.long),
            "difficulty": torch.tensor(float(self.difficulty[idx]), dtype=torch.float32),
        }
