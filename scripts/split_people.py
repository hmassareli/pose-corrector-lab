#!/usr/bin/env python3
"""Split a multi-person video into per-person clips via YOLO + ByteTrack.

Usage:
  python scripts/split_people.py --video "data/input/Burn 500....mp4"
  python scripts/split_people.py --video path.mp4 --min-sec 30 --device 0

Outputs:
  data/input/people/<stem>/person_XXX/clip.mp4
  data/input/people/<stem>/person_XXX/meta.json
  data/input/people/<stem>/people_manifest.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]


def stem_slug(path: Path) -> str:
    name = path.stem.lower()
    out = []
    prev_us = False
    for ch in name:
        if ch.isalnum():
            out.append(ch)
            prev_us = False
        else:
            if not prev_us:
                out.append("_")
                prev_us = True
    s = "".join(out).strip("_")
    # keep it readable / short
    for prefix in ("burn_500_calories", "intense_10_minute", "shadow_clip"):
        if s.startswith(prefix):
            return prefix
    return s[:60].rstrip("_")


def ema_update(prev, new, alpha: float):
    if prev is None:
        return new.astype(np.float32)
    return (alpha * new + (1.0 - alpha) * prev).astype(np.float32)


def pad_box(xyxy: np.ndarray, w: int, h: int, pad: float) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = map(float, xyxy)
    bw, bh = x2 - x1, y2 - y1
    cx, cy = (x1 + x2) * 0.5, (y1 + y2) * 0.5
    # slight square bias helps pose models
    side = max(bw, bh) * (1.0 + pad)
    nx1 = int(max(0, cx - side * 0.5))
    ny1 = int(max(0, cy - side * 0.5))
    nx2 = int(min(w - 1, cx + side * 0.5))
    ny2 = int(min(h - 1, cy + side * 0.5))
    if nx2 <= nx1 + 2 or ny2 <= ny1 + 2:
        return int(x1), int(y1), int(x2), int(y2)
    return nx1, ny1, nx2, ny2


def even_size(v: int) -> int:
    v = max(2, int(v))
    return v + (v % 2)


def max_box_size(boxes: list[np.ndarray], pad: float = 0.0) -> tuple[int, int]:
    """Max YOLO width/height across the track (+ optional pad fraction)."""
    arr = np.stack(boxes, axis=0)
    max_w = float((arr[:, 2] - arr[:, 0]).max()) * (1.0 + pad)
    max_h = float((arr[:, 3] - arr[:, 1]).max()) * (1.0 + pad)
    return even_size(int(np.ceil(max_w))), even_size(int(np.ceil(max_h)))


def crop_fixed_size(
    frame: np.ndarray,
    box: np.ndarray,
    crop_w: int,
    crop_h: int,
) -> np.ndarray:
    """Crop crop_w x crop_h centered on box; pad with edge if near border."""
    h, w = frame.shape[:2]
    cx = 0.5 * (float(box[0]) + float(box[2]))
    cy = 0.5 * (float(box[1]) + float(box[3]))
    x1 = int(round(cx - crop_w * 0.5))
    y1 = int(round(cy - crop_h * 0.5))
    x2 = x1 + crop_w
    y2 = y1 + crop_h

    pad_l = max(0, -x1)
    pad_t = max(0, -y1)
    pad_r = max(0, x2 - w)
    pad_b = max(0, y2 - h)
    xa1, ya1 = max(0, x1), max(0, y1)
    xa2, ya2 = min(w, x2), min(h, y2)
    crop = frame[ya1:ya2, xa1:xa2]
    if pad_l or pad_t or pad_r or pad_b:
        crop = cv2.copyMakeBorder(
            crop, pad_t, pad_b, pad_l, pad_r, borderType=cv2.BORDER_REPLICATE
        )
    if crop.shape[1] != crop_w or crop.shape[0] != crop_h:
        crop = cv2.resize(crop, (crop_w, crop_h), interpolation=cv2.INTER_AREA)
    return crop


def track_people(
    video_path: Path,
    model_name: str,
    device: str,
    conf: float,
    imgsz: int,
) -> tuple[dict[int, dict], float, int, int, int]:
    from ultralytics import YOLO

    model = YOLO(model_name)
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open {video_path}")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 24.0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    cap.release()

    tracks: dict[int, dict] = defaultdict(lambda: {"frames": [], "boxes": [], "confs": []})
    t0 = time.time()
    frame_i = 0
    last_log = 0.0

    results = model.track(
        source=str(video_path),
        stream=True,
        persist=True,
        classes=[0],  # person
        conf=conf,
        imgsz=imgsz,
        device=device,
        tracker="bytetrack.yaml",
        verbose=False,
    )

    for r in results:
        if r.boxes is not None and r.boxes.id is not None:
            ids = r.boxes.id.cpu().numpy().astype(int)
            xyxy = r.boxes.xyxy.cpu().numpy()
            confs = r.boxes.conf.cpu().numpy()
            for tid, box, c in zip(ids, xyxy, confs):
                tracks[tid]["frames"].append(frame_i)
                tracks[tid]["boxes"].append(box.astype(np.float32))
                tracks[tid]["confs"].append(float(c))
        frame_i += 1
        now = time.time()
        if now - last_log > 5.0:
            last_log = now
            pct = (100.0 * frame_i / total) if total else 0.0
            print(
                f"[track] frame {frame_i}/{total or '?'} ({pct:.1f}%)  "
                f"ids={len(tracks)}  elapsed={now - t0:.0f}s",
                flush=True,
            )

    if total <= 0:
        total = frame_i
    print(f"[track] done frames={frame_i} unique_ids={len(tracks)} in {time.time() - t0:.1f}s", flush=True)
    return dict(tracks), fps, width, height, total


def _iou_xyxy(a: np.ndarray, b: np.ndarray) -> float:
    x1 = max(float(a[0]), float(b[0]))
    y1 = max(float(a[1]), float(b[1]))
    x2 = min(float(a[2]), float(b[2]))
    y2 = min(float(a[3]), float(b[3]))
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if inter <= 0:
        return 0.0
    area_a = max(0.0, float(a[2] - a[0])) * max(0.0, float(a[3] - a[1]))
    area_b = max(0.0, float(b[2] - b[0])) * max(0.0, float(b[3] - b[1]))
    union = area_a + area_b - inter
    return float(inter / union) if union > 0 else 0.0


def mean_track_iou(a: dict, b: dict, max_samples: int = 80) -> float:
    """Mean IoU on co-occurring frames (sampled)."""
    fa = {int(f): box for f, box in zip(a["frames"], a["boxes"])}
    fb = {int(f): box for f, box in zip(b["frames"], b["boxes"])}
    common = sorted(set(fa) & set(fb))
    if len(common) < 5:
        return 0.0
    if len(common) > max_samples:
        idx = np.linspace(0, len(common) - 1, max_samples)
        common = [common[int(round(i))] for i in idx]
    ious = [_iou_xyxy(fa[f], fb[f]) for f in common]
    return float(np.mean(ious))


def dedup_overlapping_tracks(
    kept: list[tuple[int, dict]],
    iou_thresh: float = 0.55,
) -> list[tuple[int, dict]]:
    """Drop shorter tracks that heavily overlap a longer one (same person, split IDs)."""
    if iou_thresh <= 0 or len(kept) < 2:
        return kept
    # already sorted by duration desc
    survivors: list[tuple[int, dict]] = []
    for tid, data in kept:
        drop = False
        for _, other in survivors:
            if mean_track_iou(data, other) >= iou_thresh:
                drop = True
                break
        if not drop:
            survivors.append((tid, data))
    return survivors


def filter_tracks(
    tracks: dict[int, dict],
    fps: float,
    frame_area: float,
    min_sec: float,
    min_area_frac: float,
    dedup_iou: float = 0.55,
) -> list[tuple[int, dict]]:
    kept = []
    min_frames = max(1, int(round(min_sec * fps)))
    for tid, data in tracks.items():
        n = len(data["frames"])
        if n < min_frames:
            continue
        boxes = np.stack(data["boxes"], axis=0)
        areas = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
        mean_frac = float(areas.mean() / max(frame_area, 1.0))
        if mean_frac < min_area_frac:
            continue
        span = (data["frames"][-1] - data["frames"][0] + 1) / fps
        data = {
            **data,
            "n_obs": n,
            "duration_obs_sec": n / fps,
            "span_sec": span,
            "mean_area_frac": mean_frac,
            "mean_conf": float(np.mean(data["confs"])),
        }
        kept.append((tid, data))
    kept.sort(key=lambda x: x[1]["duration_obs_sec"], reverse=True)
    before = len(kept)
    kept = dedup_overlapping_tracks(kept, iou_thresh=dedup_iou)
    if len(kept) < before:
        print(f"[filter] dedup removed {before - len(kept)} overlapping tracks", flush=True)
    return kept


def export_track_clip(
    video_path: Path,
    out_path: Path,
    frames: list[int],
    boxes: list[np.ndarray],
    fps: float,
    width: int,
    height: int,
    pad: float,
    out_size: int,
    ema_alpha: float = 0.25,
    crop_mode: str = "square",
) -> dict:
    """Write a cropped per-person clip. Missing frames inside the span are skipped.

    crop_mode:
      - square: legacy square pad around each box, resized to out_size^2
      - max_box: fixed crop = max YOLO w/h over the track, centered on smoothed box
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    frame_to_box = {int(f): b for f, b in zip(frames, boxes)}
    f0, f1 = int(frames[0]), int(frames[-1])

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open {video_path}")

    tmp = out_path.with_suffix(".tmp.mp4")
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")

    crop_w = crop_h = out_size
    if crop_mode == "max_box":
        crop_w, crop_h = max_box_size(boxes, pad=pad)
        writer = cv2.VideoWriter(str(tmp), fourcc, fps, (crop_w, crop_h))
    else:
        writer = cv2.VideoWriter(str(tmp), fourcc, fps, (out_size, out_size))
    if not writer.isOpened():
        raise RuntimeError("VideoWriter failed")

    smooth = None
    written = 0
    cap.set(cv2.CAP_PROP_POS_FRAMES, f0)
    for fi in range(f0, f1 + 1):
        ok, frame = cap.read()
        if not ok:
            break
        box = frame_to_box.get(fi)
        if box is None:
            continue
        smooth = ema_update(smooth, box, ema_alpha)
        if crop_mode == "max_box":
            crop = crop_fixed_size(frame, smooth, crop_w, crop_h)
        else:
            x1, y1, x2, y2 = pad_box(smooth, width, height, pad)
            crop = frame[y1:y2, x1:x2]
            if crop.size == 0:
                continue
            crop = cv2.resize(crop, (out_size, out_size), interpolation=cv2.INTER_AREA)
        if crop.size == 0:
            continue
        writer.write(crop)
        written += 1

    writer.release()
    cap.release()

    import shutil
    import subprocess

    ff = shutil.which("ffmpeg")
    if ff and written > 0:
        cmd = [
            ff,
            "-y",
            "-i",
            str(tmp),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(out_path),
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        tmp.unlink(missing_ok=True)
    else:
        tmp.replace(out_path)

    info = {
        "n_frames_written": written,
        "start_frame": f0,
        "end_frame": f1,
        "start_sec": round(f0 / fps, 3),
        "end_sec": round((f1 + 1) / fps, 3),
        "duration_sec": round(written / fps, 3),
        "crop_mode": crop_mode,
    }
    if crop_mode == "max_box":
        info["crop_w"] = crop_w
        info["crop_h"] = crop_h
    return info


def save_preview(
    video_path: Path,
    frame_i: int,
    box: np.ndarray,
    out_jpg: Path,
    pad: float,
    crop_mode: str = "square",
    crop_w: int | None = None,
    crop_h: int | None = None,
) -> None:
    cap = cv2.VideoCapture(str(video_path))
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_i)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        return
    h, w = frame.shape[:2]
    if crop_mode == "max_box" and crop_w and crop_h:
        crop = crop_fixed_size(frame, box, crop_w, crop_h)
    else:
        x1, y1, x2, y2 = pad_box(box, w, h, pad)
        crop = frame[y1:y2, x1:x2]
    if crop.size:
        out_jpg.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(out_jpg), crop)


def main() -> None:
    ap = argparse.ArgumentParser(description="YOLO track → per-person folders")
    ap.add_argument("--video", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=None, help="Output root (default data/input/people/<stem>)")
    ap.add_argument("--model", default="yolo11n.pt")
    ap.add_argument("--device", default="0")
    ap.add_argument("--conf", type=float, default=0.35)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--min-sec", type=float, default=25.0, dest="min_sec")
    ap.add_argument("--min-area-frac", type=float, default=0.015, dest="min_area_frac")
    ap.add_argument("--pad", type=float, default=0.35)
    ap.add_argument("--out-size", type=int, default=512, dest="out_size")
    ap.add_argument(
        "--crop-mode",
        choices=("square", "max_box"),
        default="square",
        help="square=legacy padded square; max_box=fixed max YOLO w/h over track",
    )
    ap.add_argument(
        "--dedup-iou",
        type=float,
        default=0.55,
        dest="dedup_iou",
        help="drop shorter tracks overlapping a longer one above this IoU (0=off)",
    )
    ap.add_argument("--max-people", type=int, default=0, help="0 = keep all that pass filters")
    ap.add_argument(
        "--clean-out",
        action="store_true",
        help="delete existing person_* folders in --out before export",
    )
    args = ap.parse_args()

    video = args.video if args.video.is_absolute() else (LAB_ROOT / args.video)
    if not video.exists():
        # fuzzy match under data/input
        matches = list((LAB_ROOT / "data" / "input").glob("*" + video.name + "*")) if video.name else []
        if not matches:
            matches = [p for p in (LAB_ROOT / "data" / "input").glob("*.mp4") if "burn" in p.name.lower()]
        if len(matches) == 1:
            video = matches[0]
        else:
            print(f"Video not found: {args.video}", file=sys.stderr)
            sys.exit(1)

    slug = stem_slug(video)
    out_root = args.out
    if out_root is None:
        out_root = LAB_ROOT / "data" / "input" / "people" / slug
    elif not out_root.is_absolute():
        out_root = LAB_ROOT / out_root
    out_root.mkdir(parents=True, exist_ok=True)
    if args.clean_out:
        import shutil

        for old in out_root.glob("person_*"):
            if old.is_dir():
                shutil.rmtree(old)
        print(f"[clean] removed old person_* under {out_root}", flush=True)

    pad_eff = args.pad if args.crop_mode == "square" else args.pad
    print(f"Video: {video}")
    print(f"Out:   {out_root}")
    print(
        f"Model: {args.model} device={args.device} min_sec={args.min_sec} "
        f"crop_mode={args.crop_mode} pad={pad_eff} dedup_iou={args.dedup_iou}",
        flush=True,
    )

    tracks, fps, width, height, total = track_people(
        video, args.model, args.device, args.conf, args.imgsz
    )
    raw_path = out_root / "tracks_raw.json"
    # compact dump for debugging
    raw_dump = {
        str(tid): {
            "n": len(d["frames"]),
            "start": int(d["frames"][0]) if d["frames"] else None,
            "end": int(d["frames"][-1]) if d["frames"] else None,
        }
        for tid, d in tracks.items()
    }
    raw_path.write_text(json.dumps(raw_dump, indent=2), encoding="utf-8")

    kept = filter_tracks(
        tracks,
        fps=fps,
        frame_area=float(width * height),
        min_sec=args.min_sec,
        min_area_frac=args.min_area_frac,
        dedup_iou=args.dedup_iou,
    )
    if args.max_people > 0:
        kept = kept[: args.max_people]

    print(f"[filter] kept {len(kept)} / {len(tracks)} tracks", flush=True)

    people = []
    for i, (tid, data) in enumerate(kept):
        person_id = f"person_{i:03d}"
        person_dir = out_root / person_id
        person_dir.mkdir(parents=True, exist_ok=True)
        clip_path = person_dir / "clip.mp4"
        print(
            f"[export] {person_id} track_id={tid} "
            f"obs={data['duration_obs_sec']:.1f}s span={data['span_sec']:.1f}s "
            f"area={data['mean_area_frac']:.3f}",
            flush=True,
        )
        export_info = export_track_clip(
            video_path=video,
            out_path=clip_path,
            frames=data["frames"],
            boxes=data["boxes"],
            fps=fps,
            width=width,
            height=height,
            pad=pad_eff,
            out_size=args.out_size,
            crop_mode=args.crop_mode,
        )
        mid = data["frames"][len(data["frames"]) // 2]
        mid_box = data["boxes"][len(data["boxes"]) // 2]
        save_preview(
            video,
            mid,
            mid_box,
            person_dir / "preview.jpg",
            pad_eff,
            crop_mode=args.crop_mode,
            crop_w=export_info.get("crop_w"),
            crop_h=export_info.get("crop_h"),
        )

        meta = {
            "person_id": person_id,
            "source_track_id": int(tid),
            "source_video": str(video.as_posix()),
            "fps": fps,
            "mean_conf": data["mean_conf"],
            "mean_area_frac": data["mean_area_frac"],
            "n_observations": data["n_obs"],
            **export_info,
            "clip": "clip.mp4",
        }
        (person_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        people.append(meta)

    manifest = {
        "source": str(video.as_posix()),
        "source_name": video.name,
        "slug": slug,
        "fps": fps,
        "width": width,
        "height": height,
        "n_frames": total,
        "n_raw_tracks": len(tracks),
        "n_people": len(people),
        "min_sec": args.min_sec,
        "min_area_frac": args.min_area_frac,
        "model": args.model,
        "people": people,
    }
    (out_root / "people_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Done. {len(people)} people → {out_root}")
    for p in people:
        print(
            f"  {p['person_id']}: {p['duration_sec']:.1f}s "
            f"({p['start_sec']:.1f}-{p['end_sec']:.1f}s) track={p['source_track_id']}"
        )


if __name__ == "__main__":
    main()
