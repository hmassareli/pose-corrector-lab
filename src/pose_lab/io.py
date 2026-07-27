"""I/O helpers for clips, teacher outputs, paired samples."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}


def list_videos(folder: str | Path) -> list[Path]:
    folder = Path(folder)
    if not folder.exists():
        return []
    return sorted([p for p in folder.iterdir() if p.suffix.lower() in VIDEO_EXTS])


def clip_id_from_path(path: Path) -> str:
    return path.stem


def teacher_dir(root: str | Path, clip_id: str) -> Path:
    return Path(root) / clip_id


def save_teacher_clip(
    out_dir: Path,
    joints3d: np.ndarray,
    meta: dict[str, Any],
    joints3d_smpl: np.ndarray | None = None,
    smplx_params: dict[str, np.ndarray] | None = None,
) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    np.save(out_dir / "joints3d.npy", joints3d.astype(np.float32))
    if joints3d_smpl is not None:
        np.save(out_dir / "joints3d_smpl.npy", joints3d_smpl.astype(np.float32))
    if smplx_params is not None:
        np.savez_compressed(out_dir / "smplx_params.npz", **smplx_params)
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def load_teacher_clip(out_dir: Path) -> dict[str, Any]:
    out_dir = Path(out_dir)
    meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
    data = {
        "meta": meta,
        "joints3d": np.load(out_dir / "joints3d.npy"),
    }
    smpl_p = out_dir / "joints3d_smpl.npy"
    if smpl_p.exists():
        data["joints3d_smpl"] = np.load(smpl_p)
    qa_p = out_dir / "qa.json"
    if qa_p.exists():
        data["qa"] = json.loads(qa_p.read_text(encoding="utf-8"))
    return data


def save_viewer_payload(
    out_path: Path,
    video_url: str,
    joints: np.ndarray,
    fps: float,
    bones: list[tuple[str, str]],
    joint_names: list[str],
    title: str = "",
) -> None:
    """Write JSON consumed by viewer/index.html."""
    payload = viewer_payload_dict(video_url, joints, fps, bones, joint_names, title=title)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload), encoding="utf-8")


def viewer_payload_dict(
    video_url: str,
    joints: np.ndarray,
    fps: float,
    bones: list[tuple[str, str]],
    joint_names: list[str],
    title: str = "",
) -> dict[str, Any]:
    return {
        "title": title,
        "video": video_url,
        "fps": float(fps),
        "joint_names": list(joint_names),
        "bones": [{"a": a, "b": b} for a, b in bones],
        "frames": np.asarray(joints, dtype=float).tolist(),
    }


def clip_has_joints(clip_dir: Path) -> bool:
    return (Path(clip_dir) / "joints3d.npy").is_file()


def _source_video_name(clip_dir: Path) -> str | None:
    clip_dir = Path(clip_dir)
    for name in ("source.mp4", "source.mov", "source.webm", "source.mkv", "source.avi"):
        if (clip_dir / name).is_file():
            return name
    for p in sorted(clip_dir.iterdir()):
        if p.is_file() and p.suffix.lower() in VIDEO_EXTS:
            return p.name
    return None


def probe_video_fps(video_path: Path) -> tuple[float, int] | None:
    try:
        import cv2

        cap = cv2.VideoCapture(str(video_path))
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        cap.release()
        if fps > 1.0:
            return fps, n
    except Exception:
        pass
    return None


def resolve_clip_fps(clip_dir: Path, meta: dict[str, Any], n_joints: int | None = None) -> float:
    """Prefer container FPS from source.mp4 — teacher joints are 1:1 with video frames.

    Meta often omits fps; defaulting to 30 makes the viewer skeleton run fast on 24fps clips.
    """
    src_name = _source_video_name(clip_dir)
    if src_name:
        probed = probe_video_fps(Path(clip_dir) / src_name)
        if probed is not None:
            fps, n_vid = probed
            # If joints match frame count, trust the video clock.
            if n_joints is None or n_vid <= 1 or abs(n_joints - n_vid) <= 1:
                return float(fps)
            # Rare mismatch: derive effective fps so duration lines up.
            if n_vid > 1 and fps > 1.0:
                dur = n_vid / fps
                if dur > 0 and n_joints:
                    return float(n_joints) / dur
            return float(fps)

    if meta.get("fps"):
        return float(meta["fps"])
    video_meta = meta.get("video")
    if isinstance(video_meta, dict) and video_meta.get("fps"):
        return float(video_meta["fps"])
    return 30.0


def build_viewer_payload_from_clip(
    clip_dir: Path,
    *,
    source: str = "teacher",
    title: str | None = None,
    cache: bool = True,
) -> dict[str, Any]:
    """Build viewer JSON from joints3d.npy (+ meta). Optionally cache viewer_payload.json.

    MediaPipe joints on disk are OpenCV-ish; apply the same Y/Z flip used in run_mediapipe.
    Teacher joints stay camera-space (viewer UI plants feet on the grid).
    """
    from .skeleton import LAB_BONES, LAB_JOINTS

    clip_dir = Path(clip_dir)
    joints_path = clip_dir / "joints3d.npy"
    if not joints_path.is_file():
        raise FileNotFoundError(f"missing {joints_path}")

    meta: dict[str, Any] = {}
    meta_path = clip_dir / "meta.json"
    if meta_path.is_file():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))

    joints = np.load(joints_path).astype(np.float32)
    if joints.ndim != 3 or joints.shape[-1] != 3:
        raise ValueError(f"Expected joints (T,J,3), got {joints.shape}")

    view = joints.copy()
    # Disk MP + raw GVHMR are OpenCV-ish (Y down). Paired corrected / teacher_aligned
    # were already flipped in pair_poses — do not flip again.
    if source in ("mediapipe", "teacher") and view.size:
        view[..., 1] *= -1.0
        view[..., 2] *= -1.0

    joint_names = list(meta.get("joint_names") or LAB_JOINTS)
    if len(joint_names) != view.shape[1]:
        joint_names = LAB_JOINTS[: view.shape[1]] if view.shape[1] <= len(LAB_JOINTS) else [
            f"j{i}" for i in range(view.shape[1])
        ]

    # Prefer video-clock FPS when joints match frame count (MP / corrected /
    # teacher_aligned after source-fps export). Meta fps is the fallback.
    fps = resolve_clip_fps(clip_dir, meta, n_joints=int(view.shape[0]))
    src_name = _source_video_name(clip_dir)
    video_url = f"/media/{clip_dir.name}/{src_name}" if src_name else ""
    label = {
        "mediapipe": "MediaPipe",
        "teacher": "GVHMR",
        "teacher_aligned": "Teacher aligned",
        "corrected": "Corrector",
    }.get(source, source)
    payload = viewer_payload_dict(
        video_url=video_url,
        joints=view,
        fps=fps,
        bones=LAB_BONES,
        joint_names=joint_names,
        title=title or f"{label} — {clip_dir.name}",
    )

    if cache:
        out = clip_dir / "viewer_payload.json"
        out.write_text(json.dumps(payload), encoding="utf-8")
    return payload
