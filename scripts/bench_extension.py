#!/usr/bin/env python3
"""Benchmark arm-extension quality: teacher vs MediaPipe vs corrector.

Uses source-fps viewer exports under data/{mediapipe,corrected,teacher_aligned}/
that share matching n_frames. Teacher-extended frames are detected from
teacher_aligned poses; reach is compared on the active (more extended) side.

Extension / reach definition
----------------------------
  reach(side) = ||wrist - shoulder|| / bone_chain
  bone_chain  = ||shoulder - elbow|| + ||elbow - wrist||   (per-frame, same pose)

  Values near 1.0 ~ fully straight arm. Values are clipped to [0, 1.05] for
  reporting stability (numerical noise / slight overstretch).

Teacher-extended frame (OR of):
  - reach > --reach-thr (default 0.85), OR
  - elbow angle > --elbow-thr-deg (default 160 deg)
Optionally require jab asymmetry: active reach - guard reach >= --jab-margin
(default 0.08). Active side = argmax teacher reach on that frame.

Metrics (on teacher-extended frames, active side unless noted):
  - mean/median reach for teacher, MP, corrector
  - % frames where corrector reach > MP reach
  - mean (teacher - corrector) and (teacher - MP) reach gaps
  - guard-hand: non-active side ||wrist - shoulder|| (raw meters) and
    distance of guard wrist toward neck (||wrist - neck||)
  - hand separation: ||wrist_active - wrist_guard|| (= ||L_wrist - R_wrist||)
    raw and / shoulder_width; % frames corrector > MP; gaps to teacher
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

from pose_lab.logging_utils import write_json  # noqa: E402
from pose_lab.skeleton import JOINT_TO_IDX  # noqa: E402

LS = JOINT_TO_IDX["left_shoulder"]
RS = JOINT_TO_IDX["right_shoulder"]
LE = JOINT_TO_IDX["left_elbow"]
RE = JOINT_TO_IDX["right_elbow"]
LW = JOINT_TO_IDX["left_wrist"]
RW = JOINT_TO_IDX["right_wrist"]
NECK = JOINT_TO_IDX["neck"]


def _elbow_angles_deg(poses: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Interior elbow angle in degrees (180° = straight). poses (T,J,3)."""
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


def arm_metrics(poses: np.ndarray) -> dict[str, np.ndarray]:
    """Per-frame arm reach / chain / raw span for both sides."""
    reach = {}
    chain = {}
    span = {}
    for side, sh, el, wr in (
        ("L", LS, LE, LW),
        ("R", RS, RE, RW),
    ):
        se = np.linalg.norm(poses[:, el] - poses[:, sh], axis=-1)
        ew = np.linalg.norm(poses[:, wr] - poses[:, el], axis=-1)
        sw = np.linalg.norm(poses[:, wr] - poses[:, sh], axis=-1)
        ch = np.maximum(se + ew, 1e-8)
        chain[side] = ch
        span[side] = sw
        reach[side] = np.clip(sw / ch, 0.0, 1.05)
    ang_l, ang_r = _elbow_angles_deg(poses)
    # Guard retraction proxies (raw meters in aligned space)
    guard_to_neck = {
        "L": np.linalg.norm(poses[:, LW] - poses[:, NECK], axis=-1),
        "R": np.linalg.norm(poses[:, RW] - poses[:, NECK], axis=-1),
    }
    # Active-guard hand separation (= inter-wrist distance; active/guard partition
    # does not change the Euclidean distance between the two wrists).
    shoulder_w = np.maximum(
        np.linalg.norm(poses[:, LS] - poses[:, RS], axis=-1), 1e-8
    )
    hand_sep = np.linalg.norm(poses[:, LW] - poses[:, RW], axis=-1)
    return {
        "reach_L": reach["L"],
        "reach_R": reach["R"],
        "chain_L": chain["L"],
        "chain_R": chain["R"],
        "span_L": span["L"],
        "span_R": span["R"],
        "elbow_L": ang_l,
        "elbow_R": ang_r,
        "to_neck_L": guard_to_neck["L"],
        "to_neck_R": guard_to_neck["R"],
        "shoulder_width": shoulder_w,
        "hand_sep": hand_sep,
        "hand_sep_norm": hand_sep / shoulder_w,
    }


def detect_extended(
    teacher_m: dict[str, np.ndarray],
    reach_thr: float,
    elbow_thr_deg: float,
    jab_margin: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (is_extended bool[T], active_side int[T] with 0=L, 1=R)."""
    rL, rR = teacher_m["reach_L"], teacher_m["reach_R"]
    eL, eR = teacher_m["elbow_L"], teacher_m["elbow_R"]
    active_R = rR >= rL
    active_reach = np.where(active_R, rR, rL)
    guard_reach = np.where(active_R, rL, rR)
    active_elbow = np.where(active_R, eR, eL)
    extended = (active_reach > reach_thr) | (active_elbow > elbow_thr_deg)
    if jab_margin > 0:
        extended = extended & ((active_reach - guard_reach) >= jab_margin)
    active = active_R.astype(np.int8)  # 0=L, 1=R
    return extended, active


def _pick(side_is_R: np.ndarray, left: np.ndarray, right: np.ndarray) -> np.ndarray:
    return np.where(side_is_R, right, left)


def summarize_arrays(name: str, arr: np.ndarray) -> dict[str, float]:
    if arr.size == 0:
        return {f"{name}_mean": float("nan"), f"{name}_median": float("nan")}
    return {
        f"{name}_mean": float(np.mean(arr)),
        f"{name}_median": float(np.median(arr)),
    }


def clip_stats(
    te: dict[str, np.ndarray],
    mp: dict[str, np.ndarray],
    corr: dict[str, np.ndarray],
    extended: np.ndarray,
    active: np.ndarray,
) -> dict[str, Any]:
    if not extended.any():
        return {
            "n_extended": 0,
            "n_active_L": 0,
            "n_active_R": 0,
        }
    side_R = active.astype(bool)[extended]
    # Active-side reach
    te_r = _pick(side_R, te["reach_L"][extended], te["reach_R"][extended])
    mp_r = _pick(side_R, mp["reach_L"][extended], mp["reach_R"][extended])
    co_r = _pick(side_R, corr["reach_L"][extended], corr["reach_R"][extended])
    # Guard (non-active) side
    te_g_span = _pick(side_R, te["span_R"][extended], te["span_L"][extended])
    mp_g_span = _pick(side_R, mp["span_R"][extended], mp["span_L"][extended])
    co_g_span = _pick(side_R, corr["span_R"][extended], corr["span_L"][extended])
    te_g_neck = _pick(side_R, te["to_neck_R"][extended], te["to_neck_L"][extended])
    mp_g_neck = _pick(side_R, mp["to_neck_R"][extended], mp["to_neck_L"][extended])
    co_g_neck = _pick(side_R, corr["to_neck_R"][extended], corr["to_neck_L"][extended])
    # Guard reach (normalized) for completeness
    te_g_reach = _pick(side_R, te["reach_R"][extended], te["reach_L"][extended])
    mp_g_reach = _pick(side_R, mp["reach_R"][extended], mp["reach_L"][extended])
    co_g_reach = _pick(side_R, corr["reach_R"][extended], corr["reach_L"][extended])

    gap_co = te_r - co_r
    gap_mp = te_r - mp_r
    better = co_r > mp_r

    # Hand separation (active wrist <-> guard wrist) on same extended frames
    te_sep = te["hand_sep"][extended]
    mp_sep = mp["hand_sep"][extended]
    co_sep = corr["hand_sep"][extended]
    te_sep_n = te["hand_sep_norm"][extended]
    mp_sep_n = mp["hand_sep_norm"][extended]
    co_sep_n = corr["hand_sep_norm"][extended]
    sep_better = co_sep > mp_sep
    sep_gap_co = te_sep - co_sep
    sep_gap_mp = te_sep - mp_sep
    sep_n_better = co_sep_n > mp_sep_n
    sep_n_gap_co = te_sep_n - co_sep_n
    sep_n_gap_mp = te_sep_n - mp_sep_n

    out: dict[str, Any] = {
        "n_extended": int(extended.sum()),
        "n_active_L": int((~active.astype(bool) & extended).sum()),
        "n_active_R": int((active.astype(bool) & extended).sum()),
        "pct_corrector_reach_gt_mp": float(100.0 * better.mean()),
        "mean_gap_teacher_minus_corrector": float(gap_co.mean()),
        "mean_gap_teacher_minus_mp": float(gap_mp.mean()),
        "median_gap_teacher_minus_corrector": float(np.median(gap_co)),
        "median_gap_teacher_minus_mp": float(np.median(gap_mp)),
        "pct_corrector_hand_sep_gt_mp": float(100.0 * sep_better.mean()),
        "mean_gap_hand_sep_teacher_minus_corrector": float(sep_gap_co.mean()),
        "mean_gap_hand_sep_teacher_minus_mp": float(sep_gap_mp.mean()),
        "median_gap_hand_sep_teacher_minus_corrector": float(np.median(sep_gap_co)),
        "median_gap_hand_sep_teacher_minus_mp": float(np.median(sep_gap_mp)),
        "pct_corrector_hand_sep_norm_gt_mp": float(100.0 * sep_n_better.mean()),
        "mean_gap_hand_sep_norm_teacher_minus_corrector": float(sep_n_gap_co.mean()),
        "mean_gap_hand_sep_norm_teacher_minus_mp": float(sep_n_gap_mp.mean()),
        "median_gap_hand_sep_norm_teacher_minus_corrector": float(np.median(sep_n_gap_co)),
        "median_gap_hand_sep_norm_teacher_minus_mp": float(np.median(sep_n_gap_mp)),
    }
    out.update(summarize_arrays("reach_teacher", te_r))
    out.update(summarize_arrays("reach_mp", mp_r))
    out.update(summarize_arrays("reach_corrector", co_r))
    out.update(summarize_arrays("guard_span_teacher", te_g_span))
    out.update(summarize_arrays("guard_span_mp", mp_g_span))
    out.update(summarize_arrays("guard_span_corrector", co_g_span))
    out.update(summarize_arrays("guard_to_neck_teacher", te_g_neck))
    out.update(summarize_arrays("guard_to_neck_mp", mp_g_neck))
    out.update(summarize_arrays("guard_to_neck_corrector", co_g_neck))
    out.update(summarize_arrays("guard_reach_teacher", te_g_reach))
    out.update(summarize_arrays("guard_reach_mp", mp_g_reach))
    out.update(summarize_arrays("guard_reach_corrector", co_g_reach))
    out.update(summarize_arrays("hand_sep_teacher", te_sep))
    out.update(summarize_arrays("hand_sep_mp", mp_sep))
    out.update(summarize_arrays("hand_sep_corrector", co_sep))
    out.update(summarize_arrays("hand_sep_norm_teacher", te_sep_n))
    out.update(summarize_arrays("hand_sep_norm_mp", mp_sep_n))
    out.update(summarize_arrays("hand_sep_norm_corrector", co_sep_n))
    # How much more retracted guard is vs teacher (positive = hand farther out than teacher)
    out["mean_guard_span_corrector_minus_teacher"] = float((co_g_span - te_g_span).mean())
    out["mean_guard_span_mp_minus_teacher"] = float((mp_g_span - te_g_span).mean())
    return out


def load_trio(
    data_root: Path,
    clip_id: str,
    *,
    corrected_root: Path | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    corr_base = corrected_root if corrected_root is not None else (data_root / "corrected")
    paths = {
        "mp": data_root / "mediapipe" / clip_id / "joints3d.npy",
        "corr": corr_base / clip_id / "joints3d.npy",
        "te": data_root / "teacher_aligned" / clip_id / "joints3d.npy",
    }
    if not all(p.is_file() for p in paths.values()):
        return None
    mp = np.load(paths["mp"]).astype(np.float64)
    corr = np.load(paths["corr"]).astype(np.float64)
    te = np.load(paths["te"]).astype(np.float64)
    if mp.ndim != 3 or corr.ndim != 3 or te.ndim != 3:
        return None
    n = min(mp.shape[0], corr.shape[0], te.shape[0])
    if n < 1:
        return None
    if mp.shape[0] != corr.shape[0] or mp.shape[0] != te.shape[0]:
        # Prefer matching source-fps; truncate to shared prefix if slight mismatch
        mp, corr, te = mp[:n], corr[:n], te[:n]
    return mp, corr, te


def aggregate_clips(per_clip: list[dict[str, Any]]) -> dict[str, Any]:
    """Frame-weighted aggregate over clips with n_extended > 0."""
    usable = [c for c in per_clip if c.get("n_extended", 0) > 0]
    if not usable:
        return {"n_extended": 0, "n_clips_with_extended": 0}

    def wmean(key: str) -> float:
        num = 0.0
        den = 0.0
        for c in usable:
            v = c.get(key)
            if v is None or (isinstance(v, float) and np.isnan(v)):
                continue
            w = float(c["n_extended"])
            num += float(v) * w
            den += w
        return float(num / den) if den else float("nan")

    keys = [
        "reach_teacher_mean",
        "reach_mp_mean",
        "reach_corrector_mean",
        "reach_teacher_median",
        "reach_mp_median",
        "reach_corrector_median",
        "pct_corrector_reach_gt_mp",
        "mean_gap_teacher_minus_corrector",
        "mean_gap_teacher_minus_mp",
        "median_gap_teacher_minus_corrector",
        "median_gap_teacher_minus_mp",
        "guard_span_teacher_mean",
        "guard_span_mp_mean",
        "guard_span_corrector_mean",
        "guard_to_neck_teacher_mean",
        "guard_to_neck_mp_mean",
        "guard_to_neck_corrector_mean",
        "guard_reach_teacher_mean",
        "guard_reach_mp_mean",
        "guard_reach_corrector_mean",
        "mean_guard_span_corrector_minus_teacher",
        "mean_guard_span_mp_minus_teacher",
        "hand_sep_teacher_mean",
        "hand_sep_mp_mean",
        "hand_sep_corrector_mean",
        "hand_sep_teacher_median",
        "hand_sep_mp_median",
        "hand_sep_corrector_median",
        "pct_corrector_hand_sep_gt_mp",
        "mean_gap_hand_sep_teacher_minus_corrector",
        "mean_gap_hand_sep_teacher_minus_mp",
        "median_gap_hand_sep_teacher_minus_corrector",
        "median_gap_hand_sep_teacher_minus_mp",
        "hand_sep_norm_teacher_mean",
        "hand_sep_norm_mp_mean",
        "hand_sep_norm_corrector_mean",
        "hand_sep_norm_teacher_median",
        "hand_sep_norm_mp_median",
        "hand_sep_norm_corrector_median",
        "pct_corrector_hand_sep_norm_gt_mp",
        "mean_gap_hand_sep_norm_teacher_minus_corrector",
        "mean_gap_hand_sep_norm_teacher_minus_mp",
        "median_gap_hand_sep_norm_teacher_minus_corrector",
        "median_gap_hand_sep_norm_teacher_minus_mp",
    ]
    out: dict[str, Any] = {
        "n_extended": int(sum(c["n_extended"] for c in usable)),
        "n_active_L": int(sum(c.get("n_active_L", 0) for c in usable)),
        "n_active_R": int(sum(c.get("n_active_R", 0) for c in usable)),
        "n_clips_with_extended": len(usable),
        "n_clips_total": len(per_clip),
    }
    for k in keys:
        out[k] = wmean(k)
    return out


def print_summary(result: dict[str, Any]) -> None:
    defn = result["definition"]
    agg = result["aggregate"]
    print("=" * 72)
    print("ARM EXTENSION BENCHMARK")
    print("=" * 72)
    print(f"split: {result['split']}  |  timebase: {result['timebase']}")
    print(f"clips used: {result['n_clips_used']}/{result['n_clips_listed']}  "
          f"(skipped missing/mismatch: {result['n_clips_skipped']})")
    print()
    print("Definition:")
    print(f"  reach = ||wrist-shoulder|| / (||shoulder-elbow|| + ||elbow-wrist||)")
    print(f"  teacher-extended if active reach > {defn['reach_thr']} OR "
          f"elbow angle > {defn['elbow_thr_deg']} deg")
    print(f"  jab margin (active-guard reach): >= {defn['jab_margin']}")
    print(f"  active side = larger teacher reach on that frame")
    print()
    print("-" * 72)
    print("AGGREGATE (frame-weighted over teacher-extended frames)")
    print("-" * 72)
    if agg.get("n_extended", 0) == 0:
        print("No teacher-extended frames found.")
        return
    print(f"  n_extended frames : {agg['n_extended']}  "
          f"(L-active {agg['n_active_L']}, R-active {agg['n_active_R']})")
    print(f"  clips with ext.   : {agg['n_clips_with_extended']}/{agg['n_clips_total']}")
    print()
    print("  Active-side REACH (1.0 ~ fully straight):")
    print(f"    Teacher    mean={agg['reach_teacher_mean']:.4f}  median={agg['reach_teacher_median']:.4f}")
    print(f"    MediaPipe  mean={agg['reach_mp_mean']:.4f}  median={agg['reach_mp_median']:.4f}")
    print(f"    Corrector  mean={agg['reach_corrector_mean']:.4f}  median={agg['reach_corrector_median']:.4f}")
    print()
    print(f"  % frames corrector reach > MP : {agg['pct_corrector_reach_gt_mp']:.1f}%")
    print(f"  mean gap (teacher - MP)       : {agg['mean_gap_teacher_minus_mp']:.4f}")
    print(f"  mean gap (teacher - corrector): {agg['mean_gap_teacher_minus_corrector']:.4f}")
    print(f"  median gap (teacher - MP)     : {agg['median_gap_teacher_minus_mp']:.4f}")
    print(f"  median gap (teacher - corr)   : {agg['median_gap_teacher_minus_corrector']:.4f}")
    print()
    print("  Guard hand (non-active side):")
    print(f"    span ||wrist-shoulder||  T={agg['guard_span_teacher_mean']:.4f}  "
          f"MP={agg['guard_span_mp_mean']:.4f}  C={agg['guard_span_corrector_mean']:.4f}")
    print(f"    ||wrist-neck||           T={agg['guard_to_neck_teacher_mean']:.4f}  "
          f"MP={agg['guard_to_neck_mp_mean']:.4f}  C={agg['guard_to_neck_corrector_mean']:.4f}")
    print(f"    guard reach (norm)       T={agg['guard_reach_teacher_mean']:.4f}  "
          f"MP={agg['guard_reach_mp_mean']:.4f}  C={agg['guard_reach_corrector_mean']:.4f}")
    print(f"    mean (C - T) guard span  : {agg['mean_guard_span_corrector_minus_teacher']:+.4f}  "
          f"(+ = more extended / less retracted than teacher)")
    print(f"    mean (MP - T) guard span : {agg['mean_guard_span_mp_minus_teacher']:+.4f}")
    print()
    print("  Hand SEPARATION ||active_wrist - guard_wrist|| (= ||L_wrist - R_wrist||):")
    print(f"    Teacher    mean={agg['hand_sep_teacher_mean']:.4f}  median={agg['hand_sep_teacher_median']:.4f}")
    print(f"    MediaPipe  mean={agg['hand_sep_mp_mean']:.4f}  median={agg['hand_sep_mp_median']:.4f}")
    print(f"    Corrector  mean={agg['hand_sep_corrector_mean']:.4f}  median={agg['hand_sep_corrector_median']:.4f}")
    print(f"  % frames corrector sep > MP : {agg['pct_corrector_hand_sep_gt_mp']:.1f}%")
    print(f"  mean gap (teacher - MP)     : {agg['mean_gap_hand_sep_teacher_minus_mp']:.4f}")
    print(f"  mean gap (teacher - corr)   : {agg['mean_gap_hand_sep_teacher_minus_corrector']:.4f}")
    print(f"  median gap (teacher - MP)   : {agg['median_gap_hand_sep_teacher_minus_mp']:.4f}")
    print(f"  median gap (teacher - corr) : {agg['median_gap_hand_sep_teacher_minus_corrector']:.4f}")
    print()
    print("  Hand SEPARATION / shoulder_width (scale-invariant):")
    print(f"    Teacher    mean={agg['hand_sep_norm_teacher_mean']:.4f}  median={agg['hand_sep_norm_teacher_median']:.4f}")
    print(f"    MediaPipe  mean={agg['hand_sep_norm_mp_mean']:.4f}  median={agg['hand_sep_norm_mp_median']:.4f}")
    print(f"    Corrector  mean={agg['hand_sep_norm_corrector_mean']:.4f}  median={agg['hand_sep_norm_corrector_median']:.4f}")
    print(f"  % frames corrector sep_n > MP : {agg['pct_corrector_hand_sep_norm_gt_mp']:.1f}%")
    print(f"  mean gap_n (teacher - MP)     : {agg['mean_gap_hand_sep_norm_teacher_minus_mp']:.4f}")
    print(f"  mean gap_n (teacher - corr)   : {agg['mean_gap_hand_sep_norm_teacher_minus_corrector']:.4f}")
    print()
    print("-" * 72)
    print("PER CLIP (reach | hand_sep)")
    print("-" * 72)
    hdr = (
        f"{'clip':<44} {'n':>5} "
        f"{'rT':>5} {'rMP':>5} {'rC':>5} {'%r':>5} "
        f"{'sT':>5} {'sMP':>5} {'sC':>5} {'%s':>5}"
    )
    print(hdr)
    for c in result["per_clip"]:
        if c.get("skipped"):
            print(f"{c['clip_id']:<44} SKIP ({c.get('reason','')})")
            continue
        if c.get("n_extended", 0) == 0:
            print(f"{c['clip_id']:<44} {0:>5}")
            continue
        print(
            f"{c['clip_id']:<44} {c['n_extended']:>5} "
            f"{c['reach_teacher_mean']:>5.3f} {c['reach_mp_mean']:>5.3f} {c['reach_corrector_mean']:>5.3f} "
            f"{c['pct_corrector_reach_gt_mp']:>4.0f}% "
            f"{c['hand_sep_teacher_mean']:>5.3f} {c['hand_sep_mp_mean']:>5.3f} {c['hand_sep_corrector_mean']:>5.3f} "
            f"{c['pct_corrector_hand_sep_gt_mp']:>4.0f}%"
        )
    print("=" * 72)
    print(f"wrote {result['results_path']}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--split", default="test", choices=("train", "val", "test"))
    ap.add_argument("--manifest", type=Path, default=LAB_ROOT / "data" / "splits" / "manifest.json")
    ap.add_argument("--data-root", type=Path, default=LAB_ROOT / "data")
    ap.add_argument("--reach-thr", type=float, default=0.85)
    ap.add_argument("--elbow-thr-deg", type=float, default=160.0)
    ap.add_argument("--jab-margin", type=float, default=0.08,
                    help="Min (active-guard) teacher reach; 0 disables asymmetry filter")
    ap.add_argument("--out", type=Path, default=None,
                    help="JSON output path (default: data/evals/extension_<split>_<stamp>.json)")
    ap.add_argument(
        "--corrected-root",
        type=Path,
        default=None,
        help="Override data_root/corrected (e.g. runs/<id>/corrected_best)",
    )
    ap.add_argument(
        "--label",
        default="corrector",
        help="Label stored under compare[<label>] for multi-ckpt leaderboards",
    )
    args = ap.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    clip_ids: list[str] = list(manifest["splits"][args.split])

    per_clip: list[dict[str, Any]] = []
    n_used = 0
    n_skipped = 0
    total_frames = 0

    for clip_id in clip_ids:
        trio = load_trio(args.data_root, clip_id, corrected_root=args.corrected_root)
        if trio is None:
            per_clip.append({"clip_id": clip_id, "skipped": True, "reason": "missing_npy"})
            n_skipped += 1
            continue
        mp_j, corr_j, te_j = trio
        if mp_j.shape[1] < 14 or te_j.shape != mp_j.shape or corr_j.shape != mp_j.shape:
            # Allow truncate already done; shape joint mismatch → skip
            if te_j.shape[1:] != mp_j.shape[1:] or corr_j.shape[1:] != mp_j.shape[1:]:
                per_clip.append({"clip_id": clip_id, "skipped": True, "reason": "shape_mismatch"})
                n_skipped += 1
                continue

        te_m = arm_metrics(te_j)
        mp_m = arm_metrics(mp_j)
        co_m = arm_metrics(corr_j)
        extended, active = detect_extended(
            te_m, args.reach_thr, args.elbow_thr_deg, args.jab_margin
        )
        stats = clip_stats(te_m, mp_m, co_m, extended, active)
        stats.update({
            "clip_id": clip_id,
            "n_frames": int(mp_j.shape[0]),
            "skipped": False,
            "pct_frames_extended": float(100.0 * extended.mean()) if extended.size else 0.0,
        })
        per_clip.append(stats)
        n_used += 1
        total_frames += int(mp_j.shape[0])

    agg = aggregate_clips(per_clip)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_path = args.out or (LAB_ROOT / "data" / "evals" / f"extension_{args.split}_{stamp}.json")

    result: dict[str, Any] = {
        "created_unix": time.time(),
        "split": args.split,
        "timebase": "source_fps_viewer_exports",
        "data_root": str(args.data_root),
        "n_clips_listed": len(clip_ids),
        "n_clips_used": n_used,
        "n_clips_skipped": n_skipped,
        "n_frames_total": total_frames,
        "definition": {
            "reach": "||wrist-shoulder|| / (||shoulder-elbow|| + ||elbow-wrist||) per frame, same pose",
            "reach_thr": args.reach_thr,
            "elbow_thr_deg": args.elbow_thr_deg,
            "jab_margin": args.jab_margin,
            "active_side": "side with larger teacher reach",
            "extended_rule": (
                "teacher active reach > reach_thr OR teacher active elbow angle > elbow_thr_deg; "
                "AND (active_reach - guard_reach) >= jab_margin if jab_margin > 0"
            ),
            "guard_metrics": [
                "guard_span = ||wrist-shoulder|| on non-active side (meters, aligned space)",
                "guard_to_neck = ||wrist-neck|| on non-active side",
                "guard_reach = normalized reach on non-active side",
            ],
            "hand_separation": (
                "||wrist_active - wrist_guard|| = ||left_wrist - right_wrist|| on "
                "teacher-extended frames; also / shoulder_width (||L_sh - R_sh||)"
            ),
        },

        "aggregate": agg,
        "per_clip": per_clip,
        "results_path": str(out_path),
        "corrected_root": str(args.corrected_root) if args.corrected_root else str(args.data_root / "corrected"),
        "compare": {
            args.label: {
                "corrected_root": str(args.corrected_root)
                if args.corrected_root
                else str(args.data_root / "corrected"),
                "n_extended": agg.get("n_extended"),
                "reach_corrector_mean": agg.get("reach_corrector_mean"),
                "reach_mp_mean": agg.get("reach_mp_mean"),
                "reach_teacher_mean": agg.get("reach_teacher_mean"),
                "pct_corrector_reach_gt_mp": agg.get("pct_corrector_reach_gt_mp"),
                "mean_gap_teacher_minus_corrector": agg.get("mean_gap_teacher_minus_corrector"),
                "both": agg,
            }
        },
    }
    write_json(out_path, result)
    # Also emit compact JSON blob then human summary
    print(json.dumps({"aggregate": agg, "results_path": str(out_path), "definition": result["definition"]}, indent=2))
    print()
    print_summary(result)


if __name__ == "__main__":
    main()
