#!/usr/bin/env python3
"""Measure wrist-roll signal: NLF-S x55 finger knuckles vs the SMPL fit.

The live viewer draws the palm axes (cyan = palm fwd, magenta = across
index<->pinky, yellow = forearm) from the *non-parametric* x55 joints. This
probe answers: during a punch sequence, does that across vector actually rotate
around the forearm axis (roll/pronation), or is the signal flat?

For each boxing frame and each hand:
  - non-param x55 (what the viewer shows):
      across = pinky1 - index1 ; forearm = wrist - elbow
      roll_deg_t = signed angle of across projected on the plane perpendicular
                   to the forearm (per-frame local basis, consistent sign)
      swept_deg   = cumulative signed roll across the sequence (unwrap)
      span_mm     = |across| (knuckle credibility: tiny/erratic => noise)
  - parametric fit (SMPL24, the expensive rotations):
      wrist rotvec projected on the fitted forearm axis = pronation proxy
      |wrist rotvec| = total wrist rotation magnitude

The comparison tells us whether the fast path the game runs carries the roll
signal at all, and how much the full fit would add.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import torch

LAB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB_ROOT / "scripts"))

from nlf_fast_path import SMPLX55_JOINT_NAMES, estimate_joints24, get_joint_weights, load_nlf  # noqa: E402

DEFAULT_IMAGES = LAB_ROOT / "src" / "benchmark_images"
DEFAULT_MODEL = LAB_ROOT / "data" / "models" / "nlf" / "nlf_s_multi_0.2.2.torchscript"
DEFAULT_OUT = LAB_ROOT / "experiments" / "punch_roll" / "report.json"

SMPL24_NAMES = [
    "pelvis", "left_hip", "right_hip", "spine1", "left_knee", "right_knee",
    "spine2", "left_ankle", "right_ankle", "spine3", "left_foot", "right_foot",
    "neck", "left_collar", "right_collar", "head", "left_shoulder", "right_shoulder",
    "left_elbow", "right_elbow", "left_wrist", "right_wrist", "left_hand", "right_hand",
]
SIDES = ("left", "right")
HAND_JOINTS = {s: (f"{s}_wrist", f"{s}_elbow", f"{s}_index1", f"{s}_pinky1") for s in SIDES}
FIT_WRIST_BLOCK = {"left": 20, "right": 21}


def list_images(path: Path) -> list[Path]:
    return sorted(
        p for p in path.iterdir()
        if p.suffix.lower() in {".jpg", ".jpeg", ".png"} and p.is_file()
    )


def rotvec_angle(rotvec: np.ndarray) -> float:
    return float(np.degrees(np.linalg.norm(rotvec)))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    ap.add_argument("--images", type=Path, default=DEFAULT_IMAGES)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = ap.parse_args()

    images = list_images(args.images)
    if args.limit > 0:
        images = images[: args.limit]
    if not images:
        raise SystemExit(f"no images under {args.images}")
    if not args.model.is_file():
        raise SystemExit(f"missing model: {args.model}")

    model = load_nlf(args.model, args.device)
    weights55, _ = get_joint_weights(model, "smplx55")
    name_to_i = {n: i for i, n in enumerate(SMPLX55_JOINT_NAMES)}
    smpl24_to_i = {n: i for i, n in enumerate(SMPL24_NAMES)}

    frames: list[dict] = []
    per_side: dict[str, dict[str, list]] = {
        s: {"roll_deg": [], "swept_deg": 0.0, "span_mm": [], "fit_wrist_roll_deg": [], "fit_wrist_tot_deg": []}
        for s in SIDES
    }
    prev: dict[str, float | None] = {s: None for s in SIDES}
    prev_roll_deg: dict[str, float] = {s: 0.0 for s in SIDES}

    def basis_perp(f: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Consistent 2D basis (u, v) perpendicular to unit vector f."""
        z = np.array([0.0, 0.0, 1.0])
        c = np.cross(f, z)
        if np.linalg.norm(c) < 1e-3:
            c = np.cross(f, np.array([1.0, 0.0, 0.0]))
        u = c / np.linalg.norm(c)
        v = np.cross(f, u)
        return u, v

    for image_path in images:
        bgr = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if bgr is None:
            continue
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        img = (
            torch.from_numpy(np.ascontiguousarray(rgb))
            .permute(2, 0, 1)
            .to(args.device)
            .contiguous()
            .unsqueeze(0)
        )
        with torch.inference_mode():
            joints55 = estimate_joints24(model, rgb, weights55, device=args.device, num_aug=1)
            fit = model.detect_smpl_batched(img)
        if joints55 is None:
            continue
        pts = np.asarray(joints55, dtype=np.float64) / 1000.0
        pts = pts - pts[0:1]  # root-center, same as the live server

        fit_pose = None
        fit_joints = None
        if fit and fit.get("pose") and len(fit["pose"]) > 0:
            fit_pose = fit["pose"][0][0].detach().float().cpu().numpy()          # (72,)
            fit_joints = fit["joints3d"][0][0].detach().float().cpu().numpy()    # (24,3)

        frame: dict = {"image": image_path.name}
        for s in SIDES:
            wrist, elbow, index1, pinky1 = HAND_JOINTS[s]
            iw, ie, ii, ip = name_to_i[wrist], name_to_i[elbow], name_to_i[index1], name_to_i[pinky1]
            f = pts[iw] - pts[ie]
            fn = np.linalg.norm(f)
            d: dict = {}
            if fn < 1e-3:
                d = {"ok": False}
            else:
                fhat = f / fn
                across = pts[ip] - pts[ii]
                span_mm = float(np.linalg.norm(across) * 1000.0)
                perp = across - np.dot(across, fhat) * fhat
                pn = np.linalg.norm(perp)
                if pn < 1e-4:
                    d = {"ok": False, "span_mm": round(span_mm, 2)}
                else:
                    u, v = basis_perp(fhat)
                    perp_n = perp / pn
                    roll_deg = float(np.degrees(np.arctan2(np.dot(perp_n, v), np.dot(perp_n, u))))
                    swept = per_side[s]["swept_deg"]
                    if prev[s] is not None:
                        delta = roll_deg - prev[s]
                        delta = (delta + 180.0) % 360.0 - 180.0  # wrap to [-180,180]
                        swept += delta
                    prev[s] = roll_deg
                    per_side[s]["swept_deg"] = swept
                    per_side[s]["roll_deg"].append(round(roll_deg, 2))
                    per_side[s]["span_mm"].append(round(span_mm, 2))
                    d = {"ok": True, "roll_deg": round(roll_deg, 2), "span_mm": round(span_mm, 2)}

            fit_wrist_roll = None
            fit_wrist_tot = None
            if fit_pose is not None and fit_joints is not None:
                block = FIT_WRIST_BLOCK[s]
                rotvec = fit_pose[3 * block : 3 * block + 3]
                jw = fit_joints[smpl24_to_i[wrist]]
                je = fit_joints[smpl24_to_i[elbow]]
                ff = jw - je
                ffn = np.linalg.norm(ff)
                fit_wrist_tot = round(rotvec_angle(rotvec), 2)
                if ffn > 1e-3:
                    fit_wrist_roll = round(float(np.degrees(np.dot(rotvec, ff / ffn))), 2)
                per_side[s]["fit_wrist_tot_deg"].append(fit_wrist_tot)
                if fit_wrist_roll is not None:
                    per_side[s]["fit_wrist_roll_deg"].append(fit_wrist_roll)
                d["fit_wrist_tot_deg"] = fit_wrist_tot
                d["fit_wrist_roll_deg"] = fit_wrist_roll
            frame[s] = d
        frames.append(frame)

    def stats(a: list[float]) -> dict:
        arr = np.asarray(a, dtype=float)
        if arr.size == 0:
            return {"n": 0}
        return {
            "n": int(arr.size),
            "min": round(float(arr.min()), 2),
            "max": round(float(arr.max()), 2),
            "range": round(float(np.ptp(arr)), 2),
            "mean": round(float(arr.mean()), 2),
            "std": round(float(arr.std()), 2),
        }

    summary = {}
    for s in SIDES:
        ps = per_side[s]
        summary[s] = {
            "x55_roll_deg": stats(ps["roll_deg"]),
            "x55_swept_roll_deg": round(ps["swept_deg"], 2),
            "x55_across_span_mm": stats(ps["span_mm"]),
            "fit_wrist_tot_deg": stats(ps["fit_wrist_tot_deg"]),
            "fit_wrist_roll_deg": stats(ps["fit_wrist_roll_deg"]),
        }

    report = {
        "purpose": "wrist-roll signal: x55 knuckles (what the live viewer draws) vs SMPL fit",
        "device": args.device,
        "n_images": len(frames),
        "note": (
            "roll_deg is the signed angle of across(index<->pinky) around the current "
            "forearm axis; swept is its cumulative travel (unwrap). fit_wrist_roll is the "
            "fit's wrist rotvec projected on the fitted forearm axis. Angles in degrees."
        ),
        "summary": summary,
        "frames": frames,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
