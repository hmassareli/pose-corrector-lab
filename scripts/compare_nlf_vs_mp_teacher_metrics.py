#!/usr/bin/env python3
"""MediaPipe vs NLF-S (TorchScript multi) against Teacher — same residual panel.

Model: data/models/nlf/nlf_s_multi_0.2.2.torchscript (~298MB, not the 500MB L).

Usage:
  python scripts/compare_nlf_vs_mp_teacher_metrics.py --clip-list short --device cuda

HD cleanup before next test:
  data/nlf/  data/models/nlf/  experiments/nlf_vs_mp_teacher/
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
import torch

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
    SMPL24_AVATAR_AUX,
    TARGET_IDX,
    TARGET_JOINTS,
    smpl24_avatar_aux,
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


from nlf_fast_path import (  # noqa: E402
    estimate_joints24,
    get_joint_weights,
    load_nlf,
)


@torch.inference_mode()
def infer_frame_full(
    model, rgb: np.ndarray, device: str, joint_key: str
) -> tuple[np.ndarray, np.ndarray] | tuple[None, None]:
    """Full detect_smpl_batched → (lab 16×3, smpl24) in mm."""
    img = torch.from_numpy(rgb).permute(2, 0, 1).to(device)
    pred = model.detect_smpl_batched(img.unsqueeze(0))
    people = pred.get(joint_key) or pred.get("joints3d")
    if not people or len(people[0]) == 0:
        return None, None
    boxes = pred.get("boxes")
    idx = 0
    if boxes and len(boxes[0]) > 1:
        scores = boxes[0][:, -1]
        idx = int(torch.argmax(scores).item())
    j24 = people[0][idx].detach().cpu().numpy()
    if j24.ndim == 3:
        j24 = j24[0]
    return smpl24_to_lab(j24), np.asarray(j24, dtype=np.float64)


@torch.inference_mode()
def infer_frame_fast(
    model, rgb: np.ndarray, device: str, weights
) -> tuple[np.ndarray, np.ndarray] | tuple[None, None]:
    """Fast path: full-frame bbox + 24 joints → (lab 16×3, smpl24) in mm."""
    j24 = estimate_joints24(model, rgb, weights, device=device, num_aug=1)
    if j24 is None:
        return None, None
    j24 = np.asarray(j24, dtype=np.float64)
    return smpl24_to_lab(j24), j24


# Back-compat name used by probe_axis
def infer_frame(model, rgb, device, joint_key, *, mode="full", weights=None):
    if mode == "fast":
        lab, _ = infer_frame_fast(model, rgb, device, weights)
        return lab
    lab, _ = infer_frame_full(model, rgb, device, joint_key)
    return lab


def export_clip(
    clip_id,
    mp_root,
    out_root,
    model,
    device,
    stride,
    axis,
    joint_key,
    skip_existing,
    *,
    mode: str = "full",
    weights=None,
):
    out_dir = out_root / clip_id
    if skip_existing and (out_dir / "joints3d.npy").is_file():
        return {"clip_id": clip_id, "status": "skip"}
    mp_dir = mp_root / clip_id
    video = resolve_video(mp_dir)
    mp_j = np.load(mp_dir / "joints3d.npy")
    n_mp = int(mp_j.shape[0])
    mp_meta = {}
    if (mp_dir / "meta.json").is_file():
        mp_meta = json.loads((mp_dir / "meta.json").read_text(encoding="utf-8"))
    cap = cv2.VideoCapture(str(video))
    fps = float(cap.get(cv2.CAP_PROP_FPS) or mp_meta.get("fps") or 30.0)
    axis_fn = AXIS_PRESETS[axis]
    aux_names = list(SMPL24_AVATAR_AUX.keys())
    joints = np.zeros((n_mp, len(LAB_JOINTS), 3), np.float32)
    aux = np.zeros((n_mp, len(aux_names), 3), np.float32)
    confs = np.zeros((n_mp, len(LAB_JOINTS)), np.float32)
    det = 0
    last = None
    last_aux = None
    fi = 0
    t0 = time.time()
    frame_ms: list[float] = []
    while fi < n_mp:
        ok, frame = cap.read()
        if not ok:
            break
        if fi % stride == 0:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            try:
                if device.startswith("cuda") and torch.cuda.is_available():
                    torch.cuda.synchronize()
                    t_inf0 = time.perf_counter()
                else:
                    t_inf0 = time.perf_counter()
                if mode == "fast":
                    lab, j24 = infer_frame_fast(model, rgb, device, weights)
                else:
                    lab, j24 = infer_frame_full(model, rgb, device, joint_key)
                if device.startswith("cuda") and torch.cuda.is_available():
                    torch.cuda.synchronize()
                frame_ms.append((time.perf_counter() - t_inf0) * 1000.0)
                if lab is not None and j24 is not None:
                    lab = axis_fn(lab)
                    j24 = axis_fn(j24)
                    # Lab / viewer contract is metres; NLF TorchScript is mm.
                    lab = np.asarray(lab, dtype=np.float64) / 1000.0
                    j24_m = np.asarray(j24, dtype=np.float64) / 1000.0
                    j24_m = j24_m - j24_m[0:1]
                    aux_dict = smpl24_avatar_aux(j24_m)
                    aux_row = np.stack([aux_dict[n] for n in aux_names], axis=0)
                    last = lab
                    last_aux = aux_row
                    joints[fi] = lab.astype(np.float32)
                    aux[fi] = aux_row.astype(np.float32)
                    confs[fi] = 1.0
                    det += 1
            except Exception as e:
                print(f"  warn fi={fi}: {e}", flush=True)
        elif last is not None:
            joints[fi] = last.astype(np.float32)
            confs[fi] = 0.5
            if last_aux is not None:
                aux[fi] = last_aux.astype(np.float32)
        fi += 1
    cap.release()
    last_i = None
    for t in range(n_mp):
        if confs[t].sum() > 0:
            last_i = t
        elif last_i is not None:
            joints[t] = joints[last_i]
            confs[t] = confs[last_i] * 0.5
            aux[t] = aux[last_i]
    nxt = None
    for t in range(n_mp - 1, -1, -1):
        if confs[t].sum() > 0:
            nxt = t
        elif nxt is not None and confs[t].sum() == 0:
            joints[t] = joints[nxt]
            confs[t] = confs[nxt] * 0.5
            aux[t] = aux[nxt]

    out_dir.mkdir(parents=True, exist_ok=True)
    np.save(out_dir / "joints3d.npy", joints)
    np.save(out_dir / "conf.npy", confs)
    np.save(out_dir / "avatar_aux.npy", aux)
    (out_dir / "avatar_aux_names.json").write_text(
        json.dumps({"names": aux_names, "kind": "smpl"}, indent=2), encoding="utf-8"
    )
    ms = np.asarray(frame_ms, dtype=np.float64) if frame_ms else np.array([float("nan")])
    backend = "NLF_S_multi_0.2.2_fast_joints24" if mode == "fast" else "NLF_S_multi_0.2.2"
    meta = {
        "clip_id": clip_id,
        "backend": backend,
        "mode": mode,
        "joint_key": joint_key if mode == "full" else "poses3d_joints24",
        "axis_preset": axis,
        "stride": stride,
        "fps": fps,
        "n_frames": n_mp,
        "detect_frames": det,
        "elapsed_s": round(time.time() - t0, 2),
        "infer_ms_mean": float(np.nanmean(ms)),
        "infer_ms_p50": float(np.nanmedian(ms)),
        "infer_ms_p95": float(np.nanpercentile(ms, 95)),
        "hd_cleanup": (
            ["data/nlf_fast/", "data/models/nlf/", "experiments/nlf_speed/"]
            if mode == "fast"
            else ["data/nlf/", "data/models/nlf/", "experiments/nlf_vs_mp_teacher/"]
        ),
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


def probe_axis(mp_root, te_root, model, device, clip_id, joint_key, *, mode="full", weights=None):
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
        lab = infer_frame(model, rgb, device, joint_key, mode=mode, weights=weights)
        if lab is not None:
            raws.append(lab)
    cap.release()
    if not raws:
        return "identity"
    raw = np.stack(raws, 0)
    n = min(len(mp), len(te), 20)
    te_n = te[:n]
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
    mp_p = _residual_panel(_flip_mp_to_viewer(mp[:n]), _flip_mp_to_viewer(te_n), np.ones((n, 16)), fps)
    print(f"  [axis] MP baseline={mp_p['mpjpe_overall_mm']:.1f} chosen={best}", flush=True)
    return best


def evaluate_clip(clip_id, mp_root, te_root, nlf_root):
    mp = np.load(mp_root / clip_id / "joints3d.npy").astype(np.float64)
    te = np.load(te_root / clip_id / "joints3d.npy").astype(np.float64)
    nlf = np.load(nlf_root / clip_id / "joints3d.npy").astype(np.float64)
    mp_conf = np.load(mp_root / clip_id / "conf.npy").astype(np.float64) if (mp_root / clip_id / "conf.npy").is_file() else np.ones((mp.shape[0], mp.shape[1]))
    nlf_conf = np.load(nlf_root / clip_id / "conf.npy").astype(np.float64) if (nlf_root / clip_id / "conf.npy").is_file() else np.ones((nlf.shape[0], nlf.shape[1]))
    mp_meta = json.loads((mp_root / clip_id / "meta.json").read_text(encoding="utf-8")) if (mp_root / clip_id / "meta.json").is_file() else {}
    fps = float(mp_meta.get("fps") or 0) or resolve_clip_fps(mp_root / clip_id, mp_meta, n_joints=int(mp.shape[0]))
    n = min(len(mp), len(te), len(nlf))
    mp, te, nlf = mp[:n], te[:n], nlf[:n]
    mp_conf, nlf_conf = mp_conf[:n], nlf_conf[:n]
    mp_v, te_v, nlf_v = _flip_mp_to_viewer(mp), _flip_mp_to_viewer(te), _flip_mp_to_viewer(nlf)
    mp_panel = _residual_panel(mp_v, te_v, mp_conf, fps)
    nlf_panel = _residual_panel(nlf_v, te_v, nlf_conf, fps)
    te_mp = sequence_align_teacher_to_mp(te_v, mp_v)
    te_nl = sequence_align_teacher_to_mp(te_v, nlf_v)
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
        "nlf": {
            **{k: nlf_panel[k] for k in ("mpjpe_overall_mm", "mpjpe_hard_mm", "mpjpe_easy_mm", "hard_frac", "per_joint")},
            "hand_prox_body": _hand_prox_body(nlf_v, te_nl, hand_sel),
            "elbow_mae_deg": _elbow_mae_deg(nlf_v, te_nl, ext_sel),
            "lean_legs_mean": float(_lean_legs(nlf_v).mean()),
        },
    }
    for key in ("mpjpe_overall_mm", "mpjpe_hard_mm", "mpjpe_easy_mm", "hand_prox_body", "elbow_mae_deg", "lean_legs_mean"):
        a, b = out["mp"][key], out["nlf"][key]
        out.setdefault("nlf_better_pct", {})[key] = (
            float(100.0 * (a - b) / max(a, 1e-8)) if np.isfinite(a) and np.isfinite(b) else float("nan")
        )
    return out


def aggregate(rows):
    keys = ("mpjpe_overall_mm", "mpjpe_hard_mm", "mpjpe_easy_mm", "hand_prox_body", "elbow_mae_deg", "lean_legs_mean")
    agg = {"n_clips": len(rows), "mp": {}, "nlf": {}, "nlf_better_pct": {}, "winner": {}}
    for k in keys:
        mp_v = np.array([r["mp"][k] for r in rows], float)
        nl_v = np.array([r["nlf"][k] for r in rows], float)
        agg["mp"][k] = float(np.nanmean(mp_v))
        agg["nlf"][k] = float(np.nanmean(nl_v))
        agg["nlf_better_pct"][k] = float(100.0 * (agg["mp"][k] - agg["nlf"][k]) / max(agg["mp"][k], 1e-8))
        agg["winner"][k] = "NLF" if agg["nlf"][k] < agg["mp"][k] else "MediaPipe"
    pj = {}
    for j in TARGET_JOINTS:
        a = float(np.mean([r["mp"]["per_joint"][j]["mae_body_all"] for r in rows]))
        b = float(np.mean([r["nlf"]["per_joint"][j]["mae_body_all"] for r in rows]))
        pj[j] = {
            "mp_mae_body": a,
            "nlf_mae_body": b,
            "nlf_better_pct": float(100.0 * (a - b) / max(a, 1e-8)),
            "winner": "NLF" if b < a else "MediaPipe",
        }
    agg["per_joint"] = pj
    return agg


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mediapipe", type=Path, default=LAB_ROOT / "data" / "mediapipe")
    ap.add_argument("--teacher", type=Path, default=LAB_ROOT / "data" / "teacher")
    ap.add_argument("--nlf-out", type=Path, default=None)
    ap.add_argument(
        "--model",
        type=Path,
        default=LAB_ROOT / "data" / "models" / "nlf" / "nlf_s_multi_0.2.2.torchscript",
    )
    ap.add_argument("--exp-out", type=Path, default=None)
    ap.add_argument("--clip-list", choices=("", "short"), default="short")
    ap.add_argument("--stride", type=int, default=2)
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    ap.add_argument("--axis", default="auto", choices=["auto", *AXIS_PRESETS.keys()])
    ap.add_argument(
        "--joint-key",
        default="joints3d_nonparam",
        choices=("joints3d_nonparam", "joints3d"),
        help="nonparam = NLF field; joints3d = SMPL-fitted (full mode only)",
    )
    ap.add_argument(
        "--mode",
        choices=("full", "fast"),
        default="full",
        help="full=detect_smpl_batched; fast=estimate_poses joints24 full-frame no YOLO/fit",
    )
    ap.add_argument("--skip-existing", action="store_true")
    ap.add_argument("--metrics-only", action="store_true")
    args = ap.parse_args()

    if args.nlf_out is None:
        args.nlf_out = LAB_ROOT / "data" / ("nlf_fast" if args.mode == "fast" else "nlf")
    if args.exp_out is None:
        args.exp_out = LAB_ROOT / "experiments" / (
            "nlf_speed" if args.mode == "fast" else "nlf_vs_mp_teacher"
        )

    clips = short_clip_ids(args.mediapipe, args.teacher, n=3)
    print(
        f"[nlf] mode={args.mode} clips={clips} device={args.device} joint_key={args.joint_key}",
        flush=True,
    )

    axis = args.axis
    weights = None
    if not args.metrics_only:
        if not args.model.is_file():
            raise SystemExit(f"Missing model: {args.model}")
        print(f"[nlf] loading {args.model} ({args.model.stat().st_size/1e6:.1f} MB)...", flush=True)
        model = load_nlf(args.model, args.device)
        if args.mode == "fast":
            weights, _ = get_joint_weights(model, "joints24")
            print("[nlf] fast path: joints24 weights ready, num_aug=1, full-frame bbox", flush=True)
        if axis == "auto":
            axis = probe_axis(
                args.mediapipe,
                args.teacher,
                model,
                args.device,
                clips[0],
                args.joint_key,
                mode=args.mode,
                weights=weights,
            )
        args.nlf_out.mkdir(parents=True, exist_ok=True)
        for cid in clips:
            print(f"\n=== export {cid} mode={args.mode} axis={axis} ===", flush=True)
            info = export_clip(
                cid,
                args.mediapipe,
                args.nlf_out,
                model,
                args.device,
                args.stride,
                axis,
                args.joint_key,
                args.skip_existing,
                mode=args.mode,
                weights=weights,
            )
            print(json.dumps(info, indent=2), flush=True)

    rows = []
    for cid in clips:
        if not (args.nlf_out / cid / "joints3d.npy").is_file():
            continue
        row = evaluate_clip(cid, args.mediapipe, args.teacher, args.nlf_out)
        rows.append(row)
        print(json.dumps({
            "clip": cid,
            "mp_hard": row["mp"]["mpjpe_hard_mm"],
            "nlf_hard": row["nlf"]["mpjpe_hard_mm"],
            "mp_overall": row["mp"]["mpjpe_overall_mm"],
            "nlf_overall": row["nlf"]["mpjpe_overall_mm"],
            "hand_mp": row["mp"]["hand_prox_body"],
            "hand_nlf": row["nlf"]["hand_prox_body"],
            "elbow_mp": row["mp"]["elbow_mae_deg"],
            "elbow_nlf": row["nlf"]["elbow_mae_deg"],
            "lean_mp": row["mp"]["lean_legs_mean"],
            "lean_nlf": row["nlf"]["lean_legs_mean"],
        }, indent=2), flush=True)

    if not rows:
        raise SystemExit("No rows")
    agg = aggregate(rows)
    args.exp_out.mkdir(parents=True, exist_ok=True)
    lat_rows = []
    for cid in [r["clip_id"] for r in rows]:
        meta_p = args.nlf_out / cid / "meta.json"
        if meta_p.is_file():
            lat_rows.append(json.loads(meta_p.read_text(encoding="utf-8")))
    latency = {}
    if lat_rows:
        latency = {
            "infer_ms_mean": float(np.nanmean([m.get("infer_ms_mean", np.nan) for m in lat_rows])),
            "infer_ms_p50": float(np.nanmean([m.get("infer_ms_p50", np.nan) for m in lat_rows])),
            "infer_ms_p95": float(np.nanmean([m.get("infer_ms_p95", np.nan) for m in lat_rows])),
            "budget_30fps_ms": 33.333,
            "p95_under_budget": bool(
                np.nanmean([m.get("infer_ms_p95", np.nan) for m in lat_rows]) < 33.333
            ),
        }
    prior_full = LAB_ROOT / "experiments" / "nlf_vs_mp_teacher" / "summary.json"
    prior_nlf = None
    if prior_full.is_file() and args.mode == "fast":
        try:
            prior_nlf = json.loads(prior_full.read_text(encoding="utf-8"))["aggregate"]["nlf"]
        except Exception:
            prior_nlf = None
    cleanup = (
        [
            str(LAB_ROOT / "data" / "nlf_fast"),
            str(LAB_ROOT / "data" / "models" / "nlf"),
            str(LAB_ROOT / "experiments" / "nlf_speed"),
        ]
        if args.mode == "fast"
        else [
            str(LAB_ROOT / "data" / "nlf"),
            str(LAB_ROOT / "data" / "models" / "nlf"),
            str(LAB_ROOT / "experiments" / "nlf_vs_mp_teacher"),
        ]
    )
    payload = {
        "model": "NLF-S multi 0.2.2",
        "mode": args.mode,
        "joint_key": args.joint_key if args.mode == "full" else "poses3d_joints24",
        "axis": axis,
        "stride": args.stride,
        "device": args.device,
        "clips": [r["clip_id"] for r in rows],
        "aggregate": agg,
        "latency": latency,
        "per_clip": rows,
        "hd_cleanup_before_next_test": cleanup,
        "prior_shortlist_ref": {
            "InstantHMR_overall": 350.1,
            "InstantHMR_hard": 557.1,
            "HybrIK_overall": 387.2,
            "HybrIK_hard": 610.0,
            "MP_overall": 417.4,
            "MP_hard": 565.6,
            "NLF_full_overall": 260.7,
            "NLF_full_hard": 390.7,
        },
        "prior_nlf_full_aggregate": prior_nlf,
    }
    (args.exp_out / "summary.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    title = (
        "# NLF-S FAST path vs MediaPipe — Teacher residual panel"
        if args.mode == "fast"
        else "# NLF-S vs MediaPipe — Teacher residual panel"
    )
    mode_desc = (
        "fast · estimate_poses joints24 · full-frame bbox · num_aug=1 · no YOLO/fit"
        if args.mode == "fast"
        else f"`{args.joint_key}` · detect_smpl_batched"
    )
    lines = [
        title,
        "",
        f"NLF-S multi 0.2.2 · {mode_desc} · axis=`{axis}` · stride={args.stride} · clips={len(rows)}",
        "",
        "| metric | MediaPipe | NLF-S | NLF better % | winner |",
        "|--------|----------:|------:|-------------:|:-------|",
    ]
    for k in ("mpjpe_overall_mm", "mpjpe_hard_mm", "mpjpe_easy_mm", "hand_prox_body", "elbow_mae_deg", "lean_legs_mean"):
        lines.append(
            f"| {k} | {agg['mp'][k]:.3f} | {agg['nlf'][k]:.3f} | {agg['nlf_better_pct'][k]:+.1f}% | {agg['winner'][k]} |"
        )
    if latency:
        lines += [
            "",
            "## Latency (export infer, ms)",
            "",
            f"| mean | p50 | p95 | p95 < 33.3ms |",
            f"|-----:|----:|----:|:-------------|",
            f"| {latency['infer_ms_mean']:.1f} | {latency['infer_ms_p50']:.1f} | "
            f"{latency['infer_ms_p95']:.1f} | {latency['p95_under_budget']} |",
        ]
    lines += [
        "",
        "## vs prior shortlist (same clips, from earlier runs)",
        "",
        "| model | overall | hard |",
        "|-------|--------:|-----:|",
        f"| MediaPipe | {agg['mp']['mpjpe_overall_mm']:.1f} | {agg['mp']['mpjpe_hard_mm']:.1f} |",
        f"| NLF-S ({args.mode}) | {agg['nlf']['mpjpe_overall_mm']:.1f} | {agg['nlf']['mpjpe_hard_mm']:.1f} |",
        "| NLF-S full (prior) | 260.7 | 390.7 |",
        "| InstantHMR (prior) | 350.1 | 557.1 |",
        "| HybrIK (prior) | 387.2 | 610.0 |",
        "",
        "## Per-joint",
        "",
        "| joint | MP | NLF | better% | winner |",
        "|-------|---:|----:|-------:|:-------|",
    ]
    for j, d in agg["per_joint"].items():
        lines.append(
            f"| {j} | {d['mp_mae_body']:.4f} | {d['nlf_mae_body']:.4f} | {d['nlf_better_pct']:+.1f}% | {d['winner']} |"
        )
    if args.mode == "fast":
        lines += [
            "",
            "## CLEANUP (pouco HD) — apagar ANTES do proximo teste",
            "",
            "```",
            "data/nlf_fast/",
            "data/nlf/",
            "data/models/nlf/                 # ~298MB torchscript",
            "experiments/nlf_speed/",
            "experiments/nlf_vs_mp_teacher/",
            "```",
            "",
        ]
    else:
        lines += [
            "",
            "## CLEANUP (pouco HD) — apagar ANTES do proximo teste",
            "",
            "```",
            "data/nlf/",
            "data/models/nlf/                 # ~298MB torchscript",
            "experiments/nlf_vs_mp_teacher/",
            "```",
            "",
        ]
    (args.exp_out / "NOTES.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (args.exp_out / "CLEANUP.md").write_text(
        "# Apagar antes do proximo teste\n\n"
        + "\n".join(f"- `{p}`" for p in payload["hd_cleanup_before_next_test"])
        + "\n",
        encoding="utf-8",
    )
    try:
        print("\n" + "\n".join(lines), flush=True)
    except UnicodeEncodeError:
        print(f"Wrote {args.exp_out / 'NOTES.md'}", flush=True)
    print("LEMBRETE HD: limpar NLF antes do proximo modelo.", flush=True)


if __name__ == "__main__":
    main()
