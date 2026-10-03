#!/usr/bin/env python3
"""Batch MediaPipe Pose Landmarker on person clips → data/mediapipe/<clip_id>/."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import urllib.request
from pathlib import Path

import cv2
import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB_ROOT / "src"))

from pose_lab.io import save_viewer_payload  # noqa: E402
from pose_lab.skeleton import (  # noqa: E402
    JOINT_TO_IDX,
    LAB_BONES,
    LAB_JOINTS,
    MEDIAPIPE_TO_LAB,
    mediapipe_array_to_lab,
)

MODEL_URLS = {
    0: (
        "pose_landmarker_lite.task",
        "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
        "pose_landmarker_lite/float16/1/pose_landmarker_lite.task",
    ),
    1: (
        "pose_landmarker_full.task",
        "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
        "pose_landmarker_full/float16/1/pose_landmarker_full.task",
    ),
    2: (
        "pose_landmarker_heavy.task",
        "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
        "pose_landmarker_heavy/float16/1/pose_landmarker_heavy.task",
    ),
}


def ensure_model(complexity: int) -> Path:
    name, url = MODEL_URLS[complexity]
    path = LAB_ROOT / "data" / "models" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 1000:
        return path
    print(f"[mediapipe] downloading {name} ...", flush=True)
    urllib.request.urlretrieve(url, path)
    return path


def discover_people_clips(people_root: Path) -> list[tuple[str, Path]]:
    clips = []
    for p in sorted(people_root.rglob("clip.mp4")):
        if any(x in p.name for x in (".tmp", ".maxbox", ".crop")):
            continue
        rel = p.relative_to(people_root).as_posix()
        parts = Path(rel).parts
        if parts[-1] != "clip.mp4":
            continue
        clip_id = "__".join(parts[:-1])
        clips.append((clip_id, p))
    return clips


def _lm_xyz(lms) -> np.ndarray:
    return np.array([[lm.x, lm.y, lm.z] for lm in lms], dtype=np.float64)


def _lm_vis(lms) -> np.ndarray:
    # tasks API: visibility may be absent; use presence if needed
    out = []
    for lm in lms:
        v = getattr(lm, "visibility", None)
        if v is None:
            v = getattr(lm, "presence", 1.0)
        out.append(float(v))
    return np.array(out, dtype=np.float64)


def make_landmarker(model_path: Path):
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision

    options = vision.PoseLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=str(model_path)),
        running_mode=vision.RunningMode.VIDEO,
        num_poses=1,
    )
    return vision.PoseLandmarker.create_from_options(options)


def run_one(
    model_path: Path,
    video: Path,
    out_dir: Path,
    complexity: int,
    *,
    preserve_lab_export: bool = False,
) -> dict:
    import mediapipe as mp

    # Fresh landmarker per clip — VIDEO mode requires monotonic timestamps
    landmarker = make_landmarker(model_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        landmarker.close()
        raise RuntimeError(f"Cannot open {video}")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)

    joints3d, joints2d, confs, foot_landmarks, body_landmarks = [], [], [], [], []
    landmarks33_world, landmarks33_image, landmarks33_conf = [], [], []
    fi = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            ts_ms = int(round(fi * 1000.0 / max(fps, 1e-6)))
            res = landmarker.detect_for_video(mp_image, ts_ms)
            fi += 1

            if not res.pose_landmarks or not res.pose_world_landmarks:
                joints3d.append(np.zeros((len(LAB_JOINTS), 3), dtype=np.float32))
                joints2d.append(np.zeros((len(LAB_JOINTS), 2), dtype=np.float32))
                confs.append(np.zeros((len(LAB_JOINTS),), dtype=np.float32))
                foot_landmarks.append(np.zeros((4, 3), dtype=np.float32))
                body_landmarks.append(np.zeros((4, 3), dtype=np.float32))
                landmarks33_world.append(np.zeros((33, 3), dtype=np.float32))
                landmarks33_image.append(np.zeros((33, 3), dtype=np.float32))
                landmarks33_conf.append(np.zeros((33,), dtype=np.float32))
                continue

            img_lms = res.pose_landmarks[0]
            world_lms = res.pose_world_landmarks[0]
            world = _lm_xyz(world_lms)
            vis = _lm_vis(img_lms)
            img = np.array([[lm.x * w, lm.y * h] for lm in img_lms], dtype=np.float64)
            image_normalized = _lm_xyz(img_lms)
            if world.shape != (33, 3) or image_normalized.shape != (33, 3):
                raise ValueError(
                    f"expected 33 MediaPipe landmarks, got world={world.shape} image={image_normalized.shape}"
                )
            landmarks33_world.append(world.astype(np.float32))
            landmarks33_image.append(image_normalized.astype(np.float32))
            landmarks33_conf.append(vis.astype(np.float32))
            # Heel and toe landmarks retain the foot-facing information that the
            # 16-joint lab skeleton intentionally omits.
            foot_landmarks.append(world[[29, 31, 30, 32]].astype(np.float32))
            body_landmarks.append(world[[11, 12, 23, 24]].astype(np.float32))

            lab3d, conf = mediapipe_array_to_lab(world, vis)
            lab2d = np.zeros((len(LAB_JOINTS), 2), dtype=np.float64)
            for mpi, name in MEDIAPIPE_TO_LAB.items():
                lab2d[JOINT_TO_IDX[name]] = img[mpi]
            ls = lab2d[JOINT_TO_IDX["left_shoulder"]]
            rs = lab2d[JOINT_TO_IDX["right_shoulder"]]
            lh = lab2d[JOINT_TO_IDX["left_hip"]]
            rh = lab2d[JOINT_TO_IDX["right_hip"]]
            lab2d[JOINT_TO_IDX["pelvis"]] = 0.5 * (lh + rh)
            lab2d[JOINT_TO_IDX["neck"]] = 0.5 * (ls + rs)
            lab2d[JOINT_TO_IDX["spine"]] = 0.5 * (
                lab2d[JOINT_TO_IDX["neck"]] + lab2d[JOINT_TO_IDX["pelvis"]]
            )

            joints3d.append(lab3d.astype(np.float32))
            joints2d.append(lab2d.astype(np.float32))
            confs.append(conf.astype(np.float32))
    finally:
        cap.release()
        landmarker.close()

    j3 = np.stack(joints3d, axis=0) if joints3d else np.zeros((0, len(LAB_JOINTS), 3), np.float32)
    j2 = np.stack(joints2d, axis=0) if joints2d else np.zeros((0, len(LAB_JOINTS), 2), np.float32)
    cf = np.stack(confs, axis=0) if confs else np.zeros((0, len(LAB_JOINTS)), np.float32)
    if not preserve_lab_export:
        np.save(out_dir / "joints3d.npy", j3)
        np.save(out_dir / "joints2d.npy", j2)
        np.save(out_dir / "conf.npy", cf)
    full_world = (
        np.stack(landmarks33_world, axis=0)
        if landmarks33_world else np.zeros((0, 33, 3), np.float32)
    )
    full_image = (
        np.stack(landmarks33_image, axis=0)
        if landmarks33_image else np.zeros((0, 33, 3), np.float32)
    )
    full_conf = (
        np.stack(landmarks33_conf, axis=0)
        if landmarks33_conf else np.zeros((0, 33), np.float32)
    )
    np.save(out_dir / "landmarks33_world.npy", full_world)
    np.save(out_dir / "landmarks33_image.npy", full_image)
    np.save(out_dir / "landmarks33_conf.npy", full_conf)
    if not preserve_lab_export:
        foot = np.stack(foot_landmarks, axis=0) if foot_landmarks else np.zeros((0, 4, 3), np.float32)
        if foot.size:
            foot[..., 1] *= -1.0
            foot[..., 2] *= -1.0
        body = np.stack(body_landmarks, axis=0) if body_landmarks else np.zeros((0, 4, 3), np.float32)
        if body.size:
            body[..., 1] *= -1.0
            body[..., 2] *= -1.0
        (out_dir / "foot_landmarks.json").write_text(
            json.dumps({
                "names": ["left_heel", "left_toe", "right_heel", "right_toe"],
                "frames": foot.tolist(),
                "body_names": ["left_shoulder", "right_shoulder", "left_hip", "right_hip"],
                "body_frames": body.tolist(),
            }),
            encoding="utf-8",
        )

    src = out_dir / "source.mp4"
    if not src.exists():
        try:
            os_link = getattr(Path, "hardlink_to", None)
            if os_link:
                src.hardlink_to(video)
            else:
                raise OSError("no hardlink")
        except OSError:
            shutil.copy2(video, src)

    if not preserve_lab_export:
        # Viewer-friendly axes (OpenCV Y-down → Y-up), same idea as teacher export
        view = j3.copy()
        if view.size:
            view[..., 1] *= -1.0
            view[..., 2] *= -1.0
        save_viewer_payload(
            out_dir / "viewer_payload.json",
            video_url=f"/media/{out_dir.name}/source.mp4",
            joints=view,
            fps=float(fps),
            bones=LAB_BONES,
            joint_names=LAB_JOINTS,
            title=f"MediaPipe — {out_dir.name}",
        )

    meta_path = out_dir / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if preserve_lab_export and meta_path.is_file() else {
        "clip_id": out_dir.name,
        "source_video": str(video.resolve()),
        "backend": "mediapipe_tasks_pose_landmarker",
        "model_complexity": complexity,
        "fps": fps,
        "n_frames": int(j3.shape[0]),
        "width": w,
        "height": h,
        "joint_names": LAB_JOINTS,
    }
    meta.update({
        "full_landmarks": {
            "count": 33,
            "world_file": "landmarks33_world.npy",
            "world_axes": "MediaPipe Pose world landmarks (raw task coordinates)",
            "image_file": "landmarks33_image.npy",
            "image_axes": "MediaPipe normalized image x,y,z",
            "confidence_file": "landmarks33_conf.npy",
        },
        "created_unix": time.time(),
    })
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--people-root", type=Path, default=LAB_ROOT / "data" / "input" / "people")
    ap.add_argument("--out", type=Path, default=LAB_ROOT / "data" / "mediapipe")
    ap.add_argument("--complexity", type=int, default=1, choices=(0, 1, 2))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip clips that already have joints3d.npy under --out",
    )
    ap.add_argument(
        "--video",
        type=Path,
        action="append",
        default=[],
        help="Process only this video (repeatable). Does NOT scan --people-root.",
    )
    ap.add_argument("--clip-id", action="append", default=[], help="Output ID for each --video (repeatable)")
    ap.add_argument(
        "--full-landmarks-only",
        action="store_true",
        help="Write only landmarks33_* files and metadata; preserve existing lab/training exports.",
    )
    args = ap.parse_args()

    try:
        import mediapipe  # noqa: F401
        from mediapipe.tasks.python import vision  # noqa: F401
    except ImportError:
        print("mediapipe tasks not available. pip install mediapipe", file=sys.stderr)
        sys.exit(2)

    model_path = ensure_model(args.complexity)

    if args.clip_id and len(args.clip_id) != len(args.video):
        ap.error("--clip-id must be supplied once for every --video")

    # Explicit --video list is exclusive: never also crawl people-root.
    if args.video:
        direct_ids = args.clip_id or [video.stem for video in args.video]
        clips = list(zip(direct_ids, args.video))
    else:
        clips = discover_people_clips(args.people_root)

    if args.limit > 0:
        clips = clips[: args.limit]
    if not clips:
        src = " --video list" if args.video else f" under {args.people_root}"
        print(f"No clips{src}")
        sys.exit(1)

    args.out.mkdir(parents=True, exist_ok=True)
    print(
        f"[mediapipe] clips={len(clips)} complexity={args.complexity} "
        f"model={model_path.name} skip_existing={args.skip_existing}",
        flush=True,
    )
    ok = fail = skip = 0
    for i, (clip_id, path) in enumerate(clips, 1):
        out_dir = args.out / clip_id
        if args.skip_existing and (out_dir / "joints3d.npy").exists():
            skip += 1
            print(f"[skip] {i}/{len(clips)} {clip_id}", flush=True)
            continue
        try:
            meta = run_one(
                model_path, path, out_dir, args.complexity,
                preserve_lab_export=args.full_landmarks_only,
            )
            ok += 1
            print(f"[ok] {i}/{len(clips)} {clip_id} T={meta['n_frames']}", flush=True)
        except Exception as e:
            fail += 1
            print(f"[FAIL] {clip_id}: {e}", flush=True)

    print(f"[mediapipe] done ok={ok} skip={skip} fail={fail}", flush=True)
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
