#!/usr/bin/env python3
"""Punch-trajectory bench for game-oriented corrector ranking.

Compares Corrector vs MediaPipe toward teacher on the test split.

Metrics (per selected extending arm, then aggregated)
----------------------------------------------------
  peak_wrist_err_mm     |C−T| at teacher peak extension (lower better)
  timing_err_frames     |argmax_reach(C) − argmax_reach(T)| on short windows
  direction_cos_err     1 − cos(vel_wrist) near peak (lower better)
  return_guard_err_mm   wrist error on retract frames after a punch
  idle_delta_mm         mean ||C−MP|| on idle/guard frames (false-punch proxy)
  jitter_accel          mean ||Δv|| of wrists on extended windows

Composite punch_score (higher better): weighted relative improvements vs MP.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB_ROOT / "src"))
sys.path.insert(0, str(LAB_ROOT / "scripts"))

from pose_lab.align import body_frame_from_pose, to_body_frame  # noqa: E402
from pose_lab.logging_utils import write_json  # noqa: E402
from pose_lab.skeleton import JOINT_TO_IDX  # noqa: E402

from bench_extension import arm_metrics, detect_extended  # noqa: E402

LS = JOINT_TO_IDX["left_shoulder"]
RS = JOINT_TO_IDX["right_shoulder"]
LE = JOINT_TO_IDX["left_elbow"]
RE = JOINT_TO_IDX["right_elbow"]
LW = JOINT_TO_IDX["left_wrist"]
RW = JOINT_TO_IDX["right_wrist"]

WEIGHTS = {
    "peak_wrist": 0.30,
    "timing": 0.15,
    "direction": 0.20,
    "return_guard": 0.15,
    "idle": 0.15,
    "jitter": 0.05,
}


def load_poses(root: Path, clip_id: str) -> np.ndarray | None:
    p = root / clip_id / "joints3d.npy"
    if not p.is_file():
        return None
    arr = np.load(p).astype(np.float64)
    if arr.ndim != 3 or arr.shape[0] < 2:
        return None
    return arr


def _reach(poses: np.ndarray, sh: int, el: int, wr: int) -> np.ndarray:
    se = np.linalg.norm(poses[:, el] - poses[:, sh], axis=-1)
    ew = np.linalg.norm(poses[:, wr] - poses[:, el], axis=-1)
    sw = np.linalg.norm(poses[:, wr] - poses[:, sh], axis=-1)
    return sw / np.maximum(se + ew, 1e-8)


def _impr(err_mp: float, err_c: float, eps: float = 1e-6) -> float:
    if not np.isfinite(err_mp) or not np.isfinite(err_c):
        return float("nan")
    return float(np.clip((err_mp - err_c) / max(err_mp, eps), -1.0, 1.0))


def _to_body(poses: np.ndarray, frame_poses: np.ndarray) -> np.ndarray:
    out = np.zeros_like(poses)
    for t in range(poses.shape[0]):
        R, scale, origin = body_frame_from_pose(frame_poses[t])
        out[t] = to_body_frame(poses[t], R, scale, origin)
    return out


def _clip_metrics(
    mp: np.ndarray,
    te: np.ndarray,
    co: np.ndarray,
    *,
    reach_thr: float,
    elbow_thr_deg: float,
    jab_margin: float,
    idle_reach_max: float,
    peak_win: int,
) -> dict[str, list[float]]:
    T = te.shape[0]
    te_m = arm_metrics(te)
    extended, active = detect_extended(te_m, reach_thr, elbow_thr_deg, jab_margin)
    idle = (te_m["reach_L"] < idle_reach_max) & (te_m["reach_R"] < idle_reach_max)

    te_b = _to_body(te, te)
    mp_b = _to_body(mp, te)
    co_b = _to_body(co, te)

    peak_mp, peak_c = [], []
    timing_mp, timing_c = [], []
    dir_mp, dir_c = [], []
    ret_mp, ret_c = [], []

    for left, wr, sh, el, reach_key in (
        (True, LW, LS, LE, "reach_L"),
        (False, RW, RS, RE, "reach_R"),
    ):
        reach_te = te_m[reach_key]
        if left:
            side_ext = extended & (active == 0)
        else:
            side_ext = extended & (active == 1)
        side_ext = side_ext | (te_m[reach_key] >= reach_thr)
        if not np.any(side_ext):
            continue
        idxs = np.flatnonzero(side_ext)
        runs: list[tuple[int, int]] = []
        s = int(idxs[0])
        prev = s
        for i in idxs[1:]:
            if i == prev + 1:
                prev = int(i)
            else:
                runs.append((s, prev))
                s = int(i)
                prev = s
        runs.append((s, prev))

        for a, b in runs:
            if b - a < 2:
                continue
            peak_t = int(a + np.argmax(reach_te[a : b + 1]))
            w0 = max(0, peak_t - peak_win)
            w1 = min(T - 1, peak_t + peak_win)
            peak_mp.append(float(np.linalg.norm(mp[peak_t, wr] - te[peak_t, wr])))
            peak_c.append(float(np.linalg.norm(co[peak_t, wr] - te[peak_t, wr])))
            r_mp = _reach(mp, sh, el, wr)[w0 : w1 + 1]
            r_co = _reach(co, sh, el, wr)[w0 : w1 + 1]
            r_te = reach_te[w0 : w1 + 1]
            t_te = int(np.argmax(r_te))
            timing_mp.append(abs(int(np.argmax(r_mp)) - t_te))
            timing_c.append(abs(int(np.argmax(r_co)) - t_te))
            if peak_t > 0:
                v_te = te_b[peak_t, wr] - te_b[peak_t - 1, wr]
                v_mp = mp_b[peak_t, wr] - mp_b[peak_t - 1, wr]
                v_co = co_b[peak_t, wr] - co_b[peak_t - 1, wr]

                def cos_err(v, ref):
                    n1 = np.linalg.norm(v)
                    n2 = np.linalg.norm(ref)
                    if n1 < 1e-8 or n2 < 1e-8:
                        return 1.0
                    return float(1.0 - np.dot(v, ref) / (n1 * n2))

                dir_mp.append(cos_err(v_mp, v_te))
                dir_c.append(cos_err(v_co, v_te))
            g0 = min(T - 1, b + 1)
            g1 = min(T - 1, b + 6)
            if g1 > g0:
                ret_mp.append(
                    float(np.mean(np.linalg.norm(mp[g0 : g1 + 1, wr] - te[g0 : g1 + 1, wr], axis=-1)))
                )
                ret_c.append(
                    float(np.mean(np.linalg.norm(co[g0 : g1 + 1, wr] - te[g0 : g1 + 1, wr], axis=-1)))
                )

    idle_delta = []
    if idle.any():
        arm = [LS, RS, LE, RE, LW, RW]
        for t in np.flatnonzero(idle):
            idle_delta.append(
                float(np.linalg.norm(co[t, arm] - mp[t, arm], axis=-1).mean())
            )

    def wrist_accel(poses: np.ndarray) -> float:
        if poses.shape[0] < 3:
            return float("nan")
        v = poses[1:] - poses[:-1]
        a = v[1:] - v[:-1]
        return float(np.linalg.norm(a[:, [LW, RW]], axis=-1).mean())

    return {
        "peak_mp": peak_mp,
        "peak_c": peak_c,
        "timing_mp": timing_mp,
        "timing_c": timing_c,
        "dir_mp": dir_mp,
        "dir_c": dir_c,
        "ret_mp": ret_mp,
        "ret_c": ret_c,
        "idle_delta": idle_delta,
        "jitter_mp": [wrist_accel(mp)],
        "jitter_c": [wrist_accel(co)],
        "jitter_te": [wrist_accel(te)],
    }


def _nanmean(xs: list[float]) -> float:
    arr = np.asarray(xs, dtype=np.float64)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return float("nan")
    return float(arr.mean())


def evaluate(
    *,
    corrected_root: Path,
    mediapipe_root: Path,
    teacher_root: Path,
    clip_ids: list[str],
    reach_thr: float,
    elbow_thr_deg: float,
    jab_margin: float,
    idle_reach_max: float,
    peak_win: int,
) -> dict[str, Any]:
    bags: dict[str, list[float]] = {
        k: []
        for k in (
            "peak_mp", "peak_c", "timing_mp", "timing_c", "dir_mp", "dir_c",
            "ret_mp", "ret_c", "idle_delta", "jitter_mp", "jitter_c", "jitter_te",
        )
    }
    used = 0
    for cid in clip_ids:
        mp = load_poses(mediapipe_root, cid)
        te = load_poses(teacher_root, cid)
        co = load_poses(corrected_root, cid)
        if mp is None or te is None or co is None:
            continue
        n = min(mp.shape[0], te.shape[0], co.shape[0])
        if n < 8:
            continue
        m = _clip_metrics(
            mp[:n],
            te[:n],
            co[:n],
            reach_thr=reach_thr,
            elbow_thr_deg=elbow_thr_deg,
            jab_margin=jab_margin,
            idle_reach_max=idle_reach_max,
            peak_win=peak_win,
        )
        for k, v in m.items():
            bags[k].extend(v)
        used += 1

    peak_mp = _nanmean(bags["peak_mp"])
    peak_c = _nanmean(bags["peak_c"])
    timing_mp = _nanmean(bags["timing_mp"])
    timing_c = _nanmean(bags["timing_c"])
    dir_mp = _nanmean(bags["dir_mp"])
    dir_c = _nanmean(bags["dir_c"])
    ret_mp = _nanmean(bags["ret_mp"])
    ret_c = _nanmean(bags["ret_c"])
    idle = _nanmean(bags["idle_delta"])
    jit_mp = _nanmean(bags["jitter_mp"])
    jit_c = _nanmean(bags["jitter_c"])
    jit_te = _nanmean(bags["jitter_te"])

    idle_impr = (
        float(np.clip(1.0 - idle / 0.05, -1.0, 1.0)) if np.isfinite(idle) else float("nan")
    )
    jitter_impr = _impr(
        abs(jit_mp - jit_te) if np.isfinite(jit_mp) and np.isfinite(jit_te) else float("nan"),
        abs(jit_c - jit_te) if np.isfinite(jit_c) and np.isfinite(jit_te) else float("nan"),
    )

    components = {
        "peak_wrist_impr": _impr(peak_mp, peak_c),
        "timing_impr": _impr(timing_mp, timing_c),
        "direction_impr": _impr(dir_mp, dir_c),
        "return_guard_impr": _impr(ret_mp, ret_c),
        "idle_safety_impr": idle_impr,
        "jitter_impr": jitter_impr,
    }
    mapping = {
        "peak_wrist": components["peak_wrist_impr"],
        "timing": components["timing_impr"],
        "direction": components["direction_impr"],
        "return_guard": components["return_guard_impr"],
        "idle": components["idle_safety_impr"],
        "jitter": components["jitter_impr"],
    }
    num = 0.0
    den = 0.0
    for k, w in WEIGHTS.items():
        v = mapping[k]
        if np.isfinite(v):
            num += w * v
            den += w
    punch_score = float(num / den) if den > 0 else float("nan")

    return {
        "n_clips": used,
        "peak_wrist_err_mm_C": peak_c * 1000.0 if np.isfinite(peak_c) else None,
        "peak_wrist_err_mm_MP": peak_mp * 1000.0 if np.isfinite(peak_mp) else None,
        "timing_err_frames_C": timing_c,
        "timing_err_frames_MP": timing_mp,
        "direction_cos_err_C": dir_c,
        "direction_cos_err_MP": dir_mp,
        "return_guard_err_mm_C": ret_c * 1000.0 if np.isfinite(ret_c) else None,
        "return_guard_err_mm_MP": ret_mp * 1000.0 if np.isfinite(ret_mp) else None,
        "idle_delta_mm": idle * 1000.0 if np.isfinite(idle) else None,
        "jitter_C": jit_c,
        "jitter_MP": jit_mp,
        "components": components,
        "punch_score": punch_score,
        "weights": WEIGHTS,
    }


def _test_clips(manifest: Path) -> list[str]:
    m = json.loads(manifest.read_text(encoding="utf-8"))
    return list(m["splits"]["test"])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corrected", type=Path, required=True, help="corrected export root")
    ap.add_argument("--label", default="best")
    ap.add_argument("--paired", type=Path, default=LAB_ROOT / "data" / "paired")
    ap.add_argument("--mediapipe", type=Path, default=LAB_ROOT / "data" / "mediapipe")
    ap.add_argument(
        "--teacher",
        type=Path,
        default=LAB_ROOT / "data" / "teacher_aligned",
    )
    ap.add_argument("--manifest", type=Path, default=LAB_ROOT / "data" / "splits" / "manifest.json")
    ap.add_argument("--reach-thr", type=float, default=0.70)
    ap.add_argument("--elbow-thr-deg", type=float, default=160.0)
    ap.add_argument("--jab-margin", type=float, default=0.08)
    ap.add_argument("--idle-reach-max", type=float, default=0.55)
    ap.add_argument("--peak-win", type=int, default=6)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    teacher_root = args.teacher if args.teacher.is_dir() else LAB_ROOT / "data" / "teacher_aligned"
    mp_root = args.mediapipe if args.mediapipe.is_dir() else LAB_ROOT / "data" / "mediapipe"
    clips = _test_clips(args.manifest)
    result = evaluate(
        corrected_root=args.corrected,
        mediapipe_root=mp_root,
        teacher_root=teacher_root,
        clip_ids=clips,
        reach_thr=args.reach_thr,
        elbow_thr_deg=args.elbow_thr_deg,
        jab_margin=args.jab_margin,
        idle_reach_max=args.idle_reach_max,
        peak_win=args.peak_win,
    )
    out = {
        "label": args.label,
        "corrected": str(args.corrected),
        **result,
    }
    print(json.dumps(out, indent=2))
    if args.out:
        write_json(args.out, out)
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
