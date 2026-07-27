"""Canonical 30 Hz timebase — the simple FPS solution."""

from __future__ import annotations

from typing import Tuple

import numpy as np

CANONICAL_FPS = 30.0


def frame_times(n: int, fps: float) -> np.ndarray:
    return np.arange(n, dtype=np.float64) / float(fps)


def resample_series(
    data: np.ndarray,
    src_fps: float,
    dst_fps: float = CANONICAL_FPS,
    kind: str = "linear",
) -> Tuple[np.ndarray, np.ndarray]:
    """Resample a time series from src_fps to dst_fps.

    data: (T, ...) any trailing shape
    returns: (T_dst, ...), times_dst_seconds
    """
    if src_fps <= 0 or dst_fps <= 0:
        raise ValueError("fps must be positive")
    data = np.asarray(data)
    t_src = frame_times(data.shape[0], src_fps)
    if data.shape[0] == 0:
        return data.copy(), t_src
    duration = t_src[-1]
    n_dst = int(np.floor(duration * dst_fps)) + 1
    t_dst = np.arange(n_dst, dtype=np.float64) / dst_fps
    t_dst = np.clip(t_dst, t_src[0], t_src[-1])

    flat = data.reshape(data.shape[0], -1)
    out = np.empty((n_dst, flat.shape[1]), dtype=np.float64)
    for c in range(flat.shape[1]):
        out[:, c] = np.interp(t_dst, t_src, flat[:, c])
    out = out.reshape((n_dst,) + data.shape[1:])
    return out, t_dst


def resample_to_n_frames(
    data: np.ndarray,
    src_fps: float,
    dst_fps: float,
    n_dst: int,
) -> Tuple[np.ndarray, np.ndarray]:
    """Resample onto exactly n_dst samples at dst_fps (viewer/video frame grid).

    Unlike resample_series, n_dst is fixed — used to map 30 Hz inference back to
    the source-video / MediaPipe frame count (avoids off-by-one from duration floor).
    """
    if src_fps <= 0 or dst_fps <= 0:
        raise ValueError("fps must be positive")
    if n_dst < 0:
        raise ValueError("n_dst must be non-negative")
    data = np.asarray(data)
    if data.shape[0] == 0 or n_dst == 0:
        empty = data[:0].copy()
        return empty, np.zeros(0, dtype=np.float64)
    t_src = frame_times(data.shape[0], src_fps)
    t_dst = frame_times(n_dst, dst_fps)
    t_dst = np.clip(t_dst, t_src[0], t_src[-1])
    flat = data.reshape(data.shape[0], -1)
    out = np.empty((n_dst, flat.shape[1]), dtype=np.float64)
    for c in range(flat.shape[1]):
        out[:, c] = np.interp(t_dst, t_src, flat[:, c])
    out = out.reshape((n_dst,) + data.shape[1:])
    return out, t_dst


def resample_at_times(
    data: np.ndarray,
    src_times: np.ndarray,
    dst_times: np.ndarray,
) -> np.ndarray:
    """Linearly interpolate timestamped samples onto an explicit time grid."""
    data = np.asarray(data)
    src_times = np.asarray(src_times, dtype=np.float64)
    dst_times = np.asarray(dst_times, dtype=np.float64)
    if data.shape[0] != src_times.shape[0]:
        raise ValueError("data and src_times length mismatch")
    if src_times.ndim != 1 or dst_times.ndim != 1:
        raise ValueError("src_times and dst_times must be 1D")
    if src_times.size < 2:
        raise ValueError("at least two timestamped samples are required")
    if not np.all(np.diff(src_times) > 0):
        raise ValueError("src_times must be strictly increasing")
    if dst_times.size and (
        dst_times[0] < src_times[0] - 1e-6
        or dst_times[-1] > src_times[-1] + 1e-6
    ):
        raise ValueError("destination grid lies outside source time range")

    flat = data.reshape(data.shape[0], -1)
    out = np.empty((dst_times.shape[0], flat.shape[1]), dtype=np.float64)
    for column in range(flat.shape[1]):
        out[:, column] = np.interp(dst_times, src_times, flat[:, column])
    return out.reshape((dst_times.shape[0],) + data.shape[1:]).astype(
        data.dtype,
        copy=False,
    )


def velocity(x: np.ndarray, fps: float = CANONICAL_FPS) -> np.ndarray:
    """First difference * fps → units per second. Leading frame zeros."""
    v = np.zeros_like(x)
    if x.shape[0] > 1:
        v[1:] = (x[1:] - x[:-1]) * fps
    return v


def acceleration(x: np.ndarray, fps: float = CANONICAL_FPS) -> np.ndarray:
    return velocity(velocity(x, fps), fps)
