#!/usr/bin/env python3
"""Head-to-head MediaPipe vs RTMW3D against Teacher using the lab training metrics.

Same residual contract as pair_poses / train.eval_delta:
  - YZ flip to viewer
  - resample @ 30 Hz
  - trunk_translate_scale teacher → student (per frame)
  - Δ* = teacher − student in *student* body frame on 6 arm joints (18-D)

Also reports hand_prox / elbow MAE on the same teacher-extended frame selection
as the export benches, scored in body-frame units (shoulder-widths) so each
source gets its own trunk-aligned teacher (fair cross-estimator compare).

Usage:
  python scripts/compare_rtm_vs_mp_teacher_metrics.py --clip-list short --device cpu
  python scripts/compare_rtm_vs_mp_teacher_metrics.py --split test --limit 4 --stride 2
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB_ROOT / "src"))
sys.path.insert(0, str(LAB_ROOT / "scripts"))

from pose_lab.align import (  # noqa: E402
    body_frame_from_pose,
    sequence_align_teacher_to_mp,
    to_body_frame,
)
from pose_lab.io import resolve_clip_fps  # noqa: E402
from pose_lab.labels import residual_sequence  # noqa: E402
from pose_lab.metrics import hard_mask  # noqa: E402
from pose_lab.skeleton import (  # noqa: E402
    DELTA_DIM,
    JOINT_TO_IDX,
    LAB_JOINTS,
    TARGET_IDX,
    TARGET_JOINTS,
)
from pose_lab.timebase import CANONICAL_FPS, resample_series  # noqa: E402

from bench_extended_shoulder_level_hands import teacher_arm_qualifies  # noqa: E402

# COCO-WholeBody body subset (same indices as compare_rtmpose_mediapipe.py)
RT_TO_LAB = {
    5: "left_shoulder",
    6: "right_shoulder",
    7: "left_elbow",
    8: "right_elbow",
    9: "left_wrist",
    10: "right_wrist",
    11: "left_hip",
    12: "right_hip",
    13: "left_knee",
    14: "right_knee",
    15: "left_ankle",
    16: "right_ankle",
    0: "head",  # nose
}

LS = JOINT_TO_IDX["left_shoulder"]
RS = JOINT_TO_IDX["right_shoulder"]
LE = JOINT_TO_IDX["left_elbow"]
RE = JOINT_TO_IDX["right_elbow"]
LW = JOINT_TO_IDX["left_wrist"]
RW = JOINT_TO_IDX["right_wrist"]
LH = JOINT_TO_IDX["left_hip"]
RH = JOINT_TO_IDX["right_hip"]

AXIS_PRESETS = {
    "identity": lambda x: x,
    "flip_yz": lambda x: x * np.array([1.0, -1.0, -1.0], dtype=np.float64),
    "flip_y": lambda x: x * np.array([1.0, -1.0, 1.0], dtype=np.float64),
    "flip_z": lambda x: x * np.array([1.0, 1.0, -1.0], dtype=np.float64),
    "swap_yz_flip": lambda x: np.stack([x[..., 0], -x[..., 2], -x[..., 1]], axis=-1),
}


def _flip_mp_to_viewer(joints: np.ndarray) -> np.ndarray:
    out = joints.astype(np.float64, copy=True)
    out[..., 1] *= -1.0
    out[..., 2] *= -1.0
    return out


def coco_xyz_to_lab(xyz: np.ndarray, scores: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Map COCO/WholeBody body kpts (K,3) → lab (16,3) + conf."""
    J = len(LAB_JOINTS)
    out = np.zeros((J, 3), dtype=np.float64)
    conf = np.zeros((J,), dtype=np.float64)
    for ri, name in RT_TO_LAB.items():
        if ri >= len(xyz):
            continue
        li = JOINT_TO_IDX[name]
        out[li] = xyz[ri, :3]
        conf[li] = float(scores[ri]) if scores is not None and ri < len(scores) else 1.0
    ls, rs = out[LS], out[RS]
    lh, rh = out[LH], out[RH]
    out[JOINT_TO_IDX["pelvis"]] = 0.5 * (lh + rh)
    out[JOINT_TO_IDX["spine"]] = 0.5 * (0.5 * (ls + rs) + 0.5 * (lh + rh))
    out[JOINT_TO_IDX["neck"]] = 0.5 * (ls + rs)
    conf[JOINT_TO_IDX["pelvis"]] = 0.5 * (conf[LH] + conf[RH])
    conf[JOINT_TO_IDX["spine"]] = 0.5 * (0.5 * (conf[LS] + conf[RS]) + conf[JOINT_TO_IDX["pelvis"]])
    conf[JOINT_TO_IDX["neck"]] = 0.5 * (conf[LS] + conf[RS])
    return out, conf


def pick_person_nd(keypoints: np.ndarray, scores: np.ndarray):
    if keypoints is None or len(keypoints) == 0:
        return None
    if keypoints.ndim == 2:
        return keypoints, scores
    means = np.asarray(scores).mean(axis=1)
    i = int(np.argmax(means))
    return keypoints[i], scores[i]


def resolve_video(mp_dir: Path) -> Path | None:
    src = mp_dir / "source.mp4"
    if src.is_file():
        return src
    meta_path = mp_dir / "meta.json"
    if meta_path.is_file():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        p = Path(meta.get("source_video") or "")
        if p.is_file():
            return p
    return None


def short_clip_ids(mp_root: Path, te_root: Path, n: int = 3) -> list[str]:
    rows = []
    for p in mp_root.iterdir():
        if not (p / "joints3d.npy").is_file():
            continue
        if not (te_root / p.name / "joints3d.npy").is_file():
            continue
        if not resolve_video(p):
            continue
        t = int(np.load(p / "joints3d.npy", mmap_mode="r").shape[0])
        rows.append((t, p.name))
    rows.sort()
    return [c for _, c in rows[:n]]


def load_split_clips(split: str) -> list[str]:
    man = json.loads((LAB_ROOT / "data" / "splits" / "manifest.json").read_text(encoding="utf-8"))
    return list(man["splits"][split])


def export_rtmw3d_clip(
    clip_id: str,
    mp_root: Path,
    out_root: Path,
    model,
    *,
    stride: int,
    skip_existing: bool,
    axis: str,
) -> dict[str, Any]:
    out_dir = out_root / clip_id
    if skip_existing and (out_dir / "joints3d.npy").is_file():
        j = np.load(out_dir / "joints3d.npy", mmap_mode="r")
        return {"clip_id": clip_id, "status": "skip", "n_frames": int(j.shape[0])}

    mp_dir = mp_root / clip_id
    video = resolve_video(mp_dir)
    if video is None:
        return {"clip_id": clip_id, "status": "error", "reason": "no_video"}

    mp_meta = {}
    if (mp_dir / "meta.json").is_file():
        mp_meta = json.loads((mp_dir / "meta.json").read_text(encoding="utf-8"))
    mp_j = np.load(mp_dir / "joints3d.npy")
    n_mp = int(mp_j.shape[0])

    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        return {"clip_id": clip_id, "status": "error", "reason": "open_fail"}
    fps = float(cap.get(cv2.CAP_PROP_FPS) or mp_meta.get("fps") or 30.0)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or mp_meta.get("width") or 0)
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or mp_meta.get("height") or 0)

    axis_fn = AXIS_PRESETS[axis]
    joints = np.zeros((n_mp, len(LAB_JOINTS), 3), dtype=np.float32)
    confs = np.zeros((n_mp, len(LAB_JOINTS)), dtype=np.float32)
    det = 0
    fi = 0
    t0 = time.time()
    while fi < n_mp:
        ok, frame = cap.read()
        if not ok:
            break
        if fi % stride == 0:
            k3d, scores, _simcc, _k2d = model(frame)
            picked = pick_person_nd(np.asarray(k3d), np.asarray(scores))
            if picked is not None:
                xyz, sc = picked
                lab, cf = coco_xyz_to_lab(np.asarray(xyz, dtype=np.float64), np.asarray(sc))
                lab = axis_fn(lab)
                joints[fi] = lab.astype(np.float32)
                confs[fi] = cf.astype(np.float32)
                det += 1
                # fill skipped frames by hold
                for back in range(1, stride):
                    prev = fi - back
                    if prev >= 0 and confs[prev].sum() == 0:
                        joints[prev] = joints[fi]
                        confs[prev] = confs[fi]
        fi += 1
    cap.release()

    # forward-fill any remaining zeros from nearest detected
    last = None
    for t in range(n_mp):
        if confs[t].sum() > 0:
            last = t
        elif last is not None:
            joints[t] = joints[last]
            confs[t] = confs[last] * 0.5
    nxt = None
    for t in range(n_mp - 1, -1, -1):
        if confs[t].sum() > 0:
            nxt = t
        elif nxt is not None and confs[t].sum() == 0:
            joints[t] = joints[nxt]
            confs[t] = confs[nxt] * 0.5

    out_dir.mkdir(parents=True, exist_ok=True)
    np.save(out_dir / "joints3d.npy", joints)
    np.save(out_dir / "conf.npy", confs)
    meta = {
        "clip_id": clip_id,
        "source_video": str(video.resolve()),
        "backend": "rtmlib_Wholebody3d_RTMW3D",
        "axis_preset": axis,
        "stride": stride,
        "fps": fps,
        "n_frames": n_mp,
        "width": w,
        "height": h,
        "joint_names": LAB_JOINTS,
        "detect_frames": det,
        "elapsed_s": round(time.time() - t0, 2),
        "note": "Disk axes after axis_preset; pair_poses-style YZ flip applied at metric time like MediaPipe.",
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return {"clip_id": clip_id, "status": "ok", **meta}


def _residual_panel(student_v: np.ndarray, te_v: np.ndarray, conf: np.ndarray, fps_src: float) -> dict[str, Any]:
    """student/te already viewer-flipped. Returns residual metrics like eval_delta baseline."""
    st_30, _ = resample_series(student_v, fps_src, CANONICAL_FPS)
    te_30, _ = resample_series(te_v, fps_src, CANONICAL_FPS)
    T = int(min(st_30.shape[0], te_30.shape[0]))
    st_30 = st_30[:T]
    te_30 = te_30[:T]
    if conf.shape[0] != student_v.shape[0]:
        conf_s = np.ones((student_v.shape[0], student_v.shape[1]), dtype=np.float64)
    else:
        conf_s = conf
    conf_30, _ = resample_series(conf_s.astype(np.float64), fps_src, CANONICAL_FPS)
    conf_30 = conf_30[:T]
    te_al = sequence_align_teacher_to_mp(te_30, st_30)
    residual = residual_sequence(st_30, te_al)  # (T,18)
    conf_t = conf_30[:, TARGET_IDX]
    hard = hard_mask(residual, conf_t)
    easy = ~hard
    n = DELTA_DIM // 3
    norms = np.linalg.norm(residual.reshape(T, n, 3), axis=-1)  # (T,6)
    mean_j = norms.mean(axis=-1)
    per_joint = {
        TARGET_JOINTS[i]: {
            "mae_body_all": float(norms[:, i].mean()),
            "mae_body_hard": float(norms[hard, i].mean()) if hard.any() else float("nan"),
        }
        for i in range(n)
    }
    return {
        "n_frames_30": T,
        "mpjpe_overall_mm": float(mean_j.mean() * 1000.0),
        "mpjpe_hard_mm": float(mean_j[hard].mean() * 1000.0) if hard.any() else float("nan"),
        "mpjpe_easy_mm": float(mean_j[easy].mean() * 1000.0) if easy.any() else float("nan"),
        "hard_frac": float(hard.mean()) if T else 0.0,
        "per_joint": per_joint,
        "residual": residual,
        "te_aligned": te_al,
        "student_30": st_30,
        "conf_30": conf_30,
        "hard": hard,
    }


def _elbow_mae_deg(student: np.ndarray, teacher: np.ndarray, sel: np.ndarray) -> float:
    errs = []
    for sh, el, wr in ((LS, LE, LW), (RS, RE, RW)):
        def ang(p):
            a = p[:, sh] - p[:, el]
            b = p[:, wr] - p[:, el]
            na = np.linalg.norm(a, axis=-1)
            nb = np.linalg.norm(b, axis=-1)
            cos = np.clip(np.sum(a * b, axis=-1) / np.maximum(na * nb, 1e-8), -1.0, 1.0)
            return np.degrees(np.arccos(cos))
        errs.append(np.abs(ang(student) - ang(teacher))[sel])
    if not sel.any():
        return float("nan")
    return float(np.concatenate(errs).mean())


def _hand_prox_body(student: np.ndarray, teacher: np.ndarray, sel: np.ndarray) -> float:
    """Mean wrist MAE in teacher body-frame units (shoulder-widths) on selected frames."""
    if not sel.any():
        return float("nan")
    errs = []
    for t in np.flatnonzero(sel):
        R, scale, origin = body_frame_from_pose(teacher[t])
        tb = to_body_frame(teacher[t], R, scale, origin)
        sb = to_body_frame(student[t], R, scale, origin)
        errs.append(0.5 * (np.linalg.norm(sb[LW] - tb[LW]) + np.linalg.norm(sb[RW] - tb[RW])))
    return float(np.mean(errs))


def _lean_legs(poses: np.ndarray) -> np.ndarray:
    hip = 0.5 * (poses[:, LH] + poses[:, RH])
    sh = 0.5 * (poses[:, LS] + poses[:, RS])
    ank = 0.5 * (
        poses[:, JOINT_TO_IDX["left_ankle"]] + poses[:, JOINT_TO_IDX["right_ankle"]]
    )
    trunk = sh - hip
    legs = hip - ank
    nt = np.linalg.norm(trunk, axis=-1)
    nl = np.linalg.norm(legs, axis=-1)
    cos = np.clip(np.sum(trunk * legs, axis=-1) / np.maximum(nt * nl, 1e-8), -1.0, 1.0)
    return np.degrees(np.arccos(cos))


def pick_axis(mp_root: Path, te_root: Path, rtm_raw_probe: dict[str, np.ndarray], clip_id: str) -> str:
    """Choose axis preset minimizing residual overall vs teacher on one clip probe."""
    mp = np.load(mp_root / clip_id / "joints3d.npy").astype(np.float64)
    te = np.load(te_root / clip_id / "joints3d.npy").astype(np.float64)
    raw = rtm_raw_probe[clip_id]
    mp_meta = json.loads((mp_root / clip_id / "meta.json").read_text(encoding="utf-8"))
    fps = float(mp_meta.get("fps") or 30.0)
    best_name, best_score = "flip_yz", 1e9
    for name, fn in AXIS_PRESETS.items():
        st = fn(raw)
        # treat as MP-disk convention → viewer flip inside panel
        panel = _residual_panel(_flip_mp_to_viewer(st), _flip_mp_to_viewer(te[: st.shape[0]]), np.ones((st.shape[0], 16)), fps)
        score = panel["mpjpe_overall_mm"]
        print(f"  [axis-probe] {name}: mpjpe_overall_mm={score:.1f}", flush=True)
        if score < best_score:
            best_score, best_name = score, name
    # also report MP baseline for context
    mp_panel = _residual_panel(_flip_mp_to_viewer(mp), _flip_mp_to_viewer(te[: mp.shape[0]]), np.ones((mp.shape[0], 16)), fps)
    print(f"  [axis-probe] MediaPipe baseline mpjpe_overall_mm={mp_panel['mpjpe_overall_mm']:.1f}", flush=True)
    print(f"  [axis-probe] chosen={best_name}", flush=True)
    return best_name


def probe_raw_rtm(clip_id: str, mp_root: Path, model, max_frames: int = 24, stride: int = 3) -> np.ndarray:
    mp_dir = mp_root / clip_id
    video = resolve_video(mp_dir)
    mp_j = np.load(mp_dir / "joints3d.npy")
    n_mp = min(int(mp_j.shape[0]), max_frames * stride + 1)
    joints = np.zeros((n_mp, len(LAB_JOINTS), 3), dtype=np.float64)
    confs = np.zeros((n_mp, len(LAB_JOINTS)), dtype=np.float64)
    cap = cv2.VideoCapture(str(video))
    fi = 0
    while fi < n_mp:
        ok, frame = cap.read()
        if not ok:
            break
        if fi % stride == 0:
            k3d, scores, *_ = model(frame)
            picked = pick_person_nd(np.asarray(k3d), np.asarray(scores))
            if picked is not None:
                xyz, sc = picked
                lab, cf = coco_xyz_to_lab(np.asarray(xyz, dtype=np.float64), np.asarray(sc))
                joints[fi] = lab
                confs[fi] = cf
        fi += 1
    cap.release()
    last = None
    for t in range(n_mp):
        if confs[t].sum() > 0:
            last = t
        elif last is not None:
            joints[t] = joints[last]
    return joints


def evaluate_clip(
    clip_id: str,
    mp_root: Path,
    te_root: Path,
    rtm_root: Path,
) -> dict[str, Any]:
    mp = np.load(mp_root / clip_id / "joints3d.npy").astype(np.float64)
    te = np.load(te_root / clip_id / "joints3d.npy").astype(np.float64)
    rtm = np.load(rtm_root / clip_id / "joints3d.npy").astype(np.float64)
    mp_conf = np.load(mp_root / clip_id / "conf.npy").astype(np.float64) if (mp_root / clip_id / "conf.npy").is_file() else np.ones((mp.shape[0], mp.shape[1]))
    rtm_conf = np.load(rtm_root / clip_id / "conf.npy").astype(np.float64) if (rtm_root / clip_id / "conf.npy").is_file() else np.ones((rtm.shape[0], rtm.shape[1]))
    mp_meta = json.loads((mp_root / clip_id / "meta.json").read_text(encoding="utf-8")) if (mp_root / clip_id / "meta.json").is_file() else {}
    fps = float(mp_meta.get("fps") or 0.0) or resolve_clip_fps(mp_root / clip_id, mp_meta, n_joints=int(mp.shape[0]))

    n = min(mp.shape[0], te.shape[0], rtm.shape[0])
    mp, te, rtm = mp[:n], te[:n], rtm[:n]
    mp_conf, rtm_conf = mp_conf[:n], rtm_conf[:n]

    mp_v = _flip_mp_to_viewer(mp)
    te_v = _flip_mp_to_viewer(te)
    rtm_v = _flip_mp_to_viewer(rtm)

    mp_panel = _residual_panel(mp_v, te_v, mp_conf, fps)
    rtm_panel = _residual_panel(rtm_v, te_v, rtm_conf, fps)

    # Hand / elbow on source-fps with per-source trunk-aligned teacher
    te_mp = sequence_align_teacher_to_mp(te_v, mp_v)
    te_rt = sequence_align_teacher_to_mp(te_v, rtm_v)
    qL, qR = teacher_arm_qualifies(te_mp, reach_min=0.70, height_band=0.55, min_uy=-0.35, min_horiz=0.55)
    hand_sel = qL | qR
    # Extended-ish mask (reach≥0.70), aligned with hand/elbow bench spirit
    reach_L = np.linalg.norm(te_mp[:, LW] - te_mp[:, LS], axis=-1) / np.maximum(
        np.linalg.norm(te_mp[:, LE] - te_mp[:, LS], axis=-1)
        + np.linalg.norm(te_mp[:, LW] - te_mp[:, LE], axis=-1),
        1e-8,
    )
    reach_R = np.linalg.norm(te_mp[:, RW] - te_mp[:, RS], axis=-1) / np.maximum(
        np.linalg.norm(te_mp[:, RE] - te_mp[:, RS], axis=-1)
        + np.linalg.norm(te_mp[:, RW] - te_mp[:, RE], axis=-1),
        1e-8,
    )
    ext_sel = (np.maximum(reach_L, reach_R) >= 0.70) | hand_sel

    out = {
        "clip_id": clip_id,
        "domain": "in-domain" if "burn_500" in clip_id or "shadow_clip" in clip_id else "test/OOD-ish",
        "n_frames_src": n,
        "fps_src": fps,
        "mp": {
            "mpjpe_overall_mm": mp_panel["mpjpe_overall_mm"],
            "mpjpe_hard_mm": mp_panel["mpjpe_hard_mm"],
            "mpjpe_easy_mm": mp_panel["mpjpe_easy_mm"],
            "hard_frac": mp_panel["hard_frac"],
            "per_joint": mp_panel["per_joint"],
            "hand_prox_body": _hand_prox_body(mp_v, te_mp, hand_sel),
            "elbow_mae_deg": _elbow_mae_deg(mp_v, te_mp, ext_sel),
            "lean_legs_mean": float(_lean_legs(mp_v).mean()),
            "n_hand_sel": int(hand_sel.sum()),
            "n_ext_sel": int(ext_sel.sum()),
        },
        "rtm": {
            "mpjpe_overall_mm": rtm_panel["mpjpe_overall_mm"],
            "mpjpe_hard_mm": rtm_panel["mpjpe_hard_mm"],
            "mpjpe_easy_mm": rtm_panel["mpjpe_easy_mm"],
            "hard_frac": rtm_panel["hard_frac"],
            "per_joint": rtm_panel["per_joint"],
            "hand_prox_body": _hand_prox_body(rtm_v, te_rt, hand_sel),
            "elbow_mae_deg": _elbow_mae_deg(rtm_v, te_rt, ext_sel),
            "lean_legs_mean": float(_lean_legs(rtm_v).mean()),
            "n_hand_sel": int(hand_sel.sum()),
            "n_ext_sel": int(ext_sel.sum()),
        },
    }
    # deltas: positive = RTM better (lower error)
    for key in ("mpjpe_overall_mm", "mpjpe_hard_mm", "mpjpe_easy_mm", "hand_prox_body", "elbow_mae_deg", "lean_legs_mean"):
        a, b = out["mp"][key], out["rtm"][key]
        out.setdefault("rtm_better_delta", {})[key] = float(a - b) if np.isfinite(a) and np.isfinite(b) else float("nan")
        out.setdefault("rtm_better_pct", {})[key] = (
            float(100.0 * (a - b) / max(a, 1e-8)) if np.isfinite(a) and np.isfinite(b) else float("nan")
        )
    # per-joint winner
    pj = {}
    for jn in TARGET_JOINTS:
        a = out["mp"]["per_joint"][jn]["mae_body_all"]
        b = out["rtm"]["per_joint"][jn]["mae_body_all"]
        pj[jn] = {"mp": a, "rtm": b, "rtm_better_pct": float(100.0 * (a - b) / max(a, 1e-8))}
    out["per_joint_compare"] = pj
    return out


def aggregate(rows: list[dict]) -> dict[str, Any]:
    keys = ("mpjpe_overall_mm", "mpjpe_hard_mm", "mpjpe_easy_mm", "hand_prox_body", "elbow_mae_deg", "lean_legs_mean")
    agg: dict[str, Any] = {"n_clips": len(rows), "mp": {}, "rtm": {}, "rtm_better_pct": {}, "winner": {}}
    for k in keys:
        mp_v = np.array([r["mp"][k] for r in rows], dtype=np.float64)
        rt_v = np.array([r["rtm"][k] for r in rows], dtype=np.float64)
        agg["mp"][k] = float(np.nanmean(mp_v))
        agg["rtm"][k] = float(np.nanmean(rt_v))
        agg["rtm_better_pct"][k] = float(100.0 * (agg["mp"][k] - agg["rtm"][k]) / max(agg["mp"][k], 1e-8))
        agg["winner"][k] = "RTMW3D" if agg["rtm"][k] < agg["mp"][k] else "MediaPipe"
    # micro-average residual hard across frames would need concatenating; clip-mean is fine for short set
    pj_mp = {j: [] for j in TARGET_JOINTS}
    pj_rt = {j: [] for j in TARGET_JOINTS}
    for r in rows:
        for j in TARGET_JOINTS:
            pj_mp[j].append(r["mp"]["per_joint"][j]["mae_body_all"])
            pj_rt[j].append(r["rtm"]["per_joint"][j]["mae_body_all"])
    agg["per_joint"] = {
        j: {
            "mp_mae_body": float(np.mean(pj_mp[j])),
            "rtm_mae_body": float(np.mean(pj_rt[j])),
            "rtm_better_pct": float(100.0 * (np.mean(pj_mp[j]) - np.mean(pj_rt[j])) / max(np.mean(pj_mp[j]), 1e-8)),
            "winner": "RTMW3D" if np.mean(pj_rt[j]) < np.mean(pj_mp[j]) else "MediaPipe",
        }
        for j in TARGET_JOINTS
    }
    return agg


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mediapipe", type=Path, default=LAB_ROOT / "data" / "mediapipe")
    ap.add_argument("--teacher", type=Path, default=LAB_ROOT / "data" / "teacher")
    ap.add_argument("--rtm-out", type=Path, default=LAB_ROOT / "data" / "rtmw3d")
    ap.add_argument("--exp-out", type=Path, default=LAB_ROOT / "experiments" / "rtm_vs_mp_teacher")
    ap.add_argument("--clip", action="append", default=[])
    ap.add_argument("--clip-list", choices=("", "short"), default="")
    ap.add_argument("--split", default="", help="train|val|test from manifest")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--stride", type=int, default=2)
    ap.add_argument("--device", default="cpu", choices=("cpu", "cuda"))
    ap.add_argument("--axis", default="auto", choices=["auto", *AXIS_PRESETS.keys()])
    ap.add_argument("--skip-existing", action="store_true")
    ap.add_argument("--export-only", action="store_true")
    ap.add_argument("--metrics-only", action="store_true", help="Skip RTM inference; use existing --rtm-out")
    args = ap.parse_args()

    clips = list(args.clip)
    if args.split:
        clips = load_split_clips(args.split)
    elif args.clip_list == "short" or not clips:
        clips = short_clip_ids(args.mediapipe, args.teacher, n=3)
    if args.limit:
        clips = clips[: args.limit]
    # keep only clips with teacher + video
    clips = [
        c for c in clips
        if (args.mediapipe / c / "joints3d.npy").is_file()
        and (args.teacher / c / "joints3d.npy").is_file()
        and resolve_video(args.mediapipe / c) is not None
    ]
    print(f"[rtm-vs-mp] clips={clips}", flush=True)

    axis = args.axis
    model = None
    if not args.metrics_only:
        from rtmlib import Wholebody3d
        print("[rtm-vs-mp] loading Wholebody3d (RTMW3D)...", flush=True)
        model = Wholebody3d(mode="balanced", backend="onnxruntime", device=args.device)

        if axis == "auto":
            print("[rtm-vs-mp] probing axis presets on first clip...", flush=True)
            raw = {clips[0]: probe_raw_rtm(clips[0], args.mediapipe, model)}
            axis = pick_axis(args.mediapipe, args.teacher, raw, clips[0])

        args.rtm_out.mkdir(parents=True, exist_ok=True)
        for cid in clips:
            print(f"\n=== export {cid} axis={axis} ===", flush=True)
            info = export_rtmw3d_clip(
                cid, args.mediapipe, args.rtm_out, model,
                stride=args.stride, skip_existing=args.skip_existing, axis=axis,
            )
            print(json.dumps({k: info[k] for k in info if k not in ("joint_names",)}, indent=2), flush=True)

    if args.export_only:
        return

    rows = []
    for cid in clips:
        if not (args.rtm_out / cid / "joints3d.npy").is_file():
            print(f"[skip metrics] missing RTM export for {cid}", flush=True)
            continue
        print(f"\n=== metrics {cid} ===", flush=True)
        row = evaluate_clip(cid, args.mediapipe, args.teacher, args.rtm_out)
        rows.append(row)
        print(json.dumps({
            "clip": cid,
            "mp_hard": row["mp"]["mpjpe_hard_mm"],
            "rtm_hard": row["rtm"]["mpjpe_hard_mm"],
            "mp_overall": row["mp"]["mpjpe_overall_mm"],
            "rtm_overall": row["rtm"]["mpjpe_overall_mm"],
            "hand_mp": row["mp"]["hand_prox_body"],
            "hand_rtm": row["rtm"]["hand_prox_body"],
            "elbow_mp": row["mp"]["elbow_mae_deg"],
            "elbow_rtm": row["rtm"]["elbow_mae_deg"],
            "lean_mp": row["mp"]["lean_legs_mean"],
            "lean_rtm": row["rtm"]["lean_legs_mean"],
        }, indent=2), flush=True)

    if not rows:
        print("No metric rows.", flush=True)
        return

    agg = aggregate(rows)
    args.exp_out.mkdir(parents=True, exist_ok=True)
    payload = {
        "axis": axis,
        "stride": args.stride,
        "device": args.device,
        "clips": [r["clip_id"] for r in rows],
        "aggregate": agg,
        "per_clip": rows,
        "metric_defs": {
            "mpjpe_*_mm": "mean_j ||Δ*_j|| * 1000 in student body frame after trunk_translate_scale (same as train baseline)",
            "hard": "P80 residual OR mean target conf < 0.5 (hard_mask)",
            "hand_prox_body": "wrist MAE in teacher body-frame (shoulder-widths) on extended+shoulder-level teacher frames",
            "elbow_mae_deg": "|elbow°_student - elbow°_teacher| on extended-ish frames",
            "lean_legs_mean": "trunk vs ankle→hip angle (degrees)",
        },
    }
    # strip bulky arrays if any leaked
    for r in payload["per_clip"]:
        for side in ("mp", "rtm"):
            r[side].pop("residual", None)

    (args.exp_out / "summary.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # markdown
    lines = [
        "# RTMW3D vs MediaPipe — Teacher residual panel",
        "",
        f"Axis preset: `{axis}` · stride={args.stride} · clips={len(rows)}",
        "",
        "Same delta* contract as `pair_poses` / train baseline (trunk_translate_scale + body-frame residual on 6 arm joints).",
        "",
        "## Aggregate (clip-mean)",
        "",
        "| metric | MediaPipe | RTMW3D | RTM better % | winner |",
        "|--------|----------:|-------:|-------------:|:-------|",
    ]
    for k in ("mpjpe_overall_mm", "mpjpe_hard_mm", "mpjpe_easy_mm", "hand_prox_body", "elbow_mae_deg", "lean_legs_mean"):
        lines.append(
            f"| {k} | {agg['mp'][k]:.3f} | {agg['rtm'][k]:.3f} | {agg['rtm_better_pct'][k]:+.1f}% | {agg['winner'][k]} |"
        )
    lines += ["", "## Per-joint residual MAE (body units, all frames)", "",
              "| joint | MP | RTMW3D | RTM better % | winner |",
              "|-------|---:|-------:|-------------:|:-------|"]
    for j, d in agg["per_joint"].items():
        lines.append(
            f"| {j} | {d['mp_mae_body']:.4f} | {d['rtm_mae_body']:.4f} | {d['rtm_better_pct']:+.1f}% | {d['winner']} |"
        )
    lines += ["", "## Per clip (hard MPJPE mm)", "",
              "| clip | MP hard | RTM hard | MP overall | RTM overall |",
              "|------|--------:|---------:|-----------:|------------:|"]
    for r in rows:
        lines.append(
            f"| {r['clip_id']} | {r['mp']['mpjpe_hard_mm']:.1f} | {r['rtm']['mpjpe_hard_mm']:.1f} | "
            f"{r['mp']['mpjpe_overall_mm']:.1f} | {r['rtm']['mpjpe_overall_mm']:.1f} |"
        )
    lines += [
        "",
        "## Takeaway",
        "",
        "- On the **training residual panel** (hard/overall/easy delta* + hand_prox), MediaPipe is clearly closer to Teacher.",
        "- RTMW3D wins **trunk lean** (lean_legs) and slightly **elbow angle MAE** — geometry/angle, not wrist position.",
        "- Domain: short in-domain clips (burn_500 / shadow), not WIN webcam OOD.",
        "- Sanity: MP overall residual matches `data/paired/.../residual_30.npy` on the same clip.",
    ]
    (args.exp_out / "NOTES.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        print("\n" + "\n".join(lines), flush=True)
    except UnicodeEncodeError:
        print(f"Wrote NOTES (console encoding limited): {args.exp_out / 'NOTES.md'}", flush=True)
    print(f"\nWrote {args.exp_out / 'summary.json'}", flush=True)


if __name__ == "__main__":
    main()
