#!/usr/bin/env python3
"""Create a synthetic teacher clip so the HTML viewer works before GVHMR is installed."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB_ROOT / "src"))

from pose_lab.io import save_teacher_clip, save_viewer_payload
from pose_lab.skeleton import LAB_BONES, LAB_JOINTS, JOINT_TO_IDX


def synth_punch_sequence(n: int = 90, fps: float = 30.0) -> np.ndarray:
    """Simple jab-like motion on the right arm."""
    J = len(LAB_JOINTS)
    poses = np.zeros((n, J, 3), dtype=np.float32)

    def setj(name, xyz, t=None):
        idx = JOINT_TO_IDX[name]
        if t is None:
            poses[:, idx] = xyz
        else:
            poses[t, idx] = xyz

    # Static trunk
    setj("pelvis", [0, 0.95, 0])
    setj("left_hip", [-0.1, 0.9, 0])
    setj("right_hip", [0.1, 0.9, 0])
    setj("left_knee", [-0.12, 0.5, 0.05])
    setj("right_knee", [0.12, 0.5, 0.05])
    setj("left_ankle", [-0.12, 0.05, 0.1])
    setj("right_ankle", [0.12, 0.05, 0.1])
    setj("spine", [0, 1.2, 0])
    setj("left_shoulder", [-0.2, 1.45, 0])
    setj("right_shoulder", [0.2, 1.45, 0])
    setj("neck", [0, 1.55, 0])
    setj("head", [0, 1.72, 0])
    # Guard / punch
    for t in range(n):
        phase = (t / fps) * 2 * math.pi  # ~1 Hz cycle
        # left arm guard
        poses[t, JOINT_TO_IDX["left_elbow"]] = [-0.28, 1.25, 0.15]
        poses[t, JOINT_TO_IDX["left_wrist"]] = [-0.22, 1.35, 0.28]
        # right jab along +Z
        extend = 0.5 * (1 + math.sin(phase))
        poses[t, JOINT_TO_IDX["right_elbow"]] = [0.28, 1.28, 0.1 + 0.25 * extend]
        poses[t, JOINT_TO_IDX["right_wrist"]] = [0.32, 1.32, 0.2 + 0.55 * extend]
    return poses


def main() -> None:
    clip = "demo_jab"
    out = LAB_ROOT / "data" / "teacher" / clip
    fps = 30.0
    joints = synth_punch_sequence(90, fps)
    meta = {
        "clip_id": clip,
        "teacher": "synthetic",
        "static_camera": True,
        "video": {"fps": fps, "n_frames": int(joints.shape[0])},
        "qa": {"status": "ok", "notes": "synthetic demo for viewer"},
    }
    save_teacher_clip(out, joints, meta)

    # Tiny placeholder mp4 is hard without encoder; viewer still loads skeleton if video 404 —
    # write a note and a silent empty file marker. Prefer generating via opencv if present.
    video_path = out / "source.mp4"
    try:
        import cv2

        h, w = 480, 640
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(video_path), fourcc, fps, (w, h))
        for t in range(joints.shape[0]):
            frame = np.zeros((h, w, 3), dtype=np.uint8)
            frame[:] = (18, 20, 28)
            # draw 2D stick projection
            scale = 180
            ox, oy = w // 2, int(h * 0.85)

            def pt(name):
                p = joints[t, JOINT_TO_IDX[name]]
                return int(ox + p[0] * scale), int(oy - p[1] * scale)

            for a, b in LAB_BONES:
                cv2.line(frame, pt(a), pt(b), (80, 220, 160), 2)
            cv2.putText(
                frame,
                f"SYNTH DEMO  t={t}",
                (16, 32),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (200, 210, 220),
                1,
                cv2.LINE_AA,
            )
            writer.write(frame)
        writer.release()
    except Exception as e:
        print(f"OpenCV video write skipped: {e}")
        video_path.write_bytes(b"")

    save_viewer_payload(
        out / "viewer_payload.json",
        video_url=f"/media/{clip}/source.mp4",
        joints=joints,
        fps=fps,
        bones=LAB_BONES,
        joint_names=LAB_JOINTS,
        title=f"Synthetic jab — {clip}",
    )
    print(f"Demo clip ready: {out}")
    print(f"  python scripts/serve_viewer.py --clip {clip}")


if __name__ == "__main__":
    main()
