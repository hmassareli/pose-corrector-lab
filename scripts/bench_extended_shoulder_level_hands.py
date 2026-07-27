#!/usr/bin/env python3
"""Hand proximity on teacher extended + shoulder-level arm frames.

NOT jab detection. Selects frames from the *teacher* pose only with a strict
geometric test, then scores how close Corrector / MediaPipe wrists are to the
teacher wrists on those frames.

Frame selection (teacher, per arm, both arms can qualify independently)
----------------------------------------------------------------------
An arm (L or R) on frame t qualifies if ALL of:

  (1) Reach ratio >= --reach-min (default 0.70):
        reach = ||wrist - shoulder|| / (||shoulder - elbow|| + ||elbow - wrist||)

  (2) Wrist near shoulder height (body frame of the teacher pose at t):
        |wrist_y - shoulder_y| / shoulder_width  <=  --height-band  (default 0.55)
      Body frame: +Y = trunk up (hip→shoulder), +X = L→R shoulders, +Z = forward
      (same as pose_lab.align.body_frame_from_pose). shoulder_width = ||RS - LS||.

  (3) Arm not hanging / dropped — direction of (wrist - shoulder) is more
      horizontal than downward, in the same teacher body frame:
        Let u = normalize(wrist - shoulder) in body coords.
        Require u_y >= --min-uy  (default -0.35)
          ≈ not more than ~20° below the horizontal plane through the shoulder
        AND hypot(u_x, u_z) >= --min-horiz  (default 0.55)
          ≈ horizontal/outward component dominates (rejects mostly vertical arms)

If both arms qualify on the same frame, both contribute samples (per-side).
If one qualifies, only that side is used for "active" metrics; the other wrist
still enters the both-wrists proximity pool for that frame when we score
combined hand error (see below).

Metrics (ONLY on frames with >=1 qualifying teacher arm)
--------------------------------------------------------
Primary — hand proximity to teacher (meters in aligned export space):
  For each selected frame, define:
    err_C = 0.5 * ( ||wristL_C - wristL_T|| + ||wristR_C - wristR_T|| )
    err_MP = 0.5 * ( ||wristL_MP - wristL_T|| + ||wristR_MP - wristR_T|| )
  Report mean err_C, mean err_MP, and mean(err_MP - err_C).
  Also per-side means on frames where that side qualified:
    mean ||wrist_active_C - wrist_active_T||  (and same for guard / MP).

Secondary:
  - Hand-separation error: mean | ||wL-wR||_C - ||wL-wR||_T |  vs same for MP
  - pct_frames_C_closer: % selected frames with err_C < err_MP

Leaderboard column: `hand_prox_mae_C` (lower better) and `hand_prox_impr_vs_mp`
  = (mean_err_MP - mean_err_C) / max(mean_err_MP, eps)  (higher better).
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

from pose_lab.align import body_frame_from_pose, to_body_frame  # noqa: E402
from pose_lab.logging_utils import write_json  # noqa: E402
from pose_lab.skeleton import JOINT_TO_IDX  # noqa: E402

LS = JOINT_TO_IDX["left_shoulder"]
RS = JOINT_TO_IDX["right_shoulder"]
LE = JOINT_TO_IDX["left_elbow"]
RE = JOINT_TO_IDX["right_elbow"]
LW = JOINT_TO_IDX["left_wrist"]
RW = JOINT_TO_IDX["right_wrist"]


def load_poses(root: Path, clip_id: str) -> np.ndarray | None:
    p = root / clip_id / "joints3d.npy"
    if not p.is_file():
        return None
    arr = np.load(p).astype(np.float64)
    if arr.ndim != 3 or arr.shape[0] < 1:
        return None
    return arr


def _reach_ratios(poses: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    out = []
    for sh, el, wr in ((LS, LE, LW), (RS, RE, RW)):
        se = np.linalg.norm(poses[:, el] - poses[:, sh], axis=-1)
        ew = np.linalg.norm(poses[:, wr] - poses[:, el], axis=-1)
        sw = np.linalg.norm(poses[:, wr] - poses[:, sh], axis=-1)
        out.append(np.clip(sw / np.maximum(se + ew, 1e-8), 0.0, 1.05))
    return out[0], out[1]


def teacher_arm_qualifies(
    te: np.ndarray,
    *,
    reach_min: float,
    height_band: float,
    min_uy: float,
    min_horiz: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (qual_L[T], qual_R[T]) bool masks from teacher pose only."""
    T = te.shape[0]
    reach_L, reach_R = _reach_ratios(te)
    qual_L = np.zeros(T, dtype=bool)
    qual_R = np.zeros(T, dtype=bool)
    for t in range(T):
        R, scale, origin = body_frame_from_pose(te[t])
        # Body coords already / shoulder_width (scale), so |dy| is in shoulder-widths.
        pb = to_body_frame(te[t], R, scale, origin)
        for side, sh, wr, reach, qual in (
            ("L", LS, LW, reach_L[t], qual_L),
            ("R", RS, RW, reach_R[t], qual_R),
        ):
            if reach < reach_min:
                continue
            d = pb[wr] - pb[sh]
            n = float(np.linalg.norm(d))
            if n < 1e-8:
                continue
            u = d / n
            # (2) near shoulder height: |wrist_y - shoulder_y| / shoulder_width
            if abs(float(d[1])) > height_band:
                continue
            # (3) not hanging: uy not too negative; horizontal plane component
            if float(u[1]) < min_uy:
                continue
            if float(np.hypot(u[0], u[2])) < min_horiz:
                continue
            if side == "L":
                qual_L[t] = True
            else:
                qual_R[t] = True
    return qual_L, qual_R


def evaluate_corrector(
    *,
    clip_ids: list[str],
    teacher_root: Path,
    mp_root: Path,
    corrected_root: Path,
    reach_min: float,
    height_band: float,
    min_uy: float,
    min_horiz: float,
) -> dict[str, Any]:
    err_c_all: list[float] = []
    err_mp_all: list[float] = []
    sep_err_c: list[float] = []
    sep_err_mp: list[float] = []
    act_err_c: list[float] = []
    act_err_mp: list[float] = []
    grd_err_c: list[float] = []
    grd_err_mp: list[float] = []
    n_frames_sel = 0
    n_side_L = 0
    n_side_R = 0
    n_both = 0
    n_used = 0
    n_skipped = 0
    n_frames_total = 0

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
        n_frames_total += int(n)

        qL, qR = teacher_arm_qualifies(
            te,
            reach_min=reach_min,
            height_band=height_band,
            min_uy=min_uy,
            min_horiz=min_horiz,
        )
        sel = qL | qR
        if not sel.any():
            continue

        for t in np.flatnonzero(sel):
            n_frames_sel += 1
            if qL[t] and qR[t]:
                n_both += 1
            if qL[t]:
                n_side_L += 1
            if qR[t]:
                n_side_R += 1

            dL_c = float(np.linalg.norm(co[t, LW] - te[t, LW]))
            dR_c = float(np.linalg.norm(co[t, RW] - te[t, RW]))
            dL_m = float(np.linalg.norm(mp[t, LW] - te[t, LW]))
            dR_m = float(np.linalg.norm(mp[t, RW] - te[t, RW]))
            err_c_all.append(0.5 * (dL_c + dR_c))
            err_mp_all.append(0.5 * (dL_m + dR_m))

            sep_t = float(np.linalg.norm(te[t, LW] - te[t, RW]))
            sep_c = float(np.linalg.norm(co[t, LW] - co[t, RW]))
            sep_m = float(np.linalg.norm(mp[t, LW] - mp[t, RW]))
            sep_err_c.append(abs(sep_c - sep_t))
            sep_err_mp.append(abs(sep_m - sep_t))

            # Active = qualifying side with larger teacher reach if both; else the one
            rL, rR = _reach_ratios(te[t : t + 1])
            if qL[t] and qR[t]:
                active_R = bool(rR[0] >= rL[0])
            else:
                active_R = bool(qR[t])
            if active_R:
                act_err_c.append(dR_c)
                act_err_mp.append(dR_m)
                grd_err_c.append(dL_c)
                grd_err_mp.append(dL_m)
            else:
                act_err_c.append(dL_c)
                act_err_mp.append(dL_m)
                grd_err_c.append(dR_c)
                grd_err_mp.append(dR_m)

    ec = np.asarray(err_c_all, dtype=np.float64)
    em = np.asarray(err_mp_all, dtype=np.float64)
    if ec.size == 0:
        mean_c = mean_m = float("nan")
        pct_closer = float("nan")
        impr = float("nan")
    else:
        mean_c = float(ec.mean())
        mean_m = float(em.mean())
        pct_closer = float(100.0 * (ec < em).mean())
        impr = float((mean_m - mean_c) / max(mean_m, 1e-8))

    def _m(xs: list[float]) -> float:
        return float(np.mean(xs)) if xs else float("nan")

    return {
        "corrected_root": str(corrected_root),
        "n_clips_used": n_used,
        "n_clips_skipped": n_skipped,
        "n_frames_total": n_frames_total,
        "n_frames_selected": n_frames_sel,
        "n_side_L": n_side_L,
        "n_side_R": n_side_R,
        "n_both_sides": n_both,
        "selection": {
            "reach_min": reach_min,
            "height_band": height_band,
            "min_uy": min_uy,
            "min_horiz": min_horiz,
        },
        "hand_prox_mae_C": mean_c,
        "hand_prox_mae_MP": mean_m,
        "hand_prox_impr_vs_mp": impr,
        "pct_frames_C_closer": pct_closer,
        "active_wrist_mae_C": _m(act_err_c),
        "active_wrist_mae_MP": _m(act_err_mp),
        "guard_wrist_mae_C": _m(grd_err_c),
        "guard_wrist_mae_MP": _m(grd_err_mp),
        "sep_mae_C": _m(sep_err_c),
        "sep_mae_MP": _m(sep_err_mp),
    }


def print_summary(label: str, r: dict[str, Any]) -> None:
    print(f"\n=== extended_shoulder_level_hands [{label}] ===")
    print(
        f"  selected_frames={r['n_frames_selected']}  "
        f"(L={r['n_side_L']} R={r['n_side_R']} both={r['n_both_sides']})"
    )
    print(
        f"  hand_prox MAE C/MP = {r['hand_prox_mae_C']:.5f} / {r['hand_prox_mae_MP']:.5f}  "
        f"impr={r['hand_prox_impr_vs_mp']:+.3f}  pct_C_closer={r['pct_frames_C_closer']:.1f}%"
    )
    print(
        f"  active wrist MAE C/MP = {r['active_wrist_mae_C']:.5f} / {r['active_wrist_mae_MP']:.5f}  "
        f"guard = {r['guard_wrist_mae_C']:.5f} / {r['guard_wrist_mae_MP']:.5f}"
    )
    print(
        f"  sep MAE C/MP = {r['sep_mae_C']:.5f} / {r['sep_mae_MP']:.5f}"
    )


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--manifest", type=Path, default=LAB_ROOT / "data" / "splits" / "manifest.json")
    ap.add_argument("--split", default="test", choices=("train", "val", "test"))
    ap.add_argument("--teacher-root", type=Path, default=LAB_ROOT / "data" / "teacher_aligned")
    ap.add_argument("--mp-root", type=Path, default=LAB_ROOT / "data" / "mediapipe")
    ap.add_argument("--corrected", action="append", default=None, help="LABEL=DIR")
    ap.add_argument("--corrected-root", type=Path, default=None)
    ap.add_argument("--label", default="corrector")
    ap.add_argument("--reach-min", type=float, default=0.70)
    ap.add_argument("--height-band", type=float, default=0.55,
                    help="Max |wrist_y-shoulder_y|/shoulder_width in teacher body frame")
    ap.add_argument("--min-uy", type=float, default=-0.35,
                    help="Min body-frame uy of unit(wrist-shoulder); rejects hanging arms")
    ap.add_argument("--min-horiz", type=float, default=0.55,
                    help="Min hypot(ux,uz) of unit(wrist-shoulder)")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--run", type=Path, default=None)
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
        print(f"Evaluating hands {lab} from {root} ...", flush=True)
        r = evaluate_corrector(
            clip_ids=clip_ids,
            teacher_root=args.teacher_root,
            mp_root=args.mp_root,
            corrected_root=root,
            reach_min=args.reach_min,
            height_band=args.height_band,
            min_uy=args.min_uy,
            min_horiz=args.min_horiz,
        )
        print_summary(lab, r)
        compare[lab] = r

    out = args.out
    if out is None:
        out = (
            (Path(args.run) / "eval" / "extended_shoulder_level_hands.json")
            if args.run
            else LAB_ROOT / "data" / "evals" / f"extended_shoulder_level_hands_{args.split}.json"
        )
    out.parent.mkdir(parents=True, exist_ok=True)
    result = {
        "created_unix": time.time(),
        "benchmark": "extended_shoulder_level_hands",
        "note": (
            "Teacher-only selection: reach>=0.70 AND wrist near shoulder height "
            "AND arm not hanging. Primary metric: mean both-wrists distance to teacher."
        ),
        "split": args.split,
        "timebase": "source_fps_viewer_exports",
        "compare": compare,
        "results_path": str(out),
    }
    write_json(out, result)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
