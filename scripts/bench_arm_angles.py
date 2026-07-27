#!/usr/bin/env python3
"""Benchmark arm ANGLE fidelity to the teacher (NOT reach / hand-separation).

On the same teacher-extended frames as bench_extension.py (default thresholds
yield ~4041 test frames), measure how close MediaPipe and each corrector are
to the teacher's elbow (and optional shoulder) angles — for BOTH arms.

Angles
------
  Elbow flexion/extension (required):
    Interior angle at the elbow, angle(shoulder-elbow-wrist), in degrees.
    180 deg ≈ fully straight arm; smaller ≈ more flexed.
    Interior arccos angle (same definition as losses._elbow_angle_deg /
    bench_extension._elbow_angles_deg) — NOT a reach/magnitude metric.

  Upper-arm elevation (optional, reported):
    Angle between upper-arm vector (shoulder→elbow) and trunk up-axis
    (mid-hip → mid-shoulder). 0° ≈ arm along trunk; 90° ≈ arm out to side
    (horizontal relative to trunk). Scale-free / rotation-aware within
    the pose's own body axes.

Frame selection (identical to bench_extension.py)
-------------------------------------------------
  Teacher-extended if, on the active side (larger teacher reach):
    reach > --reach-thr  OR  elbow angle > --elbow-thr-deg
  and (active_reach - guard_reach) >= --jab-margin when jab_margin > 0.

Metrics (per arm L/R and pooled both-arms), on those frames only:
  - mean |angle_C - angle_T|  vs  mean |angle_MP - angle_T|   (degrees)
  - % frames where |C-T| < |MP-T|
  - mean signed error (C-T) and (MP-T)
  - mean teacher / MP / corrector angles for context

NOT measured here: reach magnitude, hand separation, max-reach style scores.
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

from pose_lab.logging_utils import write_json  # noqa: E402
from pose_lab.skeleton import JOINT_TO_IDX  # noqa: E402

# Reuse frame selection + reach helpers from the reach bench (same 4041-frame set).
from bench_extension import arm_metrics, detect_extended  # noqa: E402

LS = JOINT_TO_IDX["left_shoulder"]
RS = JOINT_TO_IDX["right_shoulder"]
LE = JOINT_TO_IDX["left_elbow"]
RE = JOINT_TO_IDX["right_elbow"]
LH = JOINT_TO_IDX["left_hip"]
RH = JOINT_TO_IDX["right_hip"]


def _elbow_angles_deg(poses: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Interior elbow angle in degrees (180° ≈ straight). poses (T,J,3)."""
    out = []
    for sh, el, wr in (
        (LS, LE, JOINT_TO_IDX["left_wrist"]),
        (RS, RE, JOINT_TO_IDX["right_wrist"]),
    ):
        a = poses[:, sh] - poses[:, el]
        b = poses[:, wr] - poses[:, el]
        na = np.linalg.norm(a, axis=-1)
        nb = np.linalg.norm(b, axis=-1)
        denom = np.maximum(na * nb, 1e-8)
        cos = np.clip(np.sum(a * b, axis=-1) / denom, -1.0, 1.0)
        out.append(np.degrees(np.arccos(cos)))
    return out[0], out[1]


def _upper_arm_elevation_deg(poses: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Angle between shoulder→elbow and trunk up (mid-hip→mid-shoulder), degrees."""
    mid_hip = 0.5 * (poses[:, LH] + poses[:, RH])
    mid_sh = 0.5 * (poses[:, LS] + poses[:, RS])
    trunk = mid_sh - mid_hip
    nt = np.linalg.norm(trunk, axis=-1)
    trunk_u = trunk / np.maximum(nt, 1e-8)[:, None]
    out = []
    for sh, el in ((LS, LE), (RS, RE)):
        ua = poses[:, el] - poses[:, sh]
        nu = np.linalg.norm(ua, axis=-1)
        ua_u = ua / np.maximum(nu, 1e-8)[:, None]
        cos = np.clip(np.sum(ua_u * trunk_u, axis=-1), -1.0, 1.0)
        out.append(np.degrees(np.arccos(cos)))
    return out[0], out[1]


def load_poses(root: Path, clip_id: str) -> np.ndarray | None:
    p = root / clip_id / "joints3d.npy"
    if not p.is_file():
        return None
    arr = np.load(p).astype(np.float64)
    if arr.ndim != 3 or arr.shape[0] < 1:
        return None
    return arr


def _angle_stats(
    te: np.ndarray,
    mp: np.ndarray,
    co: np.ndarray,
) -> dict[str, float]:
    """te/mp/co: 1D arrays of angles (degrees) on the same frames."""
    if te.size == 0:
        return {
            "n": 0,
            "mean_abs_err_corrector": float("nan"),
            "mean_abs_err_mp": float("nan"),
            "pct_corrector_closer_than_mp": float("nan"),
            "mean_signed_err_corrector": float("nan"),
            "mean_signed_err_mp": float("nan"),
            "mean_angle_teacher": float("nan"),
            "mean_angle_mp": float("nan"),
            "mean_angle_corrector": float("nan"),
            "median_abs_err_corrector": float("nan"),
            "median_abs_err_mp": float("nan"),
        }
    err_c = co - te
    err_m = mp - te
    abs_c = np.abs(err_c)
    abs_m = np.abs(err_m)
    closer = abs_c < abs_m
    return {
        "n": int(te.size),
        "mean_abs_err_corrector": float(abs_c.mean()),
        "mean_abs_err_mp": float(abs_m.mean()),
        "median_abs_err_corrector": float(np.median(abs_c)),
        "median_abs_err_mp": float(np.median(abs_m)),
        "pct_corrector_closer_than_mp": float(100.0 * closer.mean()),
        "mean_signed_err_corrector": float(err_c.mean()),
        "mean_signed_err_mp": float(err_m.mean()),
        "mean_angle_teacher": float(te.mean()),
        "mean_angle_mp": float(mp.mean()),
        "mean_angle_corrector": float(co.mean()),
        "mae_improvement_vs_mp_deg": float(abs_m.mean() - abs_c.mean()),
    }


def evaluate_corrector(
    *,
    clip_ids: list[str],
    teacher_root: Path,
    mp_root: Path,
    corrected_root: Path,
    reach_thr: float,
    elbow_thr_deg: float,
    jab_margin: float,
) -> dict[str, Any]:
    """Pool teacher-extended frames; score elbow (+ elevation) vs teacher."""
    elbow_te_L: list[np.ndarray] = []
    elbow_te_R: list[np.ndarray] = []
    elbow_mp_L: list[np.ndarray] = []
    elbow_mp_R: list[np.ndarray] = []
    elbow_co_L: list[np.ndarray] = []
    elbow_co_R: list[np.ndarray] = []
    elev_te_L: list[np.ndarray] = []
    elev_te_R: list[np.ndarray] = []
    elev_mp_L: list[np.ndarray] = []
    elev_mp_R: list[np.ndarray] = []
    elev_co_L: list[np.ndarray] = []
    elev_co_R: list[np.ndarray] = []

    per_clip: list[dict[str, Any]] = []
    n_used = 0
    n_skipped = 0
    n_frames_total = 0
    n_extended = 0
    n_active_L = 0
    n_active_R = 0

    for clip_id in clip_ids:
        te = load_poses(teacher_root, clip_id)
        mp = load_poses(mp_root, clip_id)
        co = load_poses(corrected_root, clip_id)
        if te is None or mp is None or co is None:
            per_clip.append({"clip_id": clip_id, "skipped": True, "reason": "missing_npy"})
            n_skipped += 1
            continue
        if te.shape[1:] != mp.shape[1:] or co.shape[1:] != mp.shape[1:]:
            per_clip.append({"clip_id": clip_id, "skipped": True, "reason": "shape_mismatch"})
            n_skipped += 1
            continue
        n = min(te.shape[0], mp.shape[0], co.shape[0])
        te, mp, co = te[:n], mp[:n], co[:n]

        te_m = arm_metrics(te)
        extended, active = detect_extended(te_m, reach_thr, elbow_thr_deg, jab_margin)
        if not extended.any():
            per_clip.append({
                "clip_id": clip_id,
                "skipped": False,
                "n_frames": int(n),
                "n_extended": 0,
            })
            n_used += 1
            n_frames_total += int(n)
            continue

        te_eL, te_eR = _elbow_angles_deg(te)
        mp_eL, mp_eR = _elbow_angles_deg(mp)
        co_eL, co_eR = _elbow_angles_deg(co)
        te_vL, te_vR = _upper_arm_elevation_deg(te)
        mp_vL, mp_vR = _upper_arm_elevation_deg(mp)
        co_vL, co_vR = _upper_arm_elevation_deg(co)

        mask = extended
        elbow_te_L.append(te_eL[mask])
        elbow_te_R.append(te_eR[mask])
        elbow_mp_L.append(mp_eL[mask])
        elbow_mp_R.append(mp_eR[mask])
        elbow_co_L.append(co_eL[mask])
        elbow_co_R.append(co_eR[mask])
        elev_te_L.append(te_vL[mask])
        elev_te_R.append(te_vR[mask])
        elev_mp_L.append(mp_vL[mask])
        elev_mp_R.append(mp_vR[mask])
        elev_co_L.append(co_vL[mask])
        elev_co_R.append(co_vR[mask])

        n_ext = int(mask.sum())
        n_ext_L = int((~active.astype(bool) & mask).sum())
        n_ext_R = int((active.astype(bool) & mask).sum())
        n_extended += n_ext
        n_active_L += n_ext_L
        n_active_R += n_ext_R
        n_used += 1
        n_frames_total += int(n)

        clip_elbow_both = _angle_stats(
            np.concatenate([te_eL[mask], te_eR[mask]]),
            np.concatenate([mp_eL[mask], mp_eR[mask]]),
            np.concatenate([co_eL[mask], co_eR[mask]]),
        )
        per_clip.append({
            "clip_id": clip_id,
            "skipped": False,
            "n_frames": int(n),
            "n_extended": n_ext,
            "n_active_L": n_ext_L,
            "n_active_R": n_ext_R,
            "elbow_both": clip_elbow_both,
            "elbow_L": _angle_stats(te_eL[mask], mp_eL[mask], co_eL[mask]),
            "elbow_R": _angle_stats(te_eR[mask], mp_eR[mask], co_eR[mask]),
        })

    def cat(parts: list[np.ndarray]) -> np.ndarray:
        return np.concatenate(parts) if parts else np.asarray([], dtype=np.float64)

    te_L, te_R = cat(elbow_te_L), cat(elbow_te_R)
    mp_L, mp_R = cat(elbow_mp_L), cat(elbow_mp_R)
    co_L, co_R = cat(elbow_co_L), cat(elbow_co_R)
    ve_L, ve_R = cat(elev_te_L), cat(elev_te_R)
    vm_L, vm_R = cat(elev_mp_L), cat(elev_mp_R)
    vc_L, vc_R = cat(elev_co_L), cat(elev_co_R)

    elbow_L = _angle_stats(te_L, mp_L, co_L)
    elbow_R = _angle_stats(te_R, mp_R, co_R)
    elbow_both = _angle_stats(
        np.concatenate([te_L, te_R]) if te_L.size else te_L,
        np.concatenate([mp_L, mp_R]) if mp_L.size else mp_L,
        np.concatenate([co_L, co_R]) if co_L.size else co_L,
    )
    elev_L = _angle_stats(ve_L, vm_L, vc_L)
    elev_R = _angle_stats(ve_R, vm_R, vc_R)
    elev_both = _angle_stats(
        np.concatenate([ve_L, ve_R]) if ve_L.size else ve_L,
        np.concatenate([vm_L, vm_R]) if vm_L.size else vm_L,
        np.concatenate([vc_L, vc_R]) if vc_L.size else vc_L,
    )

    return {
        "corrected_root": str(corrected_root),
        "n_clips_listed": len(clip_ids),
        "n_clips_used": n_used,
        "n_clips_skipped": n_skipped,
        "n_frames_total": n_frames_total,
        "n_extended": n_extended,
        "n_active_L": n_active_L,
        "n_active_R": n_active_R,
        "n_arm_angle_samples": int(elbow_both.get("n", 0)),
        "elbow": {"L": elbow_L, "R": elbow_R, "both": elbow_both},
        "upper_arm_elevation": {"L": elev_L, "R": elev_R, "both": elev_both},
        "per_clip": per_clip,
    }


def print_checkpoint_table(label: str, result: dict[str, Any]) -> None:
    e = result["elbow"]
    v = result["upper_arm_elevation"]
    print(f"\n--- {label} ---")
    print(f"  n_extended={result['n_extended']}  "
          f"(L-active {result['n_active_L']}, R-active {result['n_active_R']})  "
          f"arm-samples={result['n_arm_angle_samples']}")
    for arm_key, title in (("both", "AMBOS os bracos"), ("L", "Braco ESQUERDO"), ("R", "Braco DIREITO")):
        s = e[arm_key]
        print(f"  Elbow ({title}):")
        print(f"    mean |C-T| = {s['mean_abs_err_corrector']:.2f} deg   "
              f"mean |MP-T| = {s['mean_abs_err_mp']:.2f} deg   "
              f"dMAE (MP-C) = {s['mae_improvement_vs_mp_deg']:+.2f} deg")
        print(f"    % frames |C-T| < |MP-T| : {s['pct_corrector_closer_than_mp']:.1f}%")
        print(f"    mean signed (C-T)={s['mean_signed_err_corrector']:+.2f} deg  "
              f"(MP-T)={s['mean_signed_err_mp']:+.2f} deg")
        print(f"    mean angle T/MP/C = {s['mean_angle_teacher']:.1f} / "
              f"{s['mean_angle_mp']:.1f} / {s['mean_angle_corrector']:.1f} deg")
    sb = v["both"]
    print("  Elevacao do braco (ombro->cotovelo vs tronco, ambos):")
    print(f"    mean |C-T| = {sb['mean_abs_err_corrector']:.2f} deg   "
          f"mean |MP-T| = {sb['mean_abs_err_mp']:.2f} deg   "
          f"% closer = {sb['pct_corrector_closer_than_mp']:.1f}%")


def print_portuguese_compare(checkpoints: dict[str, dict[str, Any]], defn: dict[str, Any]) -> None:
    print()
    print("=" * 78)
    print("FIDELIDADE DE ANGULO DO BRACO AO TEACHER (nao e reach / separacao)")
    print("=" * 78)
    print("Definicao do cotovelo: angulo interior ombro-cotovelo-pulso; 180 deg ~= esticado.")
    print("Frames: mesmos teacher-extended que bench_extension "
          f"(reach>{defn['reach_thr']} OU elbow>{defn['elbow_thr_deg']} deg, "
          f"jab_margin={defn['jab_margin']}).")
    print("Avaliacao: AMBOS os bracos em cada frame extended (nao so o active).")
    print()

    labels = list(checkpoints.keys())
    # Header table for elbow both-arms
    print("Cotovelo — ambos os bracos (erro absoluto medio em graus):")
    hdr = f"{'checkpoint':<16} {'n_ext':>6} {'|C-T|':>8} {'|MP-T|':>8} {'dMAE':>8} {'%C<MP':>8} {'(C-T)':>8} {'(MP-T)':>8}"
    print(hdr)
    print("-" * len(hdr))
    for lab in labels:
        r = checkpoints[lab]
        s = r["elbow"]["both"]
        print(
            f"{lab:<16} {r['n_extended']:>6} "
            f"{s['mean_abs_err_corrector']:>8.2f} {s['mean_abs_err_mp']:>8.2f} "
            f"{s['mae_improvement_vs_mp_deg']:>+8.2f} {s['pct_corrector_closer_than_mp']:>7.1f}% "
            f"{s['mean_signed_err_corrector']:>+8.2f} {s['mean_signed_err_mp']:>+8.2f}"
        )
    print()
    print("Cotovelo — por braco:")
    print(f"{'checkpoint':<16} {'arm':>4} {'|C-T|':>8} {'|MP-T|':>8} {'dMAE':>8} {'%C<MP':>8}")
    print("-" * 56)
    for lab in labels:
        r = checkpoints[lab]
        for arm in ("L", "R"):
            s = r["elbow"][arm]
            print(
                f"{lab:<16} {arm:>4} "
                f"{s['mean_abs_err_corrector']:>8.2f} {s['mean_abs_err_mp']:>8.2f} "
                f"{s['mae_improvement_vs_mp_deg']:>+8.2f} {s['pct_corrector_closer_than_mp']:>7.1f}%"
            )
    print()
    print("Elevação do braço (ombro→cotovelo vs eixo do tronco) — ambos:")
    print(f"{'checkpoint':<16} {'|C-T|':>8} {'|MP-T|':>8} {'ΔMAE':>8} {'%C<MP':>8}")
    print("-" * 52)
    for lab in labels:
        s = checkpoints[lab]["upper_arm_elevation"]["both"]
        print(
            f"{lab:<16} "
            f"{s['mean_abs_err_corrector']:>8.2f} {s['mean_abs_err_mp']:>8.2f} "
            f"{s['mae_improvement_vs_mp_deg']:>+8.2f} {s['pct_corrector_closer_than_mp']:>7.1f}%"
        )
    print()
    print("ΔMAE = mean|MP-T| - mean|C-T|  (positivo = corrector mais perto do teacher).")
    print("%C<MP = % de amostras (braço×frame) com |C-T| < |MP-T|.")
    print("Erro assinado: positivo = ângulo maior que o teacher (mais esticado se cotovelo).")
    print("=" * 78)


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--split", default="test", choices=("train", "val", "test"))
    ap.add_argument("--manifest", type=Path, default=LAB_ROOT / "data" / "splits" / "manifest.json")
    ap.add_argument("--teacher-root", type=Path, default=LAB_ROOT / "data" / "teacher_aligned")
    ap.add_argument("--mp-root", type=Path, default=LAB_ROOT / "data" / "mediapipe")
    ap.add_argument(
        "--corrected",
        action="append",
        default=None,
        metavar="LABEL=DIR",
        help="Corrector export, e.g. ep4=runs/.../corrected_ep4 (repeatable)",
    )
    ap.add_argument("--reach-thr", type=float, default=0.85)
    ap.add_argument("--elbow-thr-deg", type=float, default=160.0)
    ap.add_argument(
        "--jab-margin",
        type=float,
        default=0.08,
        help="Min (active-guard) teacher reach; 0 disables asymmetry filter",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="JSON output path",
    )
    ap.add_argument(
        "--run",
        type=Path,
        default=LAB_ROOT / "runs" / "20260726_001626_gru_v1",
        help="Default run dir for ep4/last corrected + eval out",
    )
    args = ap.parse_args()

    # Default: compare ep4 vs last for the known run (side-by-side exports).
    if args.corrected is None:
        run = Path(args.run)
        args.corrected = [
            f"ep4={run / 'corrected_ep4'}",
            f"last={run / 'corrected_last'}",
        ]

    corrected_specs: list[tuple[str, Path]] = []
    for item in args.corrected:
        if "=" not in item:
            raise SystemExit(f"--corrected must be LABEL=DIR, got: {item}")
        label, path_s = item.split("=", 1)
        corrected_specs.append((label.strip(), Path(path_s.strip())))

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    clip_ids: list[str] = list(manifest["splits"][args.split])

    defn = {
        "metric": (
            "angle fidelity to teacher — NOT reach magnitude / hand separation"
        ),
        "elbow_angle": (
            "interior angle(shoulder-elbow-wrist) in degrees; 180 ~= straight "
            "(same as losses._elbow_angle_deg / bench_extension)"
        ),
        "upper_arm_elevation": (
            "angle between shoulder→elbow and trunk up (mid-hip→mid-shoulder), degrees"
        ),
        "arms_evaluated": "both L and R on every teacher-extended frame",
        "reach_thr": args.reach_thr,
        "elbow_thr_deg": args.elbow_thr_deg,
        "jab_margin": args.jab_margin,
        "extended_rule": (
            "teacher active reach > reach_thr OR teacher active elbow angle > elbow_thr_deg; "
            "AND (active_reach - guard_reach) >= jab_margin if jab_margin > 0 "
            "(identical to bench_extension.py)"
        ),
        "errors": (
            "abs = |pred - teacher|; signed = pred - teacher; "
            "pct_corrector_closer = share of arm×frame with |C-T| < |MP-T|"
        ),
    }

    checkpoints: dict[str, dict[str, Any]] = {}
    for label, corr_root in corrected_specs:
        if not corr_root.is_dir():
            raise SystemExit(f"corrected dir missing for {label}: {corr_root}")
        print(f"Evaluating {label} from {corr_root} ...")
        checkpoints[label] = evaluate_corrector(
            clip_ids=clip_ids,
            teacher_root=args.teacher_root,
            mp_root=args.mp_root,
            corrected_root=corr_root,
            reach_thr=args.reach_thr,
            elbow_thr_deg=args.elbow_thr_deg,
            jab_margin=args.jab_margin,
        )
        print_checkpoint_table(label, checkpoints[label])

    run = Path(args.run)
    out_path = args.out or (run / "eval" / "arm_angles_compare_ep4_vs_last.json")

    # Compact side-by-side for the compare JSON
    compare: dict[str, Any] = {}
    for lab, r in checkpoints.items():
        compare[lab] = {
            "corrected_root": r["corrected_root"],
            "n_extended": r["n_extended"],
            "n_arm_angle_samples": r["n_arm_angle_samples"],
            "elbow_both": r["elbow"]["both"],
            "elbow_L": r["elbow"]["L"],
            "elbow_R": r["elbow"]["R"],
            "elevation_both": r["upper_arm_elevation"]["both"],
        }

    result: dict[str, Any] = {
        "created_unix": time.time(),
        "benchmark": "arm_angle_fidelity_to_teacher",
        "note": (
            "Measures how much closer the corrector is to teacher ARM ANGLES "
            "than MediaPipe. Does NOT measure max-reach or hand-separation."
        ),
        "split": args.split,
        "timebase": "source_fps_viewer_exports",
        "teacher_root": str(args.teacher_root),
        "mp_root": str(args.mp_root),
        "run": str(run),
        "definition": defn,
        "compare": compare,
        "checkpoints": checkpoints,
        "results_path": str(out_path),
    }
    write_json(out_path, result)
    print_portuguese_compare(checkpoints, defn)
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
