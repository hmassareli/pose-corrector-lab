#!/usr/bin/env python3
"""Detect hard cuts / camera switches and split a video into continuous shots.

Uses ffmpeg `scene` score (reliable for hard cuts). Falls back to OpenCV
histogram/frame diffs if ffmpeg is unavailable.

Usage:
  python scripts/split_shots.py --video data/input/shadow_clip_45s.mp4
  python scripts/split_shots.py --video data/input/shadow_clip_45s.mp4 --threshold 0.35 --min-len 1.0

Outputs under data/input/shots/<video_stem>/:
  shot_000.mp4, shot_001.mp4, ...
  shots_manifest.json
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]


def _ffmpeg_bin() -> str | None:
    return shutil.which("ffmpeg")


def _ffprobe_meta(video_path: Path) -> tuple[float, int]:
    ffprobe = shutil.which("ffprobe") or "ffprobe"
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=avg_frame_rate,nb_frames,duration",
        "-of",
        "json",
        str(video_path),
    ]
    raw = subprocess.check_output(cmd, text=True)
    data = json.loads(raw)
    stream = data["streams"][0]
    num, den = stream.get("avg_frame_rate", "30/1").split("/")
    fps = float(num) / max(float(den), 1e-9)
    n_frames = int(stream["nb_frames"]) if stream.get("nb_frames") not in (None, "N/A", "0") else 0
    if n_frames <= 0:
        dur = float(stream.get("duration") or 0)
        n_frames = int(round(dur * fps))
    return fps, n_frames


def detect_cuts_ffmpeg(
    video_path: Path,
    threshold: float,
    min_scene_len_s: float,
    fps: float,
    total: int,
) -> list[tuple[int, int]]:
    """Return (start_frame, end_frame_exclusive) shots from ffmpeg scene scores."""
    ff = _ffmpeg_bin()
    assert ff
    cmd = [
        ff,
        "-hide_banner",
        "-i",
        str(video_path),
        "-filter:v",
        f"select='gt(scene,{threshold})',showinfo",
        "-an",
        "-f",
        "null",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    stderr = proc.stderr or ""
    times: list[float] = []
    for m in re.finditer(r"pts_time:(?P<t>[0-9.]+)", stderr):
        times.append(float(m.group("t")))

    min_len = max(1, int(round(min_scene_len_s * fps)))
    cut_frames: list[int] = []
    last = 0
    for t in times:
        f = int(round(t * fps))
        f = max(0, min(total - 1, f))
        if f - last >= min_len:
            cut_frames.append(f)
            last = f

    starts = [0] + cut_frames
    ends = cut_frames + [total]
    return [(s, e) for s, e in zip(starts, ends) if e > s]


def detect_cuts_opencv(
    video_path: Path,
    threshold: float,
    min_scene_len_s: float,
    fps: float,
    total: int,
) -> list[tuple[int, int]]:
    """Fallback: mean abs frame diff (threshold ~0.25–0.45 on [0,1] gray)."""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")
    min_len = max(1, int(round(min_scene_len_s * fps)))
    diff_thr = threshold if threshold < 1.5 else threshold / 100.0

    cuts_after: list[int] = []
    prev = None
    idx = 0
    last_cut = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        small = cv2.resize(frame, (160, 90), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
        if prev is not None:
            score = float(np.mean(np.abs(gray - prev)))
            if score >= diff_thr and (idx - last_cut) >= min_len:
                cuts_after.append(idx)
                last_cut = idx
        prev = gray
        idx += 1
    cap.release()
    if total <= 0:
        total = idx
    starts = [0] + cuts_after
    ends = cuts_after + [total]
    return [(s, e) for s, e in zip(starts, ends) if e > s]


def export_shot(
    video_path: Path,
    out_path: Path,
    start_f: int,
    end_f: int,
    fps: float,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    start_t = start_f / fps
    duration = max((end_f - start_f) / fps, 1.0 / fps)
    ff = _ffmpeg_bin() or "ffmpeg"
    cmd = [
        ff,
        "-y",
        "-ss",
        f"{start_t:.3f}",
        "-i",
        str(video_path),
        "-t",
        f"{duration:.3f}",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-an",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def split_video(
    video_path: Path,
    out_dir: Path,
    threshold: float,
    min_scene_len_s: float,
) -> dict:
    fps, total = _ffprobe_meta(video_path)
    method = "ffmpeg_scene"
    if _ffmpeg_bin():
        shots = detect_cuts_ffmpeg(video_path, threshold, min_scene_len_s, fps, total)
    else:
        method = "opencv_mad"
        shots = detect_cuts_opencv(video_path, threshold, min_scene_len_s, fps, total)

    out_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    for i, (sf, ef) in enumerate(shots):
        name = f"shot_{i:03d}.mp4"
        out_path = out_dir / name
        export_shot(video_path, out_path, sf, ef, fps)
        entries.append(
            {
                "id": f"shot_{i:03d}",
                "file": name,
                "start_frame": int(sf),
                "end_frame": int(ef),
                "n_frames": int(ef - sf),
                "start_sec": round(sf / fps, 3),
                "end_sec": round(ef / fps, 3),
                "duration_sec": round((ef - sf) / fps, 3),
            }
        )

    manifest = {
        "source": str(video_path.as_posix()),
        "source_name": video_path.name,
        "fps": fps,
        "n_frames": total,
        "threshold": threshold,
        "min_scene_len_s": min_scene_len_s,
        "detector": method,
        "n_shots": len(entries),
        "shots": entries,
    }
    (out_dir / "shots_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    ap = argparse.ArgumentParser(description="Split video into continuous shots at hard cuts")
    ap.add_argument(
        "--video",
        type=Path,
        default=LAB_ROOT / "data" / "input" / "shadow_clip_45s.mp4",
        help="Input video path",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output dir (default: data/input/shots/<stem>/)",
    )
    ap.add_argument(
        "--threshold",
        type=float,
        default=0.35,
        help="ffmpeg scene score threshold (lower = more cuts; try 0.3–0.45)",
    )
    ap.add_argument(
        "--min-len",
        type=float,
        default=1.0,
        dest="min_len",
        help="Minimum shot length in seconds",
    )
    args = ap.parse_args()

    video = args.video if args.video.is_absolute() else (LAB_ROOT / args.video)
    if not video.exists():
        print(f"Video not found: {video}", file=sys.stderr)
        sys.exit(1)

    out_dir = args.out
    if out_dir is None:
        out_dir = LAB_ROOT / "data" / "input" / "shots" / video.stem
    elif not out_dir.is_absolute():
        out_dir = LAB_ROOT / out_dir

    print(f"Detecting cuts in {video.name} (threshold={args.threshold}, min_len={args.min_len}s) ...")
    manifest = split_video(video, out_dir, threshold=args.threshold, min_scene_len_s=args.min_len)
    print(
        f"Found {manifest['n_shots']} shot(s) via {manifest['detector']}  "
        f"fps={manifest['fps']:.2f}  frames={manifest['n_frames']}"
    )
    for s in manifest["shots"]:
        print(
            f"  {s['id']}: {s['start_sec']:.2f}s -> {s['end_sec']:.2f}s "
            f"({s['duration_sec']:.2f}s, {s['n_frames']}f) -> {s['file']}"
        )
    print(f"Out: {out_dir}")
    print(f"Manifest: {out_dir / 'shots_manifest.json'}")


if __name__ == "__main__":
    main()
