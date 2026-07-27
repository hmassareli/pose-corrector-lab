#!/usr/bin/env python3
"""Run GVHMR teacher on every video in data/input (or --input).

This wrapper:
  1) Invokes upstream GVHMR demo per video (when installed)
  2) Converts outputs into lab-canonical joints3d.npy + meta.json
  3) Optionally exports viewer JSON

If GVHMR is not fully installed yet, use --dry-run to scaffold output folders.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import yaml

LAB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB_ROOT / "src"))

from pose_lab.io import clip_id_from_path, list_videos, save_teacher_clip, save_viewer_payload
from pose_lab.skeleton import LAB_BONES, LAB_JOINTS, smpl24_to_lab


def load_cfg(path: Path) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def probe_video_meta(video: Path) -> dict:
    """Best-effort fps / frame count via OpenCV if available."""
    meta = {"path": str(video), "fps": None, "n_frames": None, "width": None, "height": None}
    try:
        import cv2

        cap = cv2.VideoCapture(str(video))
        meta["fps"] = float(cap.get(cv2.CAP_PROP_FPS) or 0) or None
        meta["n_frames"] = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0) or None
        meta["width"] = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0) or None
        meta["height"] = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0) or None
        cap.release()
    except Exception as e:
        meta["probe_error"] = str(e)
    return meta


def find_gvhmr_demo(gvhmr_root: Path) -> Path | None:
    candidates = [
        gvhmr_root / "tools" / "demo" / "demo.py",
        gvhmr_root / "tools" / "demo.py",
        gvhmr_root / "demo.py",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def run_gvhmr_one(
    python_exe: str,
    demo_py: Path,
    video: Path,
    work_dir: Path,
    static_camera: bool,
    extra_args: list[str],
) -> Path:
    """Call upstream demo; return directory where raw outputs landed."""
    work_dir.mkdir(parents=True, exist_ok=True)
    cmd = [python_exe, str(demo_py), "-f", str(video)]
    if static_camera:
        cmd.append("-s")
    # Many demos write next to video or under outputs/; we pass output if supported
    cmd.extend(extra_args)
    env = os.environ.copy()
    print("+", " ".join(cmd))
    subprocess.run(cmd, cwd=str(demo_py.parents[1] if (demo_py.parent.name == "demo") else demo_py.parent), check=True, env=env)
    return work_dir


def try_load_smpl_joints(raw_dir: Path) -> np.ndarray | None:
    """Search common GVHMR dump patterns for (T,24,3) or (T,J,3) joints."""
    patterns = [
        "**/joints.npy",
        "**/joints3d.npy",
        "**/*hmr4d*.pt",
        "**/*.npz",
        "**/*.npzz",
        "**/*.pkl",
    ]
    # Prefer explicit npy
    for pat in ("**/joints.npy", "**/joints3d.npy", "**/*joints*.npy"):
        hits = list(raw_dir.glob(pat))
        if hits:
            arr = np.load(hits[0])
            return np.asarray(arr)

    # Torch checkpoints / results
    try:
        import torch
    except ImportError:
        torch = None

    if torch is not None:
        for hit in list(raw_dir.glob("**/*.pt")) + list(raw_dir.glob("**/*.pth")):
            try:
                obj = torch.load(hit, map_location="cpu")
            except Exception:
                continue
            if isinstance(obj, dict):
                for key in ("joints", "pred_joints", "joints3d", "pred_smpl_params"):
                    if key in obj:
                        val = obj[key]
                        if hasattr(val, "numpy"):
                            val = val.numpy()
                        if key == "pred_smpl_params":
                            continue
                        return np.asarray(val)
    return None


def convert_and_save(
    video: Path,
    out_root: Path,
    joints_smpl: np.ndarray | None,
    static_camera: bool,
    video_meta: dict,
    dry_run: bool,
) -> Path:
    clip = clip_id_from_path(video)
    out_dir = out_root / clip
    out_dir.mkdir(parents=True, exist_ok=True)

    # Keep a copy/link reference to source video for the viewer
    media_link = out_dir / f"source{video.suffix.lower()}"
    if not media_link.exists():
        try:
            os.link(video, media_link)
        except OSError:
            shutil.copy2(video, media_link)

    meta = {
        "clip_id": clip,
        "source_video": str(video.resolve()),
        "teacher": "GVHMR",
        "static_camera": static_camera,
        "created_unix": time.time(),
        "video": video_meta,
        "qa": {"status": "unchecked"},
        "dry_run": dry_run,
    }

    if dry_run or joints_smpl is None:
        # Placeholder empty teacher — allows folder wiring + viewer tests
        n = video_meta.get("n_frames") or 30
        joints = np.zeros((n, len(LAB_JOINTS), 3), dtype=np.float32)
        # Tiny T-pose-ish for viewer sanity
        joints[:, 8] = [-0.2, 0.4, 0]
        joints[:, 9] = [0.2, 0.4, 0]
        joints[:, 10] = [-0.35, 0.15, 0]
        joints[:, 11] = [0.35, 0.15, 0]
        joints[:, 12] = [-0.45, -0.05, 0]
        joints[:, 13] = [0.45, -0.05, 0]
        joints[:, 14] = [0, 0.55, 0]
        joints[:, 15] = [0, 0.7, 0]
        save_teacher_clip(out_dir, joints, meta)
        print(f"[dry/placeholder] {clip} → {out_dir}")
    else:
        j = np.asarray(joints_smpl)
        if j.ndim != 3:
            raise ValueError(f"Expected (T,J,3), got {j.shape}")
        if j.shape[1] == 24:
            lab = smpl24_to_lab(j)
            smpl_raw = j
        elif j.shape[1] == len(LAB_JOINTS):
            lab = j
            smpl_raw = None
        else:
            # take first 24 if longer (SMPL-X extras)
            lab = smpl24_to_lab(j[:, :24])
            smpl_raw = j[:, :24]
        meta["n_frames_teacher"] = int(lab.shape[0])
        save_teacher_clip(out_dir, lab, meta, joints3d_smpl=smpl_raw)
        print(f"[ok] {clip} T={lab.shape[0]} → {out_dir}")

    # Viewer payload (relative video path served by serve_viewer)
    data = np.load(out_dir / "joints3d.npy")
    fps = video_meta.get("fps") or 30.0
    save_viewer_payload(
        out_dir / "viewer_payload.json",
        video_url=f"/media/{clip}/source{video.suffix.lower()}",
        joints=data,
        fps=float(fps),
        bones=LAB_BONES,
        joint_names=LAB_JOINTS,
        title=f"GVHMR — {clip}",
    )
    return out_dir


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", type=Path, default=LAB_ROOT / "configs" / "gvhmr_local.yaml")
    ap.add_argument("--input", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--static-camera", action="store_true", default=None)
    ap.add_argument("--no-static-camera", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="Scaffold outputs without calling GVHMR")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    cfg = load_cfg(args.config)
    input_dir = Path(args.input or cfg.get("input_dir") or "data/input")
    if not input_dir.is_absolute():
        input_dir = LAB_ROOT / input_dir
    out_dir = Path(args.out or cfg.get("output_dir") or "data/teacher")
    if not out_dir.is_absolute():
        out_dir = LAB_ROOT / out_dir

    static = cfg.get("static_camera_default", True)
    if args.static_camera:
        static = True
    if args.no_static_camera:
        static = False

    videos = list_videos(input_dir)
    if args.limit:
        videos = videos[: args.limit]
    if not videos:
        print(f"No videos in {input_dir}. Put files there and re-run.")
        print(f"Accepted: {cfg.get('video_extensions', ['.mp4'])}")
        # ensure folders exist
        input_dir.mkdir(parents=True, exist_ok=True)
        out_dir.mkdir(parents=True, exist_ok=True)
        (input_dir / ".gitkeep").touch()
        return

    gvhmr_root = Path(cfg.get("gvhmr_root") or LAB_ROOT / "external" / "GVHMR")
    if not gvhmr_root.is_absolute():
        gvhmr_root = LAB_ROOT / gvhmr_root
    python_exe = cfg.get("python") or sys.executable
    demo = find_gvhmr_demo(gvhmr_root) if not args.dry_run else None
    extra = list(cfg.get("extra_args") or [])

    if not args.dry_run and demo is None:
        print(f"GVHMR demo not found under {gvhmr_root}.")
        print("Run: python scripts/setup_gvhmr.py")
        print("Or pass --dry-run to scaffold placeholder teacher outputs.")
        sys.exit(2)

    raw_dump = out_dir / "_gvhmr_raw"
    raw_dump.mkdir(parents=True, exist_ok=True)

    for video in videos:
        print(f"\n=== {video.name} ===")
        vmeta = probe_video_meta(video)
        joints = None
        if not args.dry_run:
            work = raw_dump / clip_id_from_path(video)
            work.mkdir(parents=True, exist_ok=True)
            # Copy video into work for demos that write alongside input
            local_vid = work / video.name
            if not local_vid.exists():
                shutil.copy2(video, local_vid)
            try:
                run_gvhmr_one(python_exe, demo, local_vid, work, static, extra)
                joints = try_load_smpl_joints(work)
                if joints is None:
                    # Also search GVHMR outputs folder
                    joints = try_load_smpl_joints(gvhmr_root / "outputs")
                    if joints is None:
                        print("WARNING: could not auto-parse GVHMR joints; writing placeholder.")
                        print(f"Inspect raw dumps in {work} and teach convert path in run_teacher.py")
            except subprocess.CalledProcessError as e:
                print(f"GVHMR failed for {video.name}: {e}")
                continue
        convert_and_save(video, out_dir, joints, static, vmeta, dry_run=args.dry_run or joints is None)

    print("\nDone. Visualize with:")
    print("  python scripts/serve_viewer.py --clip <clip_id>")


if __name__ == "__main__":
    main()
