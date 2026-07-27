#!/usr/bin/env python3
"""Estimate safe lateral crop % on YOLO person clips.

Samples frames, re-detects people, picks the primary (most central) person,
and reports how much left/right width can be cut without clipping them.
Also flags side-person intrusion.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO

LAB_ROOT = Path(__file__).resolve().parents[1]
PEOPLE_ROOT = LAB_ROOT / "data" / "input" / "people"


def sample_frame_indices(n_frames: int, n_samples: int) -> list[int]:
    if n_frames <= 0:
        return []
    if n_frames <= n_samples:
        return list(range(n_frames))
    # avoid first/last edge frames a bit
    lo = max(0, int(0.08 * n_frames))
    hi = min(n_frames - 1, int(0.92 * n_frames))
    if hi <= lo:
        return [n_frames // 2]
    xs = np.linspace(lo, hi, n_samples)
    return sorted({int(round(x)) for x in xs})


def read_frames(path: Path, indices: list[int]) -> list[tuple[int, np.ndarray]]:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return []
    out = []
    for idx in indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        if ok:
            out.append((idx, frame))
    cap.release()
    return out


def pick_primary(boxes: np.ndarray, w: int, h: int) -> int:
    """Index of person closest to frame center, area-weighted tie-break."""
    cx, cy = w * 0.5, h * 0.5
    centers = 0.5 * (boxes[:, 0:2] + boxes[:, 2:4])
    areas = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    dist = np.linalg.norm(centers - np.array([cx, cy]), axis=1)
    # prefer center; among near-center, prefer larger
    score = dist / max(w, h) - 0.15 * (areas / (w * h))
    return int(np.argmin(score))


def analyze_clip(
    model: YOLO,
    clip_path: Path,
    n_samples: int,
    conf: float,
    imgsz: int,
    keep_pad: float,
) -> dict:
    cap = cv2.VideoCapture(str(clip_path))
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
    cap.release()

    idxs = sample_frame_indices(n_frames, n_samples)
    frames = read_frames(clip_path, idxs)
    if not frames or w <= 0:
        return {"ok": False, "error": "no_frames", "clip": str(clip_path)}

    primary_x1s, primary_x2s = [], []
    side_hits = 0
    multi_hits = 0
    det_frames = 0
    max_side_overlap = 0.0  # fraction of width overlapping side people outside primary

    for _, frame in frames:
        r = model.predict(
            source=frame,
            classes=[0],
            conf=conf,
            imgsz=imgsz,
            verbose=False,
        )[0]
        if r.boxes is None or len(r.boxes) == 0:
            continue
        boxes = r.boxes.xyxy.cpu().numpy()
        det_frames += 1
        if len(boxes) > 1:
            multi_hits += 1
        pi = pick_primary(boxes, w, h)
        px1, py1, px2, py2 = boxes[pi]
        primary_x1s.append(float(px1))
        primary_x2s.append(float(px2))

        # side people: any other box whose center is outside primary
        for j, b in enumerate(boxes):
            if j == pi:
                continue
            side_hits += 1
            # how much of that side person sits near edges
            sx1, sx2 = float(b[0]), float(b[2])
            # intrusion from left of primary
            if sx2 < px1:
                max_side_overlap = max(max_side_overlap, sx2 / w)
            elif sx1 > px2:
                max_side_overlap = max(max_side_overlap, (w - sx1) / w)
            else:
                # overlapping primary horizontally — measure overhang outside primary
                left_over = max(0.0, px1 - sx1) / w
                right_over = max(0.0, sx2 - px2) / w
                max_side_overlap = max(max_side_overlap, left_over, right_over)

    if not primary_x1s:
        return {
            "ok": False,
            "error": "no_person_detected",
            "clip": str(clip_path),
            "width": w,
            "height": h,
            "n_frames": n_frames,
        }

    # Worst-case primary extent across samples (so crop never clips them)
    x1 = min(primary_x1s)
    x2 = max(primary_x2s)
    pad_px = keep_pad * w
    keep_x1 = max(0.0, x1 - pad_px)
    keep_x2 = min(float(w), x2 + pad_px)

    crop_left_px = keep_x1
    crop_right_px = float(w) - keep_x2
    crop_left_pct = 100.0 * crop_left_px / w
    crop_right_pct = 100.0 * crop_right_px / w
    crop_total_pct = crop_left_pct + crop_right_pct

    # Also a "tight" estimate without keep_pad (raw person bbox)
    tight_left = 100.0 * x1 / w
    tight_right = 100.0 * (w - x2) / w

    rel = clip_path.relative_to(PEOPLE_ROOT).as_posix()
    return {
        "ok": True,
        "clip": rel,
        "group": rel.split("/")[0],
        "shot": "/".join(rel.split("/")[:-2]) if "/" in rel else rel,
        "person": clip_path.parent.name,
        "width": w,
        "height": h,
        "fps": round(fps, 3),
        "n_frames": n_frames,
        "n_samples": len(frames),
        "det_frames": det_frames,
        "multi_person_frames": multi_hits,
        "side_detections": side_hits,
        "has_side_person": side_hits > 0,
        "primary_x1_frac": round(x1 / w, 4),
        "primary_x2_frac": round(x2 / w, 4),
        "primary_width_frac": round((x2 - x1) / w, 4),
        "safe_crop_left_pct": round(max(0.0, crop_left_pct), 2),
        "safe_crop_right_pct": round(max(0.0, crop_right_pct), 2),
        "safe_crop_total_pct": round(max(0.0, crop_total_pct), 2),
        "tight_crop_left_pct": round(max(0.0, tight_left), 2),
        "tight_crop_right_pct": round(max(0.0, tight_right), 2),
        "tight_crop_total_pct": round(max(0.0, tight_left + tight_right), 2),
        "recommend_20pct": crop_total_pct >= 18.0,
        "keep_pad": keep_pad,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--people-root", type=Path, default=PEOPLE_ROOT)
    ap.add_argument("--model", default=str(LAB_ROOT / "yolo11n.pt"))
    ap.add_argument("--device", default="0")
    ap.add_argument("--conf", type=float, default=0.35)
    ap.add_argument("--imgsz", type=int, default=416)
    ap.add_argument("--samples", type=int, default=5)
    ap.add_argument(
        "--keep-pad",
        type=float,
        default=0.04,
        help="extra horizontal pad around primary as fraction of width",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=LAB_ROOT / "data" / "input" / "people" / "side_crop_report.json",
    )
    args = ap.parse_args()

    clips = sorted(args.people_root.rglob("clip.mp4"))
    print(f"[analyze] clips={len(clips)} model={args.model} device={args.device}", flush=True)
    model = YOLO(args.model)

    rows = []
    for i, clip in enumerate(clips, 1):
        row = analyze_clip(
            model,
            clip,
            n_samples=args.samples,
            conf=args.conf,
            imgsz=args.imgsz,
            keep_pad=args.keep_pad,
        )
        rows.append(row)
        if i % 10 == 0 or i == len(clips):
            ok = sum(1 for r in rows if r.get("ok"))
            print(f"[analyze] {i}/{len(clips)} ok={ok}", flush=True)

    ok_rows = [r for r in rows if r.get("ok")]
    by_group: dict[str, list] = {}
    for r in ok_rows:
        by_group.setdefault(r["group"], []).append(r)

    summary = {
        "n_clips": len(rows),
        "n_ok": len(ok_rows),
        "n_fail": len(rows) - len(ok_rows),
        "keep_pad": args.keep_pad,
        "samples_per_clip": args.samples,
        "global": _agg(ok_rows),
        "by_group": {g: _agg(rs) for g, rs in sorted(by_group.items())},
        "clips": rows,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    csv_path = args.out.with_suffix(".csv")
    fields = [
        "clip",
        "group",
        "shot",
        "person",
        "safe_crop_left_pct",
        "safe_crop_right_pct",
        "safe_crop_total_pct",
        "tight_crop_total_pct",
        "primary_width_frac",
        "has_side_person",
        "multi_person_frames",
        "side_detections",
        "recommend_20pct",
        "width",
        "height",
        "n_frames",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in ok_rows:
            w.writerow(r)

    # markdown report
    md_path = args.out.with_suffix(".md")
    md_path.write_text(_markdown(summary), encoding="utf-8")

    print(f"[analyze] wrote {args.out}")
    print(f"[analyze] wrote {csv_path}")
    print(f"[analyze] wrote {md_path}")
    g = summary["global"]
    print(
        f"[analyze] safe total crop: mean={g['safe_crop_total_pct']['mean']:.1f}% "
        f"median={g['safe_crop_total_pct']['median']:.1f}% "
        f"p25={g['safe_crop_total_pct']['p25']:.1f}% "
        f"p75={g['safe_crop_total_pct']['p75']:.1f}% "
        f"side_person={g['pct_with_side_person']:.0f}% "
        f"recommend_20pct={g['pct_recommend_20pct']:.0f}%",
        flush=True,
    )


def _stats(vals: list[float]) -> dict:
    if not vals:
        return {"mean": 0, "median": 0, "p25": 0, "p75": 0, "min": 0, "max": 0}
    a = np.array(vals, dtype=np.float64)
    return {
        "mean": round(float(a.mean()), 2),
        "median": round(float(np.median(a)), 2),
        "p25": round(float(np.percentile(a, 25)), 2),
        "p75": round(float(np.percentile(a, 75)), 2),
        "min": round(float(a.min()), 2),
        "max": round(float(a.max()), 2),
    }


def _agg(rows: list[dict]) -> dict:
    if not rows:
        return {}
    return {
        "n": len(rows),
        "safe_crop_total_pct": _stats([r["safe_crop_total_pct"] for r in rows]),
        "safe_crop_left_pct": _stats([r["safe_crop_left_pct"] for r in rows]),
        "safe_crop_right_pct": _stats([r["safe_crop_right_pct"] for r in rows]),
        "tight_crop_total_pct": _stats([r["tight_crop_total_pct"] for r in rows]),
        "primary_width_frac": _stats([r["primary_width_frac"] for r in rows]),
        "pct_with_side_person": round(
            100.0 * sum(1 for r in rows if r["has_side_person"]) / len(rows), 1
        ),
        "pct_recommend_20pct": round(
            100.0 * sum(1 for r in rows if r["recommend_20pct"]) / len(rows), 1
        ),
    }


def _markdown(summary: dict) -> str:
    lines = []
    lines.append("# YOLO people side-crop report")
    lines.append("")
    lines.append(
        f"Analyzed **{summary['n_ok']}** / {summary['n_clips']} person clips "
        f"({summary['samples_per_clip']} frames each, keep_pad={summary['keep_pad']})."
    )
    lines.append("")
    lines.append(
        "Safe crop = cut left/right while keeping the primary person bbox "
        "(worst-case across samples) + keep_pad. Tight crop = same without pad."
    )
    lines.append("")
    g = summary["global"]
    lines.append("## Global")
    lines.append("")
    lines.append("| metric | mean | median | p25 | p75 | min | max |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for key, label in [
        ("safe_crop_total_pct", "safe total crop %"),
        ("safe_crop_left_pct", "safe left %"),
        ("safe_crop_right_pct", "safe right %"),
        ("tight_crop_total_pct", "tight total crop %"),
        ("primary_width_frac", "primary width frac"),
    ]:
        s = g[key]
        lines.append(
            f"| {label} | {s['mean']} | {s['median']} | {s['p25']} | {s['p75']} | {s['min']} | {s['max']} |"
        )
    lines.append("")
    lines.append(f"- Clips with side person detected: **{g['pct_with_side_person']}%**")
    lines.append(f"- Clips where ≥18% total safe crop is available: **{g['pct_recommend_20pct']}%**")
    lines.append("")

    lines.append("## By group")
    lines.append("")
    lines.append("| group | n | safe total mean | median | p25 | p75 | side person % | ≥18% ok % |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for name, agg in summary["by_group"].items():
        s = agg["safe_crop_total_pct"]
        lines.append(
            f"| {name} | {agg['n']} | {s['mean']} | {s['median']} | {s['p25']} | {s['p75']} | "
            f"{agg['pct_with_side_person']} | {agg['pct_recommend_20pct']} |"
        )
    lines.append("")

    # Per beginner clip detail
    beginner = [
        r
        for r in summary["clips"]
        if r.get("ok") and str(r.get("group", "")).startswith("beginner_friendly")
    ]
    if beginner:
        lines.append("## Beginner Friendly detail")
        lines.append("")
        lines.append("| clip | L% | R% | total% | tight% | primary_w | side? |")
        lines.append("|---|---:|---:|---:|---:|---:|:---:|")
        for r in sorted(beginner, key=lambda x: x["clip"]):
            lines.append(
                f"| `{r['clip']}` | {r['safe_crop_left_pct']} | {r['safe_crop_right_pct']} | "
                f"{r['safe_crop_total_pct']} | {r['tight_crop_total_pct']} | "
                f"{r['primary_width_frac']} | {'Y' if r['has_side_person'] else ''} |"
            )
        lines.append("")

    # Top / bottom for burn
    burn = [r for r in summary["clips"] if r.get("ok") and r.get("group") == "burn_500_shots"]
    if burn:
        burn_sorted = sorted(burn, key=lambda x: x["safe_crop_total_pct"], reverse=True)
        lines.append("## Burn 500 — most cropable (top 15)")
        lines.append("")
        lines.append("| clip | total% | L% | R% | side? |")
        lines.append("|---|---:|---:|---:|:---:|")
        for r in burn_sorted[:15]:
            lines.append(
                f"| `{r['clip']}` | {r['safe_crop_total_pct']} | {r['safe_crop_left_pct']} | "
                f"{r['safe_crop_right_pct']} | {'Y' if r['has_side_person'] else ''} |"
            )
        lines.append("")
        lines.append("## Burn 500 — least cropable (bottom 15)")
        lines.append("")
        lines.append("| clip | total% | L% | R% | side? |")
        lines.append("|---|---:|---:|---:|:---:|")
        for r in burn_sorted[-15:]:
            lines.append(
                f"| `{r['clip']}` | {r['safe_crop_total_pct']} | {r['safe_crop_left_pct']} | "
                f"{r['safe_crop_right_pct']} | {'Y' if r['has_side_person'] else ''} |"
            )
        lines.append("")

        # aggregate by shot
        by_shot: dict[str, list] = {}
        for r in burn:
            by_shot.setdefault(r["shot"], []).append(r)
        lines.append("## Burn 500 — per shot (mean safe total %)")
        lines.append("")
        lines.append("| shot | n people | mean total% | median | side person % |")
        lines.append("|---|---:|---:|---:|---:|")
        for shot, rs in sorted(by_shot.items()):
            s = _stats([r["safe_crop_total_pct"] for r in rs])
            side = 100.0 * sum(1 for r in rs if r["has_side_person"]) / len(rs)
            lines.append(
                f"| `{shot}` | {len(rs)} | {s['mean']} | {s['median']} | {side:.0f} |"
            )
        lines.append("")

    lines.append("## Recommendation")
    lines.append("")
    med = g["safe_crop_total_pct"]["median"]
    p25 = g["safe_crop_total_pct"]["p25"]
    lines.append(
        f"- Median safe lateral crop is **{med}%** of width "
        f"(p25={p25}%, so ~1/4 of clips allow less than that)."
    )
    lines.append(
        "- A uniform **20% total** crop (10% each side) is reasonable for clips "
        f"marked recommend_20pct ({g['pct_recommend_20pct']}%), but will clip "
        "arms/body on tighter ones — prefer per-clip crop from this table, "
        "or reduce square-pad in `split_people.py`."
    )
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
