#!/usr/bin/env python3
"""DEPRECATED for ablation ranking — use bench_extended_shoulder_level_hands.py.

Kept only for ad-hoc analysis. Leaderboard primary metric is hand proximity on
teacher extended + shoulder-level frames (not this composite game_score).

---
Game-relevant boxing evaluation: would this corrector help in-game vs raw MP?

Compares corrected export vs MediaPipe vs teacher_aligned on the test split,
same source-fps timeline as the viewer.

Frame sets (from teacher pose)
------------------------------
  Extended / jab frames — identical rule to bench_extension / bench_arm_angles:
    active reach > reach_thr OR active elbow > elbow_thr_deg,
    AND (active − guard) reach >= jab_margin.
  Idle / guard frames — BOTH arms have reach < idle_reach_max (default 0.55).

Metrics
-------
  Jab (extended, active side):
    - elbow angle MAE vs teacher (deg)
    - forwardness MAE: body-frame +Z of (wrist−shoulder), using the *teacher*
      body frame each frame so C/MP/T share one axis (punch depth)
    - reach-ratio MAE vs teacher (secondary)

  Guard (same extended frames, non-active side):
    - elbow angle MAE vs teacher
    - wrist–shoulder span MAE vs teacher (hand stays back)

  Idle safety (idle frames):
    - mean ||C − MP|| on arm targets (shoulders/elbows/wrists), body-frame of MP
      — lower = less over-correction of idle/guard
    - also report mean ||T − MP|| as reference difficulty

  Temporal (extended windows, active wrist):
    - mean ||Δv|| of active wrist (frame-to-frame accel proxy); lower better

Composite game_score (higher = more helpful in-game)
----------------------------------------------------
  Each component is a relative improvement of corrector vs MediaPipe toward
  teacher (or toward lower idle/jitter), clamped to [-1, 1]:

    impr(err) = (mae_MP − mae_C) / max(mae_MP, eps)

  game_score =
      0.35 * jab_angle_impr
    + 0.20 * jab_forward_impr
    + 0.25 * guard_impr          # mean of guard elbow + guard span impr
    + 0.15 * idle_safety_impr    # 1 − ||C−MP|| / max(||T−MP||, eps)  (clipped)
    + 0.05 * jitter_impr

  Idle term rewards staying close to MP when teacher is idle (don't ruin guard).
  Reach-ratio MAE is reported but NOT in the composite (avoids stretch hacking).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB_ROOT / "src"))
sys.path.insert(0, str(LAB_ROOT / "scripts"))

from pose_lab.align import body_frame_from_pose, to_body_frame  # noqa: E402
from pose_lab.logging_utils import write_json  # noqa: E402
from pose_lab.skeleton import JOINT_TO_IDX, TARGET_IDX  # noqa: E402

from bench_extension import arm_metrics, detect_extended  # noqa: E402

LS = JOINT_TO_IDX["left_shoulder"]
RS = JOINT_TO_IDX["right_shoulder"]
LE = JOINT_TO_IDX["left_elbow"]
RE = JOINT_TO_IDX["right_elbow"]
LW = JOINT_TO_IDX["left_wrist"]
RW = JOINT_TO_IDX["right_wrist"]

WEIGHTS = {
    "jab_angle": 0.35,
    "jab_forward": 0.20,
    "guard": 0.25,
    "idle_safety": 0.15,
    "jitter": 0.05,
}


def load_poses(root: Path, clip_id: str) -> np.ndarray | None:
    p = root / clip_id / "joints3d.npy"
    if not p.is_file():
        return None
    arr = np.load(p).astype(np.float64)
    if arr.ndim != 3 or arr.shape[0] < 1:
        return None
    return arr


def _elbow_angles_deg(poses: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    out = []
    for sh, el, wr in ((LS, LE, LW), (RS, RE, RW)):
        a = poses[:, sh] - poses[:, el]
        b = poses[:, wr] - poses[:, el]
        na = np.linalg.norm(a, axis=-1)
        nb = np.linalg.norm(b, axis=-1)
        denom = np.maximum(na * nb, 1e-8)
        cos = np.clip(np.sum(a * b, axis=-1) / denom, -1.0, 1.0)
        out.append(np.degrees(np.arccos(cos)))
    return out[0], out[1]


def _forwardness_body_z(
    poses: np.ndarray,
    frame_poses: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Per-frame wrist−shoulder +Z in body frame built from frame_poses (teacher)."""
    T = poses.shape[0]
    out_L = np.zeros(T, dtype=np.float64)
    out_R = np.zeros(T, dtype=np.float64)
    for t in range(T):
        R, scale, origin = body_frame_from_pose(frame_poses[t])
        pb = to_body_frame(poses[t], R, scale, origin)
        out_L[t] = float(pb[LW, 2] - pb[LS, 2])
        out_R[t] = float(pb[RW, 2] - pb[RS, 2])
    return out_L, out_R


def _pick(side_R: np.ndarray, left: np.ndarray, right: np.ndarray) -> np.ndarray:
    return np.where(side_R, right, left)


def _mae(a: np.ndarray, b: np.ndarray) -> float:
    if a.size == 0:
        return float("nan")
    return float(np.mean(np.abs(a - b)))


def _impr(mae_mp: float, mae_c: float, eps: float = 1e-6) -> float:
    if not np.isfinite(mae_mp) or not np.isfinite(mae_c):
        return float("nan")
    return float(np.clip((mae_mp - mae_c) / max(mae_mp, eps), -1.0, 1.0))


def _wrist_accel_mag(poses: np.ndarray, wrist_idx: int) -> np.ndarray:
    """||v[t]-v[t-1]|| with v = p[t]-p[t-1]; length T with first two zeros."""
    T = poses.shape[0]
    out = np.zeros(T, dtype=np.float64)
    if T < 3:
        return out
    p = poses[:, wrist_idx]
    v = np.diff(p, axis=0)  # T-1
    a = np.diff(v, axis=0)  # T-2
    out[2:] = np.linalg.norm(a, axis=-1)
    return out


def _target_mpjpe_bf(pred: np.ndarray, ref: np.ndarray, frame_pose: np.ndarray) -> np.ndarray:
    """Per-frame mean L2 on TARGET joints in body frame of frame_pose (usually MP)."""
    T = pred.shape[0]
    out = np.zeros(T, dtype=np.float64)
    for t in range(T):
        R, scale, origin = body_frame_from_pose(frame_pose[t])
        pb = to_body_frame(pred[t], R, scale, origin)
        rb = to_body_frame(ref[t], R, scale, origin)
        d = pb[TARGET_IDX] - rb[TARGET_IDX]
        out[t] = float(np.linalg.norm(d, axis=-1).mean())
    return out


def evaluate_corrector(
    *,
    clip_ids: list[str],
    teacher_root: Path,
    mp_root: Path,
    corrected_root: Path,
    reach_thr: float,
    elbow_thr_deg: float,
    jab_margin: float,
    idle_reach_max: float,
) -> dict[str, Any]:
    # Pooled arrays
    jab_te_ang: list[np.ndarray] = []
    jab_mp_ang: list[np.ndarray] = []
    jab_co_ang: list[np.ndarray] = []
    jab_te_fwd: list[np.ndarray] = []
    jab_mp_fwd: list[np.ndarray] = []
    jab_co_fwd: list[np.ndarray] = []
    jab_te_reach: list[np.ndarray] = []
    jab_mp_reach: list[np.ndarray] = []
    jab_co_reach: list[np.ndarray] = []

    g_te_ang: list[np.ndarray] = []
    g_mp_ang: list[np.ndarray] = []
    g_co_ang: list[np.ndarray] = []
    g_te_span: list[np.ndarray] = []
    g_mp_span: list[np.ndarray] = []
    g_co_span: list[np.ndarray] = []

    idle_c_mp: list[np.ndarray] = []
    idle_t_mp: list[np.ndarray] = []

    jit_mp: list[np.ndarray] = []
    jit_co: list[np.ndarray] = []

    n_extended = 0
    n_idle = 0
    n_used = 0
    n_skipped = 0
    n_frames = 0

    for clip_id in clip_ids:
        te = load_poses(teacher_root, clip_id)
        mp = load_poses(mp_root, clip_id)
        co = load_poses(corrected_root, clip_id)
        if te is None or mp is None or co is None:
            n_skipped += 1
            continue
        if te.shape[1:] != mp.shape[1:] or co.shape[1:] != mp.shape[1:]:
            n_skipped += 1
            continue
        n = min(te.shape[0], mp.shape[0], co.shape[0])
        te, mp, co = te[:n], mp[:n], co[:n]
        n_used += 1
        n_frames += int(n)

        te_m = arm_metrics(te)
        mp_m = arm_metrics(mp)
        co_m = arm_metrics(co)
        extended, active = detect_extended(te_m, reach_thr, elbow_thr_deg, jab_margin)
        idle = (te_m["reach_L"] < idle_reach_max) & (te_m["reach_R"] < idle_reach_max)

        te_eL, te_eR = _elbow_angles_deg(te)
        mp_eL, mp_eR = _elbow_angles_deg(mp)
        co_eL, co_eR = _elbow_angles_deg(co)
        # Forwardness in teacher body frame (shared axis)
        te_fL, te_fR = _forwardness_body_z(te, te)
        mp_fL, mp_fR = _forwardness_body_z(mp, te)
        co_fL, co_fR = _forwardness_body_z(co, te)

        if extended.any():
            side_R = active.astype(bool)
            m = extended
            n_extended += int(m.sum())
            jab_te_ang.append(_pick(side_R[m], te_eL[m], te_eR[m]))
            jab_mp_ang.append(_pick(side_R[m], mp_eL[m], mp_eR[m]))
            jab_co_ang.append(_pick(side_R[m], co_eL[m], co_eR[m]))
            jab_te_fwd.append(_pick(side_R[m], te_fL[m], te_fR[m]))
            jab_mp_fwd.append(_pick(side_R[m], mp_fL[m], mp_fR[m]))
            jab_co_fwd.append(_pick(side_R[m], co_fL[m], co_fR[m]))
            jab_te_reach.append(_pick(side_R[m], te_m["reach_L"][m], te_m["reach_R"][m]))
            jab_mp_reach.append(_pick(side_R[m], mp_m["reach_L"][m], mp_m["reach_R"][m]))
            jab_co_reach.append(_pick(side_R[m], co_m["reach_L"][m], co_m["reach_R"][m]))

            g_te_ang.append(_pick(side_R[m], te_eR[m], te_eL[m]))  # guard = other
            g_mp_ang.append(_pick(side_R[m], mp_eR[m], mp_eL[m]))
            g_co_ang.append(_pick(side_R[m], co_eR[m], co_eL[m]))
            g_te_span.append(_pick(side_R[m], te_m["span_R"][m], te_m["span_L"][m]))
            g_mp_span.append(_pick(side_R[m], mp_m["span_R"][m], mp_m["span_L"][m]))
            g_co_span.append(_pick(side_R[m], co_m["span_R"][m], co_m["span_L"][m]))

            # Active-wrist accel on extended frames (need full series then mask)
            a_mp_L = _wrist_accel_mag(mp, LW)
            a_mp_R = _wrist_accel_mag(mp, RW)
            a_co_L = _wrist_accel_mag(co, LW)
            a_co_R = _wrist_accel_mag(co, RW)
            jit_mp.append(_pick(side_R[m], a_mp_L[m], a_mp_R[m]))
            jit_co.append(_pick(side_R[m], a_co_L[m], a_co_R[m]))

        if idle.any():
            n_idle += int(idle.sum())
            idle_c_mp.append(_target_mpjpe_bf(co, mp, mp)[idle])
            idle_t_mp.append(_target_mpjpe_bf(te, mp, mp)[idle])

    def cat(xs: list[np.ndarray]) -> np.ndarray:
        return np.concatenate(xs) if xs else np.asarray([], dtype=np.float64)

    j_te_a, j_mp_a, j_co_a = cat(jab_te_ang), cat(jab_mp_ang), cat(jab_co_ang)
    j_te_f, j_mp_f, j_co_f = cat(jab_te_fwd), cat(jab_mp_fwd), cat(jab_co_fwd)
    j_te_r, j_mp_r, j_co_r = cat(jab_te_reach), cat(jab_mp_reach), cat(jab_co_reach)
    g_te_a, g_mp_a, g_co_a = cat(g_te_ang), cat(g_mp_ang), cat(g_co_ang)
    g_te_s, g_mp_s, g_co_s = cat(g_te_span), cat(g_mp_span), cat(g_co_span)
    id_cm, id_tm = cat(idle_c_mp), cat(idle_t_mp)
    jm, jc = cat(jit_mp), cat(jit_co)

    jab_angle_mae_c = _mae(j_co_a, j_te_a)
    jab_angle_mae_mp = _mae(j_mp_a, j_te_a)
    jab_fwd_mae_c = _mae(j_co_f, j_te_f)
    jab_fwd_mae_mp = _mae(j_mp_f, j_te_f)
    jab_reach_mae_c = _mae(j_co_r, j_te_r)
    jab_reach_mae_mp = _mae(j_mp_r, j_te_r)

    guard_ang_mae_c = _mae(g_co_a, g_te_a)
    guard_ang_mae_mp = _mae(g_mp_a, g_te_a)
    guard_span_mae_c = _mae(g_co_s, g_te_s)
    guard_span_mae_mp = _mae(g_mp_s, g_te_s)

    idle_c_mean = float(id_cm.mean()) if id_cm.size else float("nan")
    idle_t_mean = float(id_tm.mean()) if id_tm.size else float("nan")
    # Idle safety: stay near MP when idle; normalize by how far teacher is from MP
    if np.isfinite(idle_c_mean) and np.isfinite(idle_t_mean):
        idle_safety_impr = float(
            np.clip(1.0 - idle_c_mean / max(idle_t_mean, 1e-6), -1.0, 1.0)
        )
    else:
        idle_safety_impr = float("nan")

    jitter_c = float(jc.mean()) if jc.size else float("nan")
    jitter_mp = float(jm.mean()) if jm.size else float("nan")

    jab_angle_impr = _impr(jab_angle_mae_mp, jab_angle_mae_c)
    jab_forward_impr = _impr(jab_fwd_mae_mp, jab_fwd_mae_c)
    guard_ang_impr = _impr(guard_ang_mae_mp, guard_ang_mae_c)
    guard_span_impr = _impr(guard_span_mae_mp, guard_span_mae_c)
    if np.isfinite(guard_ang_impr) and np.isfinite(guard_span_impr):
        guard_impr = 0.5 * (guard_ang_impr + guard_span_impr)
    else:
        guard_impr = float("nan")
    jitter_impr = _impr(jitter_mp, jitter_c)  # lower jitter better → same form

    comps = {
        "jab_angle": jab_angle_impr,
        "jab_forward": jab_forward_impr,
        "guard": guard_impr,
        "idle_safety": idle_safety_impr,
        "jitter": jitter_impr,
    }
    # Weighted sum; if a component is NaN, redistribute its weight
    w_sum = 0.0
    score = 0.0
    for k, w in WEIGHTS.items():
        v = comps[k]
        if np.isfinite(v):
            score += w * v
            w_sum += w
    game_score = float(score / w_sum) if w_sum > 0 else float("nan")

    return {
        "corrected_root": str(corrected_root),
        "n_clips_used": n_used,
        "n_clips_skipped": n_skipped,
        "n_frames_total": n_frames,
        "n_extended": n_extended,
        "n_idle": n_idle,
        "weights": dict(WEIGHTS),
        "game_score": game_score,
        "components": {
            "jab_angle_impr": jab_angle_impr,
            "jab_forward_impr": jab_forward_impr,
            "guard_impr": guard_impr,
            "idle_safety_impr": idle_safety_impr,
            "jitter_impr": jitter_impr,
        },
        "jab": {
            "elbow_mae_C_T": jab_angle_mae_c,
            "elbow_mae_MP_T": jab_angle_mae_mp,
            "forward_mae_C_T": jab_fwd_mae_c,
            "forward_mae_MP_T": jab_fwd_mae_mp,
            "reach_mae_C_T": jab_reach_mae_c,
            "reach_mae_MP_T": jab_reach_mae_mp,
            "n": int(j_te_a.size),
        },
        "guard": {
            "elbow_mae_C_T": guard_ang_mae_c,
            "elbow_mae_MP_T": guard_ang_mae_mp,
            "span_mae_C_T": guard_span_mae_c,
            "span_mae_MP_T": guard_span_mae_mp,
            "n": int(g_te_a.size),
        },
        "idle": {
            "mean_corrector_vs_mp_bf": idle_c_mean,
            "mean_teacher_vs_mp_bf": idle_t_mean,
            "n": int(id_cm.size),
        },
        "jitter": {
            "active_wrist_accel_mean_C": jitter_c,
            "active_wrist_accel_mean_MP": jitter_mp,
            "n": int(jm.size),
        },
    }


def print_summary(label: str, r: dict[str, Any]) -> None:
    print(f"\n=== game_boxing [{label}] game_score={r['game_score']:.4f} ===")
    c = r["components"]
    print(
        f"  jab_angle_impr={c['jab_angle_impr']:+.3f}  "
        f"jab_forward_impr={c['jab_forward_impr']:+.3f}  "
        f"guard_impr={c['guard_impr']:+.3f}"
    )
    print(
        f"  idle_safety_impr={c['idle_safety_impr']:+.3f}  "
        f"jitter_impr={c['jitter_impr']:+.3f}"
    )
    j, g = r["jab"], r["guard"]
    print(
        f"  jab elbow MAE C/MP: {j['elbow_mae_C_T']:.2f} / {j['elbow_mae_MP_T']:.2f} deg"
    )
    print(
        f"  jab forward MAE C/MP: {j['forward_mae_C_T']:.4f} / {j['forward_mae_MP_T']:.4f}"
    )
    print(
        f"  guard elbow MAE C/MP: {g['elbow_mae_C_T']:.2f} / {g['elbow_mae_MP_T']:.2f} deg  "
        f"span MAE C/MP: {g['span_mae_C_T']:.4f} / {g['span_mae_MP_T']:.4f}"
    )
    print(
        f"  idle ||C-MP||={r['idle']['mean_corrector_vs_mp_bf']:.4f}  "
        f"||T-MP||={r['idle']['mean_teacher_vs_mp_bf']:.4f}  "
        f"n_ext={r['n_extended']} n_idle={r['n_idle']}"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", type=Path, default=LAB_ROOT / "data" / "splits" / "manifest.json")
    ap.add_argument("--split", default="test", choices=("train", "val", "test"))
    ap.add_argument("--teacher-root", type=Path, default=LAB_ROOT / "data" / "teacher_aligned")
    ap.add_argument("--mp-root", type=Path, default=LAB_ROOT / "data" / "mediapipe")
    ap.add_argument(
        "--corrected",
        action="append",
        default=None,
        help="LABEL=DIR (repeatable). Default: use --corrected-root with --label",
    )
    ap.add_argument("--corrected-root", type=Path, default=None)
    ap.add_argument("--label", default="corrector")
    ap.add_argument("--reach-thr", type=float, default=0.85)
    ap.add_argument("--elbow-thr-deg", type=float, default=160.0)
    ap.add_argument("--jab-margin", type=float, default=0.08)
    ap.add_argument("--idle-reach-max", type=float, default=0.55)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--run", type=Path, default=None, help="Optional run dir for default out path")
    args = ap.parse_args()

    specs: list[tuple[str, Path]] = []
    if args.corrected:
        for item in args.corrected:
            if "=" not in item:
                raise SystemExit(f"--corrected must be LABEL=DIR, got: {item}")
            lab, path_s = item.split("=", 1)
            specs.append((lab.strip(), Path(path_s.strip())))
    elif args.corrected_root is not None:
        specs.append((args.label, args.corrected_root))
    else:
        raise SystemExit("Provide --corrected LABEL=DIR or --corrected-root")

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    clip_ids: list[str] = list(manifest["splits"][args.split])

    compare: dict[str, Any] = {}
    for lab, root in specs:
        if not root.is_dir():
            raise SystemExit(f"corrected dir missing for {lab}: {root}")
        print(f"Evaluating game_boxing {lab} from {root} ...", flush=True)
        r = evaluate_corrector(
            clip_ids=clip_ids,
            teacher_root=args.teacher_root,
            mp_root=args.mp_root,
            corrected_root=root,
            reach_thr=args.reach_thr,
            elbow_thr_deg=args.elbow_thr_deg,
            jab_margin=args.jab_margin,
            idle_reach_max=args.idle_reach_max,
        )
        print_summary(lab, r)
        compare[lab] = r

    run = Path(args.run) if args.run else None
    out = args.out
    if out is None:
        if run is not None:
            out = run / "eval" / "game_boxing.json"
        else:
            out = LAB_ROOT / "data" / "evals" / f"game_boxing_{args.split}.json"
    out.parent.mkdir(parents=True, exist_ok=True)

    result = {
        "created_unix": time.time(),
        "benchmark": "game_boxing_helpfulness",
        "note": (
            "Composite game_score: higher = more helpful in-game vs raw MediaPipe. "
            "Jab/guard use teacher-extended frames; idle uses low-reach frames. "
            "Reach MAE reported but excluded from score (anti stretch-hack)."
        ),
        "split": args.split,
        "timebase": "source_fps_viewer_exports",
        "weights": dict(WEIGHTS),
        "definition": {
            "forwardness": "body-frame +Z of (wrist-shoulder) using teacher body frame",
            "idle": f"both teacher reaches < {args.idle_reach_max}",
            "game_score": (
                "0.35*jab_angle_impr + 0.20*jab_forward_impr + 0.25*guard_impr "
                "+ 0.15*idle_safety_impr + 0.05*jitter_impr; "
                "impr=(mae_MP-mae_C)/mae_MP clipped [-1,1]; "
                "idle_safety=1-||C-MP||/||T-MP||"
            ),
        },
        "compare": compare,
        "results_path": str(out),
    }
    write_json(out, result)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
