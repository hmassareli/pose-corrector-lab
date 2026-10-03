#!/usr/bin/env python3
"""Head-to-head MediaPipe vs InstantHMR against Teacher (same residual panel as RTM test).

Uses InstantHMR ONNX (momolesang/InstantHMR, ~81MB) — NOT the 461MB .pth.
Person bbox = full-frame (lab clips are already person crops).

Usage:
  python scripts/compare_instanthmr_vs_mp_teacher_metrics.py --clip-list short --device cpu
  python scripts/compare_instanthmr_vs_mp_teacher_metrics.py --metrics-only

HD cleanup after this experiment (do before next model test):
  data/instanthmr/  data/models/instanthmr/  experiments/instanthmr_vs_mp_teacher/
  and HF cache copies of InstantHMR if any.
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
import onnxruntime as ort

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

# MHR70 → lab (body subset; wrists are 62/41 not COCO 9/10)
MHR_TO_LAB = {
    0: "head",  # nose
    5: "left_shoulder",
    6: "right_shoulder",
    7: "left_elbow",
    8: "right_elbow",
    9: "left_hip",
    10: "right_hip",
    11: "left_knee",
    12: "right_knee",
    13: "left_ankle",
    14: "right_ankle",
    62: "left_wrist",
    41: "right_wrist",
    69: "neck",
}

IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

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
    "flip_y": lambda x: x * np.array([1.0, -1.0, 1.0], dtype=np.float64),  # Y-down → Y-up
    "flip_yz": lambda x: x * np.array([1.0, -1.0, -1.0], dtype=np.float64),
    "flip_z": lambda x: x * np.array([1.0, 1.0, -1.0], dtype=np.float64),
}


def _flip_mp_to_viewer(joints: np.ndarray) -> np.ndarray:
    out = joints.astype(np.float64, copy=True)
    out[..., 1] *= -1.0
    out[..., 2] *= -1.0
    return out


def mhr70_to_lab(xyz70: np.ndarray) -> np.ndarray:
    J = len(LAB_JOINTS)
    out = np.zeros((J, 3), dtype=np.float64)
    for mi, name in MHR_TO_LAB.items():
        out[JOINT_TO_IDX[name]] = xyz70[mi, :3]
    ls, rs = out[LS], out[RS]
    lh, rh = out[LH], out[RH]
    out[JOINT_TO_IDX["pelvis"]] = 0.5 * (lh + rh)
    if np.linalg.norm(out[JOINT_TO_IDX["neck"]]) < 1e-8:
        out[JOINT_TO_IDX["neck"]] = 0.5 * (ls + rs)
    out[JOINT_TO_IDX["spine"]] = 0.5 * (out[JOINT_TO_IDX["neck"]] + out[JOINT_TO_IDX["pelvis"]])
    return out


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


def preprocess_crop(rgb: np.ndarray, x1: float, y1: float, x2: float, y2: float):
    H, W = rgb.shape[:2]
    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    size = max(x2 - x1, y2 - y1) * 1.2
    sx1, sy1 = int(cx - size / 2), int(cy - size / 2)
    sx2, sy2 = int(cx + size / 2), int(cy + size / 2)
    pad = [max(0, -sy1), max(0, sy2 - H), max(0, -sx1), max(0, sx2 - W)]
    patch = rgb[max(0, sy1) : min(H, sy2), max(0, sx1) : min(W, sx2)]
    patch = cv2.copyMakeBorder(patch, *pad, cv2.BORDER_CONSTANT, value=0)
    crop = cv2.resize(patch, (224, 224), interpolation=cv2.INTER_LINEAR)
    img = (crop.astype(np.float32) / 255.0 - IMAGENET_MEAN) / IMAGENET_STD
    img = np.transpose(img, (2, 0, 1))[None].astype(np.float32)
    cliff = np.array(
        [2.0 * cx / W - 1.0, 2.0 * cy / H - 1.0, max(x2 - x1, y2 - y1) / max(W, H)],
        dtype=np.float32,
    )[None]
    return img, cliff


def load_session(onnx_path: Path, device: str) -> ort.InferenceSession:
    providers = ["CPUExecutionProvider"]
    if device == "cuda":
        providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
    return ort.InferenceSession(str(onnx_path), providers=providers)


def run_hmr(sess: ort.InferenceSession, rgb: np.ndarray) -> np.ndarray:
    """Return lab joints (16,3) in model camera space (metres, Y-down before axis)."""
    H, W = rgb.shape[:2]
    # Person-centric clips: full-frame bbox with small margin
    margin = 0.02
    x1, y1 = margin * W, margin * H
    x2, y2 = (1.0 - margin) * W, (1.0 - margin) * H
    img, cliff = preprocess_crop(rgb, x1, y1, x2, y2)
    outs = sess.run(None, {"image": img, "cliff_cond": cliff})
    # mhr, shape, cam_trans, joints_2d, joints_3d
    cam_trans = outs[2][0]  # (3,)
    joints_3d = outs[4][0]  # (70,3) body-centred
    abs3d = joints_3d + cam_trans[None, :]
    return mhr70_to_lab(abs3d)


def export_clip(
    clip_id: str,
    mp_root: Path,
    out_root: Path,
    sess: ort.InferenceSession,
    *,
    stride: int,
    axis: str,
    skip_existing: bool,
) -> dict[str, Any]:
    out_dir = out_root / clip_id
    if skip_existing and (out_dir / "joints3d.npy").is_file():
        j = np.load(out_dir / "joints3d.npy", mmap_mode="r")
        return {"clip_id": clip_id, "status": "skip", "n_frames": int(j.shape[0])}

    mp_dir = mp_root / clip_id
    video = resolve_video(mp_dir)
    if video is None:
        return {"clip_id": clip_id, "status": "error", "reason": "no_video"}
    mp_j = np.load(mp_dir / "joints3d.npy")
    n_mp = int(mp_j.shape[0])
    mp_meta = {}
    if (mp_dir / "meta.json").is_file():
        mp_meta = json.loads((mp_dir / "meta.json").read_text(encoding="utf-8"))

    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        return {"clip_id": clip_id, "status": "error", "reason": "open_fail"}
    fps = float(cap.get(cv2.CAP_PROP_FPS) or mp_meta.get("fps") or 30.0)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    axis_fn = AXIS_PRESETS[axis]

    joints = np.zeros((n_mp, len(LAB_JOINTS), 3), dtype=np.float32)
    confs = np.zeros((n_mp, len(LAB_JOINTS)), dtype=np.float32)
    det = 0
    fi = 0
    t0 = time.time()
    last_lab = None
    while fi < n_mp:
        ok, frame = cap.read()
        if not ok:
            break
        if fi % stride == 0:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            try:
                lab = axis_fn(run_hmr(sess, rgb))
                last_lab = lab
                joints[fi] = lab.astype(np.float32)
                confs[fi] = 1.0
                det += 1
            except Exception as e:
                print(f"  warn fi={fi}: {e}", flush=True)
        elif last_lab is not None:
            joints[fi] = last_lab.astype(np.float32)
            confs[fi] = 0.5
        fi += 1
    cap.release()

    # fill gaps
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
        "backend": "InstantHMR_ONNX_momolesang",
        "onnx": "data/models/instanthmr/instanthmr.onnx",
        "axis_preset": axis,
        "stride": stride,
        "bbox": "full_frame_person_crop",
        "fps": fps,
        "n_frames": n_mp,
        "width": w,
        "height": h,
        "detect_frames": det,
        "elapsed_s": round(time.time() - t0, 2),
        "joint_names": LAB_JOINTS,
        "note": "Disk axes after axis_preset. Metric path applies same YZ viewer flip as MediaPipe.",
        "hd_cleanup": [
            "data/instanthmr/",
            "data/models/instanthmr/",
            "experiments/instanthmr_vs_mp_teacher/",
            "~/.cache/huggingface/hub/*InstantHMR*",
        ],
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return {"clip_id": clip_id, "status": "ok", **{k: meta[k] for k in meta if k != "joint_names"}}


def _residual_panel(student_v, te_v, conf, fps_src) -> dict[str, Any]:
    st_30, _ = resample_series(student_v, fps_src, CANONICAL_FPS)
    te_30, _ = resample_series(te_v, fps_src, CANONICAL_FPS)
    T = int(min(st_30.shape[0], te_30.shape[0]))
    st_30, te_30 = st_30[:T], te_30[:T]
    conf_s = conf if conf.shape[0] == student_v.shape[0] else np.ones((student_v.shape[0], student_v.shape[1]))
    conf_30, _ = resample_series(conf_s.astype(np.float64), fps_src, CANONICAL_FPS)
    conf_30 = conf_30[:T]
    te_al = sequence_align_teacher_to_mp(te_30, st_30)
    residual = residual_sequence(st_30, te_al)
    conf_t = conf_30[:, TARGET_IDX]
    hard = hard_mask(residual, conf_t)
    easy = ~hard
    n = DELTA_DIM // 3
    norms = np.linalg.norm(residual.reshape(T, n, 3), axis=-1)
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
    }


def _elbow_mae_deg(student, teacher, sel) -> float:
    if not sel.any():
        return float("nan")
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
    return float(np.concatenate(errs).mean())


def _hand_prox_body(student, teacher, sel) -> float:
    if not sel.any():
        return float("nan")
    errs = []
    for t in np.flatnonzero(sel):
        R, scale, origin = body_frame_from_pose(teacher[t])
        tb = to_body_frame(teacher[t], R, scale, origin)
        sb = to_body_frame(student[t], R, scale, origin)
        errs.append(0.5 * (np.linalg.norm(sb[LW] - tb[LW]) + np.linalg.norm(sb[RW] - tb[RW])))
    return float(np.mean(errs))


def _lean_legs(poses) -> np.ndarray:
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


def probe_axis(mp_root, te_root, sess, clip_id: str) -> str:
    mp = np.load(mp_root / clip_id / "joints3d.npy").astype(np.float64)
    te = np.load(te_root / clip_id / "joints3d.npy").astype(np.float64)
    video = resolve_video(mp_root / clip_id)
    cap = cv2.VideoCapture(str(video))
    raws = []
    for _ in range(12):
        ok, frame = cap.read()
        if not ok:
            break
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        raws.append(run_hmr(sess, rgb))
    cap.release()
    if not raws:
        return "flip_y"
    raw = np.stack(raws, axis=0)
    # tile to ~mp length for crude score (first frames only)
    n = min(len(mp), len(te), 24)
    te_n, mp_n = te[:n], mp[:n]
    # repeat raw to n
    idx = np.linspace(0, len(raw) - 1, n).astype(int)
    raw_n = raw[idx]
    mp_meta = json.loads((mp_root / clip_id / "meta.json").read_text(encoding="utf-8"))
    fps = float(mp_meta.get("fps") or 30.0)
    best, best_s = "flip_y", 1e9
    for name, fn in AXIS_PRESETS.items():
        st = fn(raw_n)
        panel = _residual_panel(_flip_mp_to_viewer(st), _flip_mp_to_viewer(te_n), np.ones((n, 16)), fps)
        print(f"  [axis-probe] {name}: mpjpe_overall_mm={panel['mpjpe_overall_mm']:.1f}", flush=True)
        if panel["mpjpe_overall_mm"] < best_s:
            best, best_s = name, panel["mpjpe_overall_mm"]
    mp_panel = _residual_panel(_flip_mp_to_viewer(mp_n), _flip_mp_to_viewer(te_n), np.ones((n, 16)), fps)
    print(f"  [axis-probe] MediaPipe baseline={mp_panel['mpjpe_overall_mm']:.1f} chosen={best}", flush=True)
    return best


def evaluate_clip(clip_id, mp_root, te_root, hmr_root) -> dict[str, Any]:
    mp = np.load(mp_root / clip_id / "joints3d.npy").astype(np.float64)
    te = np.load(te_root / clip_id / "joints3d.npy").astype(np.float64)
    hmr = np.load(hmr_root / clip_id / "joints3d.npy").astype(np.float64)
    mp_conf = (
        np.load(mp_root / clip_id / "conf.npy").astype(np.float64)
        if (mp_root / clip_id / "conf.npy").is_file()
        else np.ones((mp.shape[0], mp.shape[1]))
    )
    hmr_conf = (
        np.load(hmr_root / clip_id / "conf.npy").astype(np.float64)
        if (hmr_root / clip_id / "conf.npy").is_file()
        else np.ones((hmr.shape[0], hmr.shape[1]))
    )
    mp_meta = json.loads((mp_root / clip_id / "meta.json").read_text(encoding="utf-8")) if (mp_root / clip_id / "meta.json").is_file() else {}
    fps = float(mp_meta.get("fps") or 0.0) or resolve_clip_fps(mp_root / clip_id, mp_meta, n_joints=int(mp.shape[0]))
    n = min(mp.shape[0], te.shape[0], hmr.shape[0])
    mp, te, hmr = mp[:n], te[:n], hmr[:n]
    mp_conf, hmr_conf = mp_conf[:n], hmr_conf[:n]
    mp_v, te_v, hmr_v = _flip_mp_to_viewer(mp), _flip_mp_to_viewer(te), _flip_mp_to_viewer(hmr)
    mp_panel = _residual_panel(mp_v, te_v, mp_conf, fps)
    hmr_panel = _residual_panel(hmr_v, te_v, hmr_conf, fps)
    te_mp = sequence_align_teacher_to_mp(te_v, mp_v)
    te_hm = sequence_align_teacher_to_mp(te_v, hmr_v)
    qL, qR = teacher_arm_qualifies(te_mp, reach_min=0.70, height_band=0.55, min_uy=-0.35, min_horiz=0.55)
    hand_sel = qL | qR
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
        "hmr": {
            "mpjpe_overall_mm": hmr_panel["mpjpe_overall_mm"],
            "mpjpe_hard_mm": hmr_panel["mpjpe_hard_mm"],
            "mpjpe_easy_mm": hmr_panel["mpjpe_easy_mm"],
            "hard_frac": hmr_panel["hard_frac"],
            "per_joint": hmr_panel["per_joint"],
            "hand_prox_body": _hand_prox_body(hmr_v, te_hm, hand_sel),
            "elbow_mae_deg": _elbow_mae_deg(hmr_v, te_hm, ext_sel),
            "lean_legs_mean": float(_lean_legs(hmr_v).mean()),
            "n_hand_sel": int(hand_sel.sum()),
            "n_ext_sel": int(ext_sel.sum()),
        },
    }
    for key in ("mpjpe_overall_mm", "mpjpe_hard_mm", "mpjpe_easy_mm", "hand_prox_body", "elbow_mae_deg", "lean_legs_mean"):
        a, b = out["mp"][key], out["hmr"][key]
        out.setdefault("hmr_better_pct", {})[key] = (
            float(100.0 * (a - b) / max(a, 1e-8)) if np.isfinite(a) and np.isfinite(b) else float("nan")
        )
    return out


def aggregate(rows: list[dict]) -> dict[str, Any]:
    keys = ("mpjpe_overall_mm", "mpjpe_hard_mm", "mpjpe_easy_mm", "hand_prox_body", "elbow_mae_deg", "lean_legs_mean")
    agg: dict[str, Any] = {"n_clips": len(rows), "mp": {}, "hmr": {}, "hmr_better_pct": {}, "winner": {}}
    for k in keys:
        mp_v = np.array([r["mp"][k] for r in rows], dtype=np.float64)
        hm_v = np.array([r["hmr"][k] for r in rows], dtype=np.float64)
        agg["mp"][k] = float(np.nanmean(mp_v))
        agg["hmr"][k] = float(np.nanmean(hm_v))
        agg["hmr_better_pct"][k] = float(100.0 * (agg["mp"][k] - agg["hmr"][k]) / max(agg["mp"][k], 1e-8))
        agg["winner"][k] = "InstantHMR" if agg["hmr"][k] < agg["mp"][k] else "MediaPipe"
    pj_mp = {j: [] for j in TARGET_JOINTS}
    pj_hm = {j: [] for j in TARGET_JOINTS}
    for r in rows:
        for j in TARGET_JOINTS:
            pj_mp[j].append(r["mp"]["per_joint"][j]["mae_body_all"])
            pj_hm[j].append(r["hmr"]["per_joint"][j]["mae_body_all"])
    agg["per_joint"] = {
        j: {
            "mp_mae_body": float(np.mean(pj_mp[j])),
            "hmr_mae_body": float(np.mean(pj_hm[j])),
            "hmr_better_pct": float(100.0 * (np.mean(pj_mp[j]) - np.mean(pj_hm[j])) / max(np.mean(pj_mp[j]), 1e-8)),
            "winner": "InstantHMR" if np.mean(pj_hm[j]) < np.mean(pj_mp[j]) else "MediaPipe",
        }
        for j in TARGET_JOINTS
    }
    return agg


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mediapipe", type=Path, default=LAB_ROOT / "data" / "mediapipe")
    ap.add_argument("--teacher", type=Path, default=LAB_ROOT / "data" / "teacher")
    ap.add_argument("--hmr-out", type=Path, default=LAB_ROOT / "data" / "instanthmr")
    ap.add_argument("--onnx", type=Path, default=LAB_ROOT / "data" / "models" / "instanthmr" / "instanthmr.onnx")
    ap.add_argument("--exp-out", type=Path, default=LAB_ROOT / "experiments" / "instanthmr_vs_mp_teacher")
    ap.add_argument("--clip", action="append", default=[])
    ap.add_argument("--clip-list", choices=("", "short"), default="")
    ap.add_argument("--stride", type=int, default=2)
    ap.add_argument("--device", default="cpu", choices=("cpu", "cuda"))
    ap.add_argument("--axis", default="auto", choices=["auto", *AXIS_PRESETS.keys()])
    ap.add_argument("--skip-existing", action="store_true")
    ap.add_argument("--metrics-only", action="store_true")
    args = ap.parse_args()

    clips = list(args.clip)
    if args.clip_list == "short" or not clips:
        clips = short_clip_ids(args.mediapipe, args.teacher, n=3)
    clips = [
        c
        for c in clips
        if (args.mediapipe / c / "joints3d.npy").is_file()
        and (args.teacher / c / "joints3d.npy").is_file()
        and resolve_video(args.mediapipe / c) is not None
    ]
    print(f"[ihm] clips={clips}", flush=True)

    axis = args.axis
    if not args.metrics_only:
        if not args.onnx.is_file():
            raise SystemExit(f"Missing ONNX: {args.onnx} (download momolesang/InstantHMR instanthmr.onnx only)")
        print(f"[ihm] loading {args.onnx} ({args.onnx.stat().st_size/1e6:.1f} MB)...", flush=True)
        sess = load_session(args.onnx, args.device)
        if axis == "auto":
            print("[ihm] probing axis...", flush=True)
            axis = probe_axis(args.mediapipe, args.teacher, sess, clips[0])
        args.hmr_out.mkdir(parents=True, exist_ok=True)
        for cid in clips:
            print(f"\n=== export {cid} axis={axis} ===", flush=True)
            info = export_clip(
                cid, args.mediapipe, args.hmr_out, sess,
                stride=args.stride, axis=axis, skip_existing=args.skip_existing,
            )
            print(json.dumps(info, indent=2), flush=True)

    rows = []
    for cid in clips:
        if not (args.hmr_out / cid / "joints3d.npy").is_file():
            print(f"[skip] no export {cid}", flush=True)
            continue
        row = evaluate_clip(cid, args.mediapipe, args.teacher, args.hmr_out)
        rows.append(row)
        print(json.dumps({
            "clip": cid,
            "mp_hard": row["mp"]["mpjpe_hard_mm"],
            "hmr_hard": row["hmr"]["mpjpe_hard_mm"],
            "mp_overall": row["mp"]["mpjpe_overall_mm"],
            "hmr_overall": row["hmr"]["mpjpe_overall_mm"],
            "hand_mp": row["mp"]["hand_prox_body"],
            "hand_hmr": row["hmr"]["hand_prox_body"],
            "elbow_mp": row["mp"]["elbow_mae_deg"],
            "elbow_hmr": row["hmr"]["elbow_mae_deg"],
            "lean_mp": row["mp"]["lean_legs_mean"],
            "lean_hmr": row["hmr"]["lean_legs_mean"],
        }, indent=2), flush=True)

    if not rows:
        raise SystemExit("No metric rows")

    agg = aggregate(rows)
    args.exp_out.mkdir(parents=True, exist_ok=True)
    payload = {
        "model": "InstantHMR ONNX",
        "axis": axis if not args.metrics_only else "from_export_meta",
        "stride": args.stride,
        "device": args.device,
        "clips": [r["clip_id"] for r in rows],
        "aggregate": agg,
        "per_clip": rows,
        "hd_cleanup_before_next_test": [
            str(LAB_ROOT / "data" / "instanthmr"),
            str(LAB_ROOT / "data" / "models" / "instanthmr"),
            str(LAB_ROOT / "experiments" / "instanthmr_vs_mp_teacher"),
            str(Path.home() / ".cache" / "huggingface" / "hub") + " (*InstantHMR*)",
        ],
    }
    (args.exp_out / "summary.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "# InstantHMR vs MediaPipe — Teacher residual panel",
        "",
        f"Axis: `{axis}` · stride={args.stride} · clips={len(rows)} · ONNX only (~81MB, no .pth)",
        "",
        "## Aggregate (clip-mean)",
        "",
        "| metric | MediaPipe | InstantHMR | HMR better % | winner |",
        "|--------|----------:|-----------:|-------------:|:-------|",
    ]
    for k in ("mpjpe_overall_mm", "mpjpe_hard_mm", "mpjpe_easy_mm", "hand_prox_body", "elbow_mae_deg", "lean_legs_mean"):
        lines.append(
            f"| {k} | {agg['mp'][k]:.3f} | {agg['hmr'][k]:.3f} | {agg['hmr_better_pct'][k]:+.1f}% | {agg['winner'][k]} |"
        )
    lines += [
        "",
        "## Per-joint residual MAE",
        "",
        "| joint | MP | InstantHMR | HMR better % | winner |",
        "|-------|---:|-----------:|-------------:|:-------|",
    ]
    for j, d in agg["per_joint"].items():
        lines.append(
            f"| {j} | {d['mp_mae_body']:.4f} | {d['hmr_mae_body']:.4f} | {d['hmr_better_pct']:+.1f}% | {d['winner']} |"
        )
    lines += [
        "",
        "## CLEANUP (pouco HD) — apagar ANTES do proximo teste de modelo",
        "",
        "```",
        "data/instanthmr/",
        "data/models/instanthmr/          # onnx ~81MB",
        "experiments/instanthmr_vs_mp_teacher/",
        "%USERPROFILE%\\.cache\\huggingface\\hub\\*InstantHMR*",
        "```",
        "",
        "Nao baixar instanthmr.pth (461MB) a menos que va treinar.",
        "",
    ]
    (args.exp_out / "NOTES.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (args.exp_out / "CLEANUP.md").write_text(
        "# Apagar antes do proximo teste\n\n"
        + "\n".join(f"- `{p}`" for p in payload["hd_cleanup_before_next_test"])
        + "\n\nNao baixar `instanthmr.pth` (461MB).\n",
        encoding="utf-8",
    )
    try:
        print("\n" + "\n".join(lines), flush=True)
    except UnicodeEncodeError:
        print(f"Wrote {args.exp_out / 'NOTES.md'}", flush=True)
    print(f"\nWrote {args.exp_out / 'summary.json'}", flush=True)
    print("LEMBRETE HD: apagar InstantHMR data/models/exps antes do proximo modelo.", flush=True)


if __name__ == "__main__":
    main()
