#!/usr/bin/env python3
"""MediaPipe vs HybrIK (ResNet-34 SMPL) against Teacher — same residual panel.

Uses external/HybrIK + pretrained_models/hybrik_res34.pth (body SMPL, not HybrIK-X).

Usage:
  python scripts/compare_hybrik_vs_mp_teacher_metrics.py --clip-list short --device cuda

HD cleanup before next model test:
  data/hybrik/
  experiments/hybrik_vs_mp_teacher/
  external/HybrIK/pretrained_models/
  external/HybrIK/model_files/
  (optional) entire external/HybrIK/ if done with HybrIK
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import torch
from easydict import EasyDict as edict
from torchvision import transforms as T

LAB_ROOT = Path(__file__).resolve().parents[1]
HYB_ROOT = LAB_ROOT / "external" / "HybrIK"
sys.path.insert(0, str(LAB_ROOT / "src"))
sys.path.insert(0, str(LAB_ROOT / "scripts"))
sys.path.insert(0, str(HYB_ROOT))

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
    smpl24_to_lab,
)
from pose_lab.timebase import CANONICAL_FPS, resample_series  # noqa: E402

from bench_extended_shoulder_level_hands import teacher_arm_qualifies  # noqa: E402

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
    "flip_y": lambda x: x * np.array([1.0, -1.0, 1.0], dtype=np.float64),
    "flip_yz": lambda x: x * np.array([1.0, -1.0, -1.0], dtype=np.float64),
    "flip_z": lambda x: x * np.array([1.0, 1.0, -1.0], dtype=np.float64),
}


def _flip_mp_to_viewer(joints: np.ndarray) -> np.ndarray:
    out = joints.astype(np.float64, copy=True)
    out[..., 1] *= -1.0
    out[..., 2] *= -1.0
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


def load_hybrik(device: str):
    os.chdir(HYB_ROOT)
    from hybrik.models import builder
    from hybrik.utils.config import update_config
    from hybrik.utils.presets import SimpleTransform3DSMPLCam

    cfg_file = "configs/256x192_adam_lr1e-3-res34_smpl_3d_cam_2x_mix_w_pw3d.yaml"
    ckpt_path = HYB_ROOT / "pretrained_models" / "hybrik_res34.pth"
    cfg = update_config(cfg_file)
    bbox_3d_shape = [item * 1e-3 for item in getattr(cfg.MODEL, "BBOX_3D_SHAPE", (2000, 2000, 2000))]
    dummy = edict({
        "joint_pairs_17": None,
        "joint_pairs_24": None,
        "joint_pairs_29": None,
        "bbox_3d_shape": bbox_3d_shape,
    })
    transform = SimpleTransform3DSMPLCam(
        dummy,
        scale_factor=cfg.DATASET.SCALE_FACTOR,
        color_factor=cfg.DATASET.COLOR_FACTOR,
        occlusion=cfg.DATASET.OCCLUSION,
        input_size=cfg.MODEL.IMAGE_SIZE,
        output_size=cfg.MODEL.HEATMAP_SIZE,
        depth_dim=cfg.MODEL.EXTRA.DEPTH_DIM,
        bbox_3d_shape=bbox_3d_shape,
        rot=cfg.DATASET.ROT_FACTOR,
        sigma=cfg.MODEL.EXTRA.SIGMA,
        train=False,
        add_dpg=False,
        loss_type=cfg.LOSS["TYPE"],
    )
    model = builder.build_sppe(cfg.MODEL)
    save_dict = torch.load(str(ckpt_path), map_location="cpu", weights_only=False)
    sd = save_dict["model"] if isinstance(save_dict, dict) and "model" in save_dict else save_dict
    model.load_state_dict(sd, strict=False)
    model.to(device)
    model.eval()
    return model, transform


@torch.no_grad()
def infer_frame(model, transform, rgb: np.ndarray, device: str) -> np.ndarray:
    """Return lab joints (16,3) in camera metres (HybrIK convention)."""
    H, W = rgb.shape[:2]
    # person-centric clips → full-frame bbox
    m = 0.02
    bbox = [m * W, m * H, (1 - m) * W, (1 - m) * H]
    pose_input, bbox_out, img_center = transform.test_transform(rgb, bbox)
    pose_input = pose_input.to(device)[None]
    out = model(
        pose_input,
        flip_test=False,  # ResNet-34 ckpt mismatches flip path (512 vs 1024)
        bboxes=torch.tensor(np.asarray(bbox_out)[None], dtype=torch.float32, device=device),
        img_center=torch.tensor(np.asarray(img_center)[None], dtype=torch.float32, device=device),
    )
    xyz24 = out.pred_xyz_jts_24_struct.reshape(24, 3).cpu().numpy()
    transl = out.transl.detach().cpu().numpy().reshape(3)
    # camera-space absolute
    abs24 = xyz24 + transl[None, :]
    return smpl24_to_lab(abs24)


def export_clip(clip_id, mp_root, out_root, model, transform, device, stride, axis, skip_existing):
    out_dir = out_root / clip_id
    if skip_existing and (out_dir / "joints3d.npy").is_file():
        return {"clip_id": clip_id, "status": "skip"}
    mp_dir = mp_root / clip_id
    video = resolve_video(mp_dir)
    mp_j = np.load(mp_dir / "joints3d.npy")
    n_mp = int(mp_j.shape[0])
    mp_meta = json.loads((mp_dir / "meta.json").read_text(encoding="utf-8")) if (mp_dir / "meta.json").is_file() else {}
    cap = cv2.VideoCapture(str(video))
    fps = float(cap.get(cv2.CAP_PROP_FPS) or mp_meta.get("fps") or 30.0)
    axis_fn = AXIS_PRESETS[axis]
    joints = np.zeros((n_mp, len(LAB_JOINTS), 3), np.float32)
    confs = np.zeros((n_mp, len(LAB_JOINTS)), np.float32)
    det = 0
    last = None
    fi = 0
    t0 = time.time()
    while fi < n_mp:
        ok, frame = cap.read()
        if not ok:
            break
        if fi % stride == 0:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            try:
                lab = axis_fn(infer_frame(model, transform, rgb, device))
                last = lab
                joints[fi] = lab.astype(np.float32)
                confs[fi] = 1.0
                det += 1
            except Exception as e:
                print(f"  warn fi={fi}: {e}", flush=True)
        elif last is not None:
            joints[fi] = last.astype(np.float32)
            confs[fi] = 0.5
        fi += 1
    cap.release()
    last_i = None
    for t in range(n_mp):
        if confs[t].sum() > 0:
            last_i = t
        elif last_i is not None:
            joints[t] = joints[last_i]
            confs[t] = confs[last_i] * 0.5
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
        "backend": "HybrIK_ResNet34_SMPL",
        "axis_preset": axis,
        "stride": stride,
        "fps": fps,
        "n_frames": n_mp,
        "detect_frames": det,
        "elapsed_s": round(time.time() - t0, 2),
        "hd_cleanup": [
            "data/hybrik/",
            "experiments/hybrik_vs_mp_teacher/",
            "external/HybrIK/pretrained_models/",
            "external/HybrIK/model_files/",
        ],
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return {"clip_id": clip_id, "status": "ok", **meta}


def _residual_panel(student_v, te_v, conf, fps_src):
    st_30, _ = resample_series(student_v, fps_src, CANONICAL_FPS)
    te_30, _ = resample_series(te_v, fps_src, CANONICAL_FPS)
    T = int(min(st_30.shape[0], te_30.shape[0]))
    st_30, te_30 = st_30[:T], te_30[:T]
    conf_s = conf if conf.shape[0] == student_v.shape[0] else np.ones((student_v.shape[0], student_v.shape[1]))
    conf_30, _ = resample_series(conf_s.astype(np.float64), fps_src, CANONICAL_FPS)
    conf_30 = conf_30[:T]
    te_al = sequence_align_teacher_to_mp(te_30, st_30)
    residual = residual_sequence(st_30, te_al)
    hard = hard_mask(residual, conf_30[:, TARGET_IDX])
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
        "mpjpe_overall_mm": float(mean_j.mean() * 1000.0),
        "mpjpe_hard_mm": float(mean_j[hard].mean() * 1000.0) if hard.any() else float("nan"),
        "mpjpe_easy_mm": float(mean_j[easy].mean() * 1000.0) if easy.any() else float("nan"),
        "hard_frac": float(hard.mean()) if T else 0.0,
        "per_joint": per_joint,
    }


def _elbow_mae_deg(student, teacher, sel):
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


def _hand_prox_body(student, teacher, sel):
    if not sel.any():
        return float("nan")
    errs = []
    for t in np.flatnonzero(sel):
        R, scale, origin = body_frame_from_pose(teacher[t])
        tb = to_body_frame(teacher[t], R, scale, origin)
        sb = to_body_frame(student[t], R, scale, origin)
        errs.append(0.5 * (np.linalg.norm(sb[LW] - tb[LW]) + np.linalg.norm(sb[RW] - tb[RW])))
    return float(np.mean(errs))


def _lean_legs(poses):
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


def probe_axis(mp_root, te_root, model, transform, device, clip_id):
    mp = np.load(mp_root / clip_id / "joints3d.npy").astype(np.float64)
    te = np.load(te_root / clip_id / "joints3d.npy").astype(np.float64)
    video = resolve_video(mp_root / clip_id)
    cap = cv2.VideoCapture(str(video))
    raws = []
    for _ in range(10):
        ok, frame = cap.read()
        if not ok:
            break
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        raws.append(infer_frame(model, transform, rgb, device))
    cap.release()
    raw = np.stack(raws, 0)
    n = min(len(mp), len(te), 20)
    te_n, mp_n = te[:n], mp[:n]
    idx = np.linspace(0, len(raw) - 1, n).astype(int)
    raw_n = raw[idx]
    fps = float(json.loads((mp_root / clip_id / "meta.json").read_text(encoding="utf-8")).get("fps") or 30)
    best, best_s = "identity", 1e9
    for name, fn in AXIS_PRESETS.items():
        st = fn(raw_n)
        panel = _residual_panel(_flip_mp_to_viewer(st), _flip_mp_to_viewer(te_n), np.ones((n, 16)), fps)
        print(f"  [axis] {name}: {panel['mpjpe_overall_mm']:.1f}", flush=True)
        if panel["mpjpe_overall_mm"] < best_s:
            best, best_s = name, panel["mpjpe_overall_mm"]
    mp_p = _residual_panel(_flip_mp_to_viewer(mp_n), _flip_mp_to_viewer(te_n), np.ones((n, 16)), fps)
    print(f"  [axis] MP baseline={mp_p['mpjpe_overall_mm']:.1f} chosen={best}", flush=True)
    return best


def evaluate_clip(clip_id, mp_root, te_root, hy_root):
    mp = np.load(mp_root / clip_id / "joints3d.npy").astype(np.float64)
    te = np.load(te_root / clip_id / "joints3d.npy").astype(np.float64)
    hy = np.load(hy_root / clip_id / "joints3d.npy").astype(np.float64)
    mp_conf = np.load(mp_root / clip_id / "conf.npy").astype(np.float64) if (mp_root / clip_id / "conf.npy").is_file() else np.ones((mp.shape[0], mp.shape[1]))
    hy_conf = np.load(hy_root / clip_id / "conf.npy").astype(np.float64) if (hy_root / clip_id / "conf.npy").is_file() else np.ones((hy.shape[0], hy.shape[1]))
    mp_meta = json.loads((mp_root / clip_id / "meta.json").read_text(encoding="utf-8")) if (mp_root / clip_id / "meta.json").is_file() else {}
    fps = float(mp_meta.get("fps") or 0) or resolve_clip_fps(mp_root / clip_id, mp_meta, n_joints=int(mp.shape[0]))
    n = min(len(mp), len(te), len(hy))
    mp, te, hy = mp[:n], te[:n], hy[:n]
    mp_conf, hy_conf = mp_conf[:n], hy_conf[:n]
    mp_v, te_v, hy_v = _flip_mp_to_viewer(mp), _flip_mp_to_viewer(te), _flip_mp_to_viewer(hy)
    mp_panel = _residual_panel(mp_v, te_v, mp_conf, fps)
    hy_panel = _residual_panel(hy_v, te_v, hy_conf, fps)
    te_mp = sequence_align_teacher_to_mp(te_v, mp_v)
    te_hy = sequence_align_teacher_to_mp(te_v, hy_v)
    qL, qR = teacher_arm_qualifies(te_mp, reach_min=0.70, height_band=0.55, min_uy=-0.35, min_horiz=0.55)
    hand_sel = qL | qR
    reach_L = np.linalg.norm(te_mp[:, LW] - te_mp[:, LS], axis=-1) / np.maximum(
        np.linalg.norm(te_mp[:, LE] - te_mp[:, LS], axis=-1) + np.linalg.norm(te_mp[:, LW] - te_mp[:, LE], axis=-1), 1e-8)
    reach_R = np.linalg.norm(te_mp[:, RW] - te_mp[:, RS], axis=-1) / np.maximum(
        np.linalg.norm(te_mp[:, RE] - te_mp[:, RS], axis=-1) + np.linalg.norm(te_mp[:, RW] - te_mp[:, RE], axis=-1), 1e-8)
    ext_sel = (np.maximum(reach_L, reach_R) >= 0.70) | hand_sel
    out = {
        "clip_id": clip_id,
        "mp": {
            **{k: mp_panel[k] for k in ("mpjpe_overall_mm", "mpjpe_hard_mm", "mpjpe_easy_mm", "hard_frac", "per_joint")},
            "hand_prox_body": _hand_prox_body(mp_v, te_mp, hand_sel),
            "elbow_mae_deg": _elbow_mae_deg(mp_v, te_mp, ext_sel),
            "lean_legs_mean": float(_lean_legs(mp_v).mean()),
        },
        "hybrik": {
            **{k: hy_panel[k] for k in ("mpjpe_overall_mm", "mpjpe_hard_mm", "mpjpe_easy_mm", "hard_frac", "per_joint")},
            "hand_prox_body": _hand_prox_body(hy_v, te_hy, hand_sel),
            "elbow_mae_deg": _elbow_mae_deg(hy_v, te_hy, ext_sel),
            "lean_legs_mean": float(_lean_legs(hy_v).mean()),
        },
    }
    for key in ("mpjpe_overall_mm", "mpjpe_hard_mm", "mpjpe_easy_mm", "hand_prox_body", "elbow_mae_deg", "lean_legs_mean"):
        a, b = out["mp"][key], out["hybrik"][key]
        out.setdefault("hybrik_better_pct", {})[key] = (
            float(100.0 * (a - b) / max(a, 1e-8)) if np.isfinite(a) and np.isfinite(b) else float("nan")
        )
    return out


def aggregate(rows):
    keys = ("mpjpe_overall_mm", "mpjpe_hard_mm", "mpjpe_easy_mm", "hand_prox_body", "elbow_mae_deg", "lean_legs_mean")
    agg = {"n_clips": len(rows), "mp": {}, "hybrik": {}, "hybrik_better_pct": {}, "winner": {}}
    for k in keys:
        mp_v = np.array([r["mp"][k] for r in rows], float)
        hy_v = np.array([r["hybrik"][k] for r in rows], float)
        agg["mp"][k] = float(np.nanmean(mp_v))
        agg["hybrik"][k] = float(np.nanmean(hy_v))
        agg["hybrik_better_pct"][k] = float(100.0 * (agg["mp"][k] - agg["hybrik"][k]) / max(agg["mp"][k], 1e-8))
        agg["winner"][k] = "HybrIK" if agg["hybrik"][k] < agg["mp"][k] else "MediaPipe"
    pj = {}
    for j in TARGET_JOINTS:
        a = float(np.mean([r["mp"]["per_joint"][j]["mae_body_all"] for r in rows]))
        b = float(np.mean([r["hybrik"]["per_joint"][j]["mae_body_all"] for r in rows]))
        pj[j] = {
            "mp_mae_body": a,
            "hybrik_mae_body": b,
            "hybrik_better_pct": float(100.0 * (a - b) / max(a, 1e-8)),
            "winner": "HybrIK" if b < a else "MediaPipe",
        }
    agg["per_joint"] = pj
    return agg


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mediapipe", type=Path, default=LAB_ROOT / "data" / "mediapipe")
    ap.add_argument("--teacher", type=Path, default=LAB_ROOT / "data" / "teacher")
    ap.add_argument("--hybrik-out", type=Path, default=LAB_ROOT / "data" / "hybrik")
    ap.add_argument("--exp-out", type=Path, default=LAB_ROOT / "experiments" / "hybrik_vs_mp_teacher")
    ap.add_argument("--clip-list", choices=("", "short"), default="short")
    ap.add_argument("--stride", type=int, default=2)
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    ap.add_argument("--axis", default="auto", choices=["auto", *AXIS_PRESETS.keys()])
    ap.add_argument("--skip-existing", action="store_true")
    ap.add_argument("--metrics-only", action="store_true")
    args = ap.parse_args()

    clips = short_clip_ids(args.mediapipe, args.teacher, n=3)
    print(f"[hybrik] clips={clips} device={args.device}", flush=True)

    axis = args.axis
    if not args.metrics_only:
        print("[hybrik] loading model...", flush=True)
        model, transform = load_hybrik(args.device)
        if axis == "auto":
            axis = probe_axis(args.mediapipe, args.teacher, model, transform, args.device, clips[0])
        args.hybrik_out.mkdir(parents=True, exist_ok=True)
        for cid in clips:
            print(f"\n=== export {cid} axis={axis} ===", flush=True)
            info = export_clip(
                cid, args.mediapipe, args.hybrik_out, model, transform, args.device,
                args.stride, axis, args.skip_existing,
            )
            print(json.dumps({k: info[k] for k in info if k != "joint_names"}, indent=2), flush=True)

    rows = []
    for cid in clips:
        if not (args.hybrik_out / cid / "joints3d.npy").is_file():
            continue
        row = evaluate_clip(cid, args.mediapipe, args.teacher, args.hybrik_out)
        rows.append(row)
        print(json.dumps({
            "clip": cid,
            "mp_hard": row["mp"]["mpjpe_hard_mm"],
            "hy_hard": row["hybrik"]["mpjpe_hard_mm"],
            "mp_overall": row["mp"]["mpjpe_overall_mm"],
            "hy_overall": row["hybrik"]["mpjpe_overall_mm"],
            "hand_mp": row["mp"]["hand_prox_body"],
            "hand_hy": row["hybrik"]["hand_prox_body"],
            "elbow_mp": row["mp"]["elbow_mae_deg"],
            "elbow_hy": row["hybrik"]["elbow_mae_deg"],
            "lean_mp": row["mp"]["lean_legs_mean"],
            "lean_hy": row["hybrik"]["lean_legs_mean"],
        }, indent=2), flush=True)

    if not rows:
        raise SystemExit("No rows")
    agg = aggregate(rows)
    args.exp_out.mkdir(parents=True, exist_ok=True)
    payload = {
        "model": "HybrIK ResNet-34 SMPL",
        "axis": axis,
        "stride": args.stride,
        "device": args.device,
        "clips": [r["clip_id"] for r in rows],
        "aggregate": agg,
        "per_clip": rows,
        "hd_cleanup_before_next_test": [
            str(LAB_ROOT / "data" / "hybrik"),
            str(LAB_ROOT / "experiments" / "hybrik_vs_mp_teacher"),
            str(HYB_ROOT / "pretrained_models"),
            str(HYB_ROOT / "model_files"),
            str(HYB_ROOT) + " (optional full delete)",
        ],
        "vs_instanthmr_note": "InstantHMR was cleaned before this run; compare numbers to prior chat summary.",
    }
    (args.exp_out / "summary.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [
        "# HybrIK vs MediaPipe — Teacher residual panel",
        "",
        f"HybrIK ResNet-34 SMPL · axis=`{axis}` · stride={args.stride} · clips={len(rows)}",
        "",
        "| metric | MediaPipe | HybrIK | Hy better % | winner |",
        "|--------|----------:|-------:|------------:|:-------|",
    ]
    for k in ("mpjpe_overall_mm", "mpjpe_hard_mm", "mpjpe_easy_mm", "hand_prox_body", "elbow_mae_deg", "lean_legs_mean"):
        lines.append(
            f"| {k} | {agg['mp'][k]:.3f} | {agg['hybrik'][k]:.3f} | {agg['hybrik_better_pct'][k]:+.1f}% | {agg['winner'][k]} |"
        )
    lines += ["", "## Per-joint", "", "| joint | MP | HybrIK | better% | winner |", "|-------|---:|-------:|-------:|:-------|"]
    for j, d in agg["per_joint"].items():
        lines.append(
            f"| {j} | {d['mp_mae_body']:.4f} | {d['hybrik_mae_body']:.4f} | {d['hybrik_better_pct']:+.1f}% | {d['winner']} |"
        )
    lines += [
        "",
        "## CLEANUP (pouco HD) — apagar ANTES do proximo teste",
        "",
        "```",
        "data/hybrik/",
        "experiments/hybrik_vs_mp_teacher/",
        "external/HybrIK/pretrained_models/   # ~131MB",
        "external/HybrIK/model_files/         # ~80MB",
        "external/HybrIK/                    # opcional, repo inteiro",
        "```",
        "",
    ]
    (args.exp_out / "NOTES.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (args.exp_out / "CLEANUP.md").write_text(
        "# Apagar antes do proximo teste\n\n" + "\n".join(f"- `{p}`" for p in payload["hd_cleanup_before_next_test"]) + "\n",
        encoding="utf-8",
    )
    try:
        print("\n" + "\n".join(lines), flush=True)
    except UnicodeEncodeError:
        print(f"Wrote {args.exp_out / 'NOTES.md'}", flush=True)
    print("LEMBRETE HD: limpar HybrIK antes do proximo modelo.", flush=True)


if __name__ == "__main__":
    main()
