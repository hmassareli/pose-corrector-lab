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
    extra = x.shape[-1] - _F_WITH_2D
    assert extra >= 0 and extra % _ACC == 0, (
        f"expected F={_F_WITH_2D}+k*{_ACC}, got {x.shape[-1]}"
    )
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

    # Separate multilag blocks appended after the stable F=113 layout.
    for o0 in range(_F_WITH_2D, out.shape[-1], _ACC):
        neg_x_block(slice(o0, o0 + _ACC), N_TARGETS)
        swap_joint_pairs(
            slice(o0, o0 + _ACC),
            [(0, 1), (2, 3), (4, 5)],
            N_TARGETS,
            3,
        )

    return out[0] if single else out


def mirror_motion_label(label: int) -> int:
    name = MOTION_LABELS[int(label)]
    if name == "extend_L":
        return MOTION_LABELS.index("extend_R")
    if name == "extend_R":
        return MOTION_LABELS.index("extend_L")
    return int(label)


# Slice offsets into F=113 feature vector (include_2d=True).
_OFF_IPSI = _CONTEXT  # 33
_OFF_BONES = _OFF_IPSI + _IPSI  # 45
_OFF_CONF = _OFF_BONES + _BONES  # 53
_OFF_VEL = _OFF_CONF + _CONF  # 65
_OFF_ACC = _OFF_VEL + _VEL  # 83
_OFF_2D = _OFF_ACC + _ACC  # 101


def feature_ablation_kwargs(fcfg: dict | None = None) -> dict:
    """Parse ``cfg['features']`` into kwargs for ``apply_feature_ablation``.

    ``zero_tier_a`` is a convenience that drops pure-derived blocks:
    ipsilateral shoulder-relative coords, bone/angle/reach scalars, and
    the deterministic ``1-conf`` channels (accel is separate / already baseline).
    """
    fcfg = fcfg or {}
    tier_a = bool(fcfg.get("zero_tier_a", False))
    return {
        "zero_accel": bool(fcfg.get("zero_accel", False)),
        "zero_2d": bool(fcfg.get("zero_2d", False)),
        "zero_ipsi": bool(fcfg.get("zero_ipsi", False)) or tier_a,
        "zero_bones": bool(fcfg.get("zero_bones", False)) or tier_a,
        "zero_inv_conf": bool(fcfg.get("zero_inv_conf", False)) or tier_a,
        "multilag": bool(fcfg.get("multilag", False)),
        "multilag_steps": tuple(int(s) for s in (fcfg.get("multilag_steps") or [1, 3, 6])),
        "multilag_mode": str(fcfg.get("multilag_mode", "mean")),
    }


def apply_feature_ablation(
    x: np.ndarray,
    *,
    zero_accel: bool = False,
    zero_2d: bool = False,
    zero_ipsi: bool = False,
    zero_bones: bool = False,
    zero_inv_conf: bool = False,
    multilag: bool = False,
    multilag_steps: tuple[int, ...] = (1, 3, 6),
    multilag_mode: str = "mean",
) -> np.ndarray:
    """Zero / rewrite selected feature blocks (keeps F=113 for same GRU).

    multilag: replace the acceleration block with packed target displacements
    over ``multilag_steps`` (body-frame xyz from context joints). More stable
    than raw acceleration; uses only past frames inside the window.
    """
    any_ablate = (
        zero_accel
        or zero_2d
        or zero_ipsi
        or zero_bones
        or zero_inv_conf
        or multilag
    )
    if not any_ablate:
        return x
    out = np.array(x, dtype=np.float32, copy=True)
    if multilag:
        out = _rewrite_accel_as_multilag(
            out,
            steps=multilag_steps,
            mode=multilag_mode,
        )
    elif zero_accel:
        out[..., _OFF_ACC:_OFF_2D] = 0.0
    if zero_ipsi:
        out[..., _OFF_IPSI:_OFF_BONES] = 0.0
    if zero_bones:
        out[..., _OFF_BONES:_OFF_CONF] = 0.0
    if zero_inv_conf:
        conf = out[..., _OFF_CONF:_OFF_VEL].reshape(*out.shape[:-1], N_TARGETS, 2)
        conf[..., 1] = 0.0
        out[..., _OFF_CONF:_OFF_VEL] = conf.reshape(*out.shape[:-1], _CONF)
    if zero_2d:
        out[..., _OFF_2D:_OFF_2D + _2D] = 0.0
    return out


# Context target xyz slice inside F (pelvis.. → targets LS..RW at [9:27])
_CTX_TARGET_START = 9
_CTX_TARGET_END = 9 + N_TARGETS * 3


def _rewrite_accel_as_multilag(
    x: np.ndarray,
    *,
    steps: tuple[int, ...] = (1, 3, 6),
    mode: str = "mean",
) -> np.ndarray:
    """Overwrite ACC block (18) with packed multi-lag target displacements.

    Context targets LS..RW live at feature bytes [9:27]. For each lag k in
    ``steps``, compute pose[t]-pose[t-k]. Pack into 18 dims by averaging the
    lag vectors (same F; preserves GRU width).
    """
    squeeze = x.ndim == 2
    out = np.array(x, dtype=np.float32, copy=True)
    if squeeze:
        out = out[None]
    n, t, _f = out.shape
    tgt = out[..., _CTX_TARGET_START:_CTX_TARGET_END].reshape(n, t, N_TARGETS, 3)
    lags = []
    for k in steps:
        k = int(k)
        if k < 1:
            continue
        disp = np.zeros_like(tgt)
        if k < t:
            disp[:, k:] = tgt[:, k:] - tgt[:, :-k]
        lags.append(disp)
    if mode not in {"mean", "separate"}:
        raise ValueError(f"multilag_mode must be 'mean' or 'separate', got {mode!r}")
    if not lags:
        out[..., _OFF_ACC:_OFF_2D] = 0.0
    elif mode == "mean":
        stacked = np.stack(lags, axis=0).mean(axis=0)  # (n,t,6,3)
        out[..., _OFF_ACC:_OFF_2D] = stacked.reshape(n, t, _ACC)
    else:
        packed = [lag.reshape(n, t, _ACC) for lag in lags]
        out[..., _OFF_ACC:_OFF_2D] = packed[0]
        if len(packed) > 1:
            out = np.concatenate([out, *packed[1:]], axis=-1)
    return out[0] if squeeze else out


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
        zero_ipsi: bool = False,
        zero_bones: bool = False,
        zero_inv_conf: bool = False,
        multilag: bool = False,
        multilag_steps: tuple[int, ...] = (1, 3, 6),
        multilag_mode: str = "mean",
        require_y_seq: bool = False,
    ):
        data = np.load(npz_path, allow_pickle=True)
        self.x = data["x"].astype(np.float32)
        self.y = data["y"].astype(np.float32)
        self.conf = data["conf_targets"].astype(np.float32)
        self.motion = data["motion"].astype(np.int64)
        self.difficulty = data["difficulty"].astype(np.float32)
        self.y_seq = None
        if "y_seq" in data.files:
            self.y_seq = data["y_seq"].astype(np.float32)
        elif require_y_seq:
            raise RuntimeError(
                f"{npz_path} missing y_seq — run scripts/augment_npz_yseq.py"
            )
        self.mirror_p = float(mirror_p)
        self.zero_accel = bool(zero_accel)
        self.zero_2d = bool(zero_2d)
        self.zero_ipsi = bool(zero_ipsi)
        self.zero_bones = bool(zero_bones)
        self.zero_inv_conf = bool(zero_inv_conf)
        self.multilag = bool(multilag)
        self.multilag_steps = tuple(int(s) for s in multilag_steps)
        self.multilag_mode = str(multilag_mode)

        # Precompute multilag once (getitem rewrite was too slow for full epochs).
        if self.multilag:
            print(
                f"[dataset] precomputing multilag steps={self.multilag_steps} "
                f"on {len(self.x)} windows…",
                flush=True,
            )
            self.x = _rewrite_accel_as_multilag(
                self.x,
                steps=self.multilag_steps,
                mode=self.multilag_mode,
            )
            self.multilag = False  # already baked into ACC block
            self._multilag_baked = True
        else:
            self._multilag_baked = False

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
        y_seq = None if self.y_seq is None else self.y_seq[idx]
        if self.mirror_p > 0 and np.random.rand() < self.mirror_p:
            x = mirror_features(x)
            y = mirror_residual(y)
            motion = mirror_motion_label(motion)
            if y_seq is not None:
                y_seq = np.stack([mirror_residual(y_seq[t]) for t in range(y_seq.shape[0])], axis=0)
        x = apply_feature_ablation(
            x,
            zero_accel=self.zero_accel,
            zero_2d=self.zero_2d,
            zero_ipsi=self.zero_ipsi,
            zero_bones=self.zero_bones,
            zero_inv_conf=self.zero_inv_conf,
            multilag=self.multilag,
            multilag_steps=self.multilag_steps,
            multilag_mode=self.multilag_mode,
        )
        out = {
            "x": torch.from_numpy(np.ascontiguousarray(x)),
            "y": torch.from_numpy(np.ascontiguousarray(y)),
            "conf": torch.from_numpy(np.ascontiguousarray(conf)),
            "motion": torch.tensor(motion, dtype=torch.long),
            "difficulty": torch.tensor(float(self.difficulty[idx]), dtype=torch.float32),
        }
        if y_seq is not None:
            out["y_seq"] = torch.from_numpy(np.ascontiguousarray(y_seq))
        return out
