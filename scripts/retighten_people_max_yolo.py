#!/usr/bin/env python3
"""Re-crop existing person clips to max YOLO box size (fixed w/h over the clip).

For each clip.mp4:
  1) detect person boxes (primary = most central)
  2) max_w / max_h across detections
  3) rewrite clip with that fixed crop centered on smoothed box
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO

LAB_ROOT = Path(__file__).resolve().parents[1]
PEOPLE_ROOT = LAB_ROOT / "data" / "input" / "people"

# reuse helpers
sys.path.insert(0, str(LAB_ROOT / "scripts"))
from split_people import crop_fixed_size, ema_update, even_size  # noqa: E402


def pick_primary(boxes: np.ndarray, w: int, h: int) -> int:
    cx, cy = w * 0.5, h * 0.5
    centers = 0.5 * (boxes[:, 0:2] + boxes[:, 2:4])
    areas = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    dist = np.linalg.norm(centers - np.array([cx, cy]), axis=1)
    score = dist / max(w, h) - 0.15 * (areas / (w * h))
    return int(np.argmin(score))


def collect_primary_boxes(
    model: YOLO,
    clip: Path,
    conf: float,
    imgsz: int,
    stride: int,
    device: str,
) -> tuple[dict[int, np.ndarray], int, int, float]:
    cap = cv2.VideoCapture(str(clip))
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 24.0)
    cap.release()

    boxes: dict[int, np.ndarray] = {}
    results = model.predict(
        source=str(clip),
        stream=True,
        classes=[0],
        conf=conf,
        imgsz=imgsz,
        verbose=False,
        device=device,
        vid_stride=stride,
    )
    # vid_stride skips frames; map result index -> approx source frame
    for i, r in enumerate(results):
        fi = i * stride
        if r.boxes is not None and len(r.boxes):
            xyxy = r.boxes.xyxy.cpu().numpy()
            pi = pick_primary(xyxy, w, h)
            boxes[fi] = xyxy[pi].astype(np.float32)
    return boxes, w, h, fps


def interpolate_boxes(boxes: dict[int, np.ndarray], n_frames: int) -> dict[int, np.ndarray]:
    if not boxes:
        return {}
    keys = sorted(boxes.keys())
    out: dict[int, np.ndarray] = {}
    for fi in range(n_frames):
        if fi in boxes:
            out[fi] = boxes[fi]
            continue
        # nearest neighbor from sampled detections
        j = min(keys, key=lambda k: abs(k - fi))
        out[fi] = boxes[j]
    return out


def retighten_clip(
    model: YOLO,
    clip: Path,
    conf: float,
    imgsz: int,
    stride: int,
    pad: float,
    device: str,
) -> dict:
    cap = cv2.VideoCapture(str(clip))
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    cap.release()

    sampled, w, h, fps = collect_primary_boxes(
        model, clip, conf, imgsz, stride, device=device
    )
    if len(sampled) < 3:
        return {"ok": False, "clip": str(clip), "error": "too_few_detections"}

    arr = np.stack(list(sampled.values()), axis=0)
    max_w = even_size(int(np.ceil(float((arr[:, 2] - arr[:, 0]).max()) * (1.0 + pad))))
    max_h = even_size(int(np.ceil(float((arr[:, 3] - arr[:, 1]).max()) * (1.0 + pad))))
    max_w = min(max_w, even_size(w))
    max_h = min(max_h, even_size(h))

    # already tight enough?
    if max_w >= w - 2 and max_h >= h - 2:
        return {
            "ok": True,
            "clip": str(clip),
            "skipped": True,
            "crop_w": max_w,
            "crop_h": max_h,
            "src_w": w,
            "src_h": h,
        }

    frame_boxes = interpolate_boxes(sampled, n_frames)
    tmp = clip.with_suffix(".maxbox_tmp.mp4")
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(tmp), fourcc, fps, (max_w, max_h))
    if not writer.isOpened():
        return {"ok": False, "clip": str(clip), "error": "writer_failed"}

    cap = cv2.VideoCapture(str(clip))
    smooth = None
    written = 0
    fi = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        box = frame_boxes.get(fi)
        if box is None:
            fi += 1
            continue
        smooth = ema_update(smooth, box, 0.35)
        crop = crop_fixed_size(frame, smooth, max_w, max_h)
        writer.write(crop)
        written += 1
        fi += 1
    writer.release()
    cap.release()

    if written == 0:
        tmp.unlink(missing_ok=True)
        return {"ok": False, "clip": str(clip), "error": "no_frames_written"}

    ff = shutil.which("ffmpeg")
    if ff:
        out_tmp = clip.with_suffix(".maxbox_h264.mp4")
        cmd = [
            ff, "-y", "-i", str(tmp),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-an", str(out_tmp),
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        tmp.unlink(missing_ok=True)
        out_tmp.replace(clip)
    else:
        tmp.replace(clip)

    meta_path = clip.parent / "meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["crop_mode"] = "max_box"
        meta["crop_w"] = max_w
        meta["crop_h"] = max_h
        meta["max_box_from"] = "retighten_people_max_yolo"
        meta.pop("side_crop_total_pct", None)
        meta.pop("side_crop_each_pct", None)
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    # refresh preview from mid frame
    mid = n_frames // 2
    cap = cv2.VideoCapture(str(clip))
    cap.set(cv2.CAP_PROP_POS_FRAMES, mid)
    ok, frame = cap.read()
    cap.release()
    if ok:
        cv2.imwrite(str(clip.parent / "preview.jpg"), frame)

    return {
        "ok": True,
        "clip": str(clip.relative_to(PEOPLE_ROOT).as_posix()),
        "skipped": False,
        "crop_w": max_w,
        "crop_h": max_h,
        "src_w": w,
        "src_h": h,
        "n_det": len(sampled),
        "written": written,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--people-root", type=Path, default=PEOPLE_ROOT)
    ap.add_argument("--model", default=str(LAB_ROOT / "yolo11n.pt"))
    ap.add_argument("--device", default="0")
    ap.add_argument("--conf", type=float, default=0.35)
    ap.add_argument("--imgsz", type=int, default=320)
    ap.add_argument("--stride", type=int, default=3, help="detect every Nth frame")
    ap.add_argument("--pad", type=float, default=0.0, help="extra fraction on max w/h")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    clips = sorted(args.people_root.rglob("clip.mp4"))
    clips = [c for c in clips if ".tmp" not in c.name and ".maxbox" not in c.name]
    if args.limit > 0:
        clips = clips[: args.limit]

    print(
        f"[maxbox] clips={len(clips)} stride={args.stride} pad={args.pad} imgsz={args.imgsz}",
        flush=True,
    )
    model = YOLO(args.model)
    # warm up on device
    model.predict(np.zeros((64, 64, 3), dtype=np.uint8), verbose=False, device=args.device)

    rows = []
    ok = fail = skip = 0
    for i, clip in enumerate(clips, 1):
        # force device via predict kwargs already; set model device
        try:
            row = retighten_clip(
                model,
                clip,
                conf=args.conf,
                imgsz=args.imgsz,
                stride=args.stride,
                pad=args.pad,
                device=args.device,
            )
        except Exception as e:
            row = {"ok": False, "clip": str(clip), "error": str(e)}
        rows.append(row)
        if not row.get("ok"):
            fail += 1
            print(f"[FAIL] {clip.relative_to(args.people_root)}: {row.get('error')}", flush=True)
        elif row.get("skipped"):
            skip += 1
        else:
            ok += 1
            print(
                f"[ok] {row['clip']}: {row['src_w']}x{row['src_h']} -> "
                f"{row['crop_w']}x{row['crop_h']} (dets={row['n_det']})",
                flush=True,
            )
        if i % 10 == 0 or i == len(clips):
            print(f"[maxbox] {i}/{len(clips)} ok={ok} skip={skip} fail={fail}", flush=True)

    out = args.people_root / "max_box_retighten_report.json"
    out.write_text(json.dumps({"rows": rows, "ok": ok, "skip": skip, "fail": fail}, indent=2), encoding="utf-8")
    print(f"[maxbox] done ok={ok} skip={skip} fail={fail} -> {out}", flush=True)
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
