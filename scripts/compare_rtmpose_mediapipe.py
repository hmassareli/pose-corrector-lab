#!/usr/bin/env python3
"""Side-by-side MediaPipe Pose vs RTMPose / RTMW3D on lab clips.

Variants:
  --variant 2d   BodyWithFeet (Halpe26) — image lean only
  --variant 3d   Wholebody3d / RTMW3D-x — 2D overlay + 3D lean vs MP world

First run downloads ONNX (2d: ~140MB, 3d: YOLOX-m + large RTMW3D from HuggingFace).

Usage:
  python scripts/compare_rtmpose_mediapipe.py --variant 3d --clip-list short --max-frames 60 --stride 2
  python scripts/compare_rtmpose_mediapipe.py --variant 2d --clip burn_500_shots__shot_000__person_009
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]

# MediaPipe Pose-33
MP_LS, MP_RS, MP_LH, MP_RH = 11, 12, 23, 24
MP_LA, MP_RA = 27, 28
MP_BONES = [
    (11, 12), (11, 13), (13, 15), (12, 14), (14, 16),
    (11, 23), (12, 24), (23, 24), (23, 25), (25, 27), (24, 26), (26, 28),
    (27, 31), (28, 32), (0, 11), (0, 12),
]

# COCO / Halpe / WholeBody body subset
RT_LS, RT_RS, RT_LH, RT_RH = 5, 6, 11, 12
RT_LA, RT_RA = 15, 16
RT_BONES = [
    (5, 6), (5, 7), (7, 9), (6, 8), (8, 10),
    (5, 11), (6, 12), (11, 12), (11, 13), (13, 15), (12, 14), (14, 16),
    (0, 5), (0, 6),
]


def lean_deg_2d(hip_mid: np.ndarray, sh_mid: np.ndarray) -> float:
    trunk = sh_mid.astype(np.float64) - hip_mid.astype(np.float64)
    n = np.linalg.norm(trunk)
    if n < 1e-6:
        return float("nan")
    up = np.array([0.0, -1.0])  # image up (OpenCV y-down)
    c = float(np.clip(np.dot(trunk / n, up), -1.0, 1.0))
    return float(np.degrees(np.arccos(c)))


def lean_deg_axis(hip_mid: np.ndarray, sh_mid: np.ndarray, up: np.ndarray) -> float:
    trunk = sh_mid.astype(np.float64) - hip_mid.astype(np.float64)
    n = np.linalg.norm(trunk)
    un = np.linalg.norm(up)
    if n < 1e-6 or un < 1e-6:
        return float("nan")
    c = float(np.clip(np.dot(trunk / n, up / un), -1.0, 1.0))
    return float(np.degrees(np.arccos(c)))


def lean_vs_legs(ankle_mid: np.ndarray, hip_mid: np.ndarray, sh_mid: np.ndarray) -> float:
    """Trunk lean relative to leg axis (ankle→hip). Axis-convention agnostic."""
    return lean_deg_axis(hip_mid, sh_mid, hip_mid.astype(np.float64) - ankle_mid.astype(np.float64))


def draw_pose(img, kpts_xy, bones, color, thr=0.3, scores=None):
    for a, b in bones:
        if a >= len(kpts_xy) or b >= len(kpts_xy):
            continue
        if scores is not None and (scores[a] < thr or scores[b] < thr):
            continue
        pa, pb = kpts_xy[a], kpts_xy[b]
        if not np.all(np.isfinite(pa)) or not np.all(np.isfinite(pb)):
            continue
        cv2.line(img, (int(pa[0]), int(pa[1])), (int(pb[0]), int(pb[1])), color, 2, cv2.LINE_AA)
    for i, p in enumerate(kpts_xy):
        if scores is not None and i < len(scores) and scores[i] < thr:
            continue
        if not np.all(np.isfinite(p[:2])):
            continue
        cv2.circle(img, (int(p[0]), int(p[1])), 3, color, -1, cv2.LINE_AA)
    return img


def pick_person_nd(keypoints: np.ndarray, scores: np.ndarray):
    if keypoints is None or len(keypoints) == 0:
        return None
    if keypoints.ndim == 2:
        return keypoints, scores
    means = np.asarray(scores).mean(axis=1)
    i = int(np.argmax(means))
    return keypoints[i], scores[i]


def short_clip_ids(mp_root: Path, n: int = 3) -> list[str]:
    rows = []
    for p in mp_root.iterdir():
        if not (p / "source.mp4").is_file() or not (p / "landmarks33_image.npy").is_file():
            continue
        meta = {}
        if (p / "meta.json").is_file():
            meta = json.loads((p / "meta.json").read_text(encoding="utf-8"))
        T = int(meta.get("n_frames") or 0)
        if T <= 0:
            T = int(np.load(p / "landmarks33_image.npy", mmap_mode="r").shape[0])
        rows.append((T, p.name))
    rows.sort()
    return [name for _, name in rows[:n]]


def _stats(rows: list[dict], key: str) -> dict:
    vals = np.array([r[key] for r in rows], dtype=np.float64)
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        return {"n": 0}
    return {
        "n": int(vals.size),
        "mean": float(vals.mean()),
        "p50": float(np.median(vals)),
        "p95": float(np.percentile(vals, 95)),
        "max": float(vals.max()),
    }


def run_clip(
    clip_id: str,
    mp_root: Path,
    out_root: Path,
    model,
    *,
    variant: str,
    max_frames: int,
    stride: int,
    device: str,
) -> dict:
    clip_dir = mp_root / clip_id
    lm_img = np.load(clip_dir / "landmarks33_image.npy")
    lm_world = np.load(clip_dir / "landmarks33_world.npy")
    conf = (
        np.load(clip_dir / "landmarks33_conf.npy")
        if (clip_dir / "landmarks33_conf.npy").is_file()
        else None
    )

    cap = cv2.VideoCapture(str(clip_dir / "source.mp4"))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video for {clip_id}")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)

    out_dir = out_root / clip_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "compare.mp4"
    writer = cv2.VideoWriter(
        str(out_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        max(fps / max(stride, 1), 1.0),
        (w * 2, h),
    )

    rows: list[dict] = []
    fi = written = det_ok = 0
    t0 = time.time()
    label_rt = "RTMW3D" if variant == "3d" else "RTMPose2D"

    while True:
        ok, frame = cap.read()
        if not ok or fi >= lm_img.shape[0]:
            break
        if max_frames > 0 and written >= max_frames:
            break
        if fi % stride != 0:
            fi += 1
            continue

        # MediaPipe cached
        mp_norm = lm_img[fi]
        mp_xy = np.stack([mp_norm[:, 0] * w, mp_norm[:, 1] * h], axis=-1)
        mp_sc = conf[fi] if conf is not None else np.ones(33, np.float32)
        mp_hip = 0.5 * (mp_xy[MP_LH] + mp_xy[MP_RH])
        mp_sh = 0.5 * (mp_xy[MP_LS] + mp_xy[MP_RS])
        mp_lean2d = lean_deg_2d(mp_hip, mp_sh)

        world = lm_world[fi].astype(np.float64).copy()
        world[:, 1] *= -1.0
        world[:, 2] *= -1.0
        w_hip = 0.5 * (world[MP_LH] + world[MP_RH])
        w_sh = 0.5 * (world[MP_LS] + world[MP_RS])
        w_ank = 0.5 * (world[MP_LA] + world[MP_RA])
        mp_lean3d_y = lean_deg_axis(w_hip, w_sh, np.array([0.0, 1.0, 0.0]))
        mp_lean3d_legs = lean_vs_legs(w_ank, w_hip, w_sh)

        rt_lean2d = rt_lean3d_y = rt_lean3d_legs = float("nan")
        rt_xy = np.full((26, 2), np.nan)
        rt_sc = np.zeros(26)

        if variant == "3d":
            k3d, scores, _simcc, k2d = model(frame)
            picked3 = pick_person_nd(np.asarray(k3d), np.asarray(scores))
            picked2 = pick_person_nd(np.asarray(k2d), np.asarray(scores))
            if picked3 is not None and picked2 is not None:
                det_ok += 1
                xyz, rt_sc = picked3
                rt_xy, _ = picked2
                rt_hip = 0.5 * (xyz[RT_LH] + xyz[RT_RH])
                rt_sh = 0.5 * (xyz[RT_LS] + xyz[RT_RS])
                rt_ank = 0.5 * (xyz[RT_LA] + xyz[RT_RA])
                # RTMW3D often uses y-down-ish model space; report both, prefer legs-relative.
                rt_lean3d_y = min(
                    lean_deg_axis(rt_hip, rt_sh, np.array([0.0, 1.0, 0.0])),
                    lean_deg_axis(rt_hip, rt_sh, np.array([0.0, -1.0, 0.0])),
                )
                rt_lean3d_legs = lean_vs_legs(rt_ank, rt_hip, rt_sh)
                rt_lean2d = lean_deg_2d(
                    0.5 * (rt_xy[RT_LH] + rt_xy[RT_RH]),
                    0.5 * (rt_xy[RT_LS] + rt_xy[RT_RS]),
                )
        else:
            kpts, scores = model(frame)
            picked = pick_person_nd(np.asarray(kpts), np.asarray(scores))
            if picked is not None:
                det_ok += 1
                rt_xy, rt_sc = picked
                rt_lean2d = lean_deg_2d(
                    0.5 * (rt_xy[RT_LH] + rt_xy[RT_RH]),
                    0.5 * (rt_xy[RT_LS] + rt_xy[RT_RS]),
                )

        left = frame.copy()
        right = frame.copy()
        draw_pose(left, mp_xy, MP_BONES, (80, 220, 120), thr=0.35, scores=mp_sc)
        draw_pose(right, rt_xy, RT_BONES, (80, 180, 255), thr=0.35, scores=rt_sc)

        if variant == "3d":
            cv2.putText(
                left,
                f"MediaPipe  lean3d_legs={mp_lean3d_legs:.1f}  lean3d_Y={mp_lean3d_y:.1f}",
                (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (80, 220, 120), 2, cv2.LINE_AA,
            )
            cv2.putText(
                right,
                f"{label_rt}  lean3d_legs={rt_lean3d_legs:.1f}  lean3d_Y={rt_lean3d_y:.1f}",
                (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (80, 180, 255), 2, cv2.LINE_AA,
            )
        else:
            cv2.putText(
                left,
                f"MediaPipe  lean2d={mp_lean2d:.1f}  lean3d_Y={mp_lean3d_y:.1f}",
                (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (80, 220, 120), 2, cv2.LINE_AA,
            )
            cv2.putText(
                right,
                f"{label_rt}  lean2d={rt_lean2d:.1f}",
                (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (80, 180, 255), 2, cv2.LINE_AA,
            )
        cv2.putText(left, f"{clip_id}  f={fi}", (12, h - 16),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1, cv2.LINE_AA)

        writer.write(np.concatenate([left, right], axis=1))
        rows.append({
            "frame": fi,
            "mp_lean2d_deg": mp_lean2d,
            "mp_lean3d_y_deg": mp_lean3d_y,
            "mp_lean3d_legs_deg": mp_lean3d_legs,
            "rt_lean2d_deg": rt_lean2d,
            "rt_lean3d_y_deg": rt_lean3d_y,
            "rt_lean3d_legs_deg": rt_lean3d_legs,
            "rt_detected": int(np.isfinite(rt_lean2d) or np.isfinite(rt_lean3d_legs)),
        })
        written += 1
        fi += 1
        if written % 20 == 0:
            print(f"  [{clip_id}] wrote {written} (src fi={fi})", flush=True)

    cap.release()
    writer.release()

    model_name = (
        "Wholebody3d / RTMW3D-x (HuggingFace Soykaf)"
        if variant == "3d"
        else "BodyWithFeet balanced (YOLOX-m + RTMPose-m Halpe26)"
    )
    summary = {
        "clip_id": clip_id,
        "variant": variant,
        "device": device,
        "rtm_model": model_name,
        "n_frames_written": written,
        "stride": stride,
        "rt_detect_rate": float(det_ok / max(written, 1)),
        "elapsed_s": round(time.time() - t0, 2),
        "mp_lean2d": _stats(rows, "mp_lean2d_deg"),
        "mp_lean3d_y": _stats(rows, "mp_lean3d_y_deg"),
        "mp_lean3d_legs": _stats(rows, "mp_lean3d_legs_deg"),
        "rt_lean2d": _stats(rows, "rt_lean2d_deg"),
        "rt_lean3d_y": _stats(rows, "rt_lean3d_y_deg"),
        "rt_lean3d_legs": _stats(rows, "rt_lean3d_legs_deg"),
        "compare_mp4": str(out_path.relative_to(LAB_ROOT).as_posix()),
        "note": "lean3d_legs = trunk vs ankle→hip (best for cross-model 3D). lean3d_y = vs world +Y.",
    }
    with (out_dir / "lean.csv").open("w", newline="", encoding="utf-8") as f:
        wcsv = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["frame"])
        wcsv.writeheader()
        wcsv.writerows(rows)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mediapipe", type=Path, default=LAB_ROOT / "data" / "mediapipe")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--variant", choices=("2d", "3d"), default="2d")
    ap.add_argument("--clip", action="append", default=[])
    ap.add_argument("--clip-list", choices=("", "short"), default="")
    ap.add_argument("--max-frames", type=int, default=80)
    ap.add_argument("--stride", type=int, default=2)
    ap.add_argument("--mode", default="balanced", choices=("lightweight", "balanced", "performance"))
    ap.add_argument("--device", default="cpu", choices=("cpu", "cuda"))
    args = ap.parse_args()

    if args.out is None:
        args.out = LAB_ROOT / "experiments" / (
            "rtmpose3d_vs_mp" if args.variant == "3d" else "rtmpose_vs_mp"
        )

    clips = list(args.clip)
    if args.clip_list == "short" or not clips:
        clips = short_clip_ids(args.mediapipe, n=3)
        if args.clip:
            clips = args.clip

    print(f"[compare] variant={args.variant} clips={clips} device={args.device}", flush=True)
    print("[compare] loading model (downloads ONNX on first run)...", flush=True)

    if args.variant == "3d":
        from rtmlib import Wholebody3d
        model = Wholebody3d(mode="balanced", backend="onnxruntime", device=args.device)
    else:
        from rtmlib import BodyWithFeet
        model = BodyWithFeet(mode=args.mode, backend="onnxruntime", device=args.device)

    args.out.mkdir(parents=True, exist_ok=True)
    all_sum = []
    for cid in clips:
        print(f"\n=== {cid} ===", flush=True)
        all_sum.append(
            run_clip(
                cid, args.mediapipe, args.out, model,
                variant=args.variant,
                max_frames=args.max_frames,
                stride=args.stride,
                device=args.device,
            )
        )

    table = []
    for s in all_sum:
        table.append({
            "clip": s["clip_id"],
            "variant": s["variant"],
            "mp_lean3d_legs_mean": s["mp_lean3d_legs"].get("mean"),
            "rt_lean3d_legs_mean": s["rt_lean3d_legs"].get("mean"),
            "mp_lean3d_y_mean": s["mp_lean3d_y"].get("mean"),
            "rt_lean3d_y_mean": s["rt_lean3d_y"].get("mean"),
            "mp_lean2d_mean": s["mp_lean2d"].get("mean"),
            "rt_lean2d_mean": s["rt_lean2d"].get("mean"),
            "rt_detect_rate": s["rt_detect_rate"],
            "video": s["compare_mp4"],
        })
    (args.out / "compare_summary.json").write_text(json.dumps(table, indent=2), encoding="utf-8")
    print("\n[compare] done ->", args.out / "compare_summary.json", flush=True)


if __name__ == "__main__":
    main()
