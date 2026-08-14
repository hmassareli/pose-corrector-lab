#!/usr/bin/env python3
"""NLF-S game/runtime fast path helpers (no YOLO, no SMPL fit, joints-only)."""

from __future__ import annotations

from typing import Any

import numpy as np
import torch


def load_nlf(model_path, device: str = "cuda"):
    import torchvision  # noqa: F401 — TorchScript needs torchvision.ops.nms

    model = torch.jit.load(str(model_path), map_location=device).eval()
    return model


def smpl24_canonical(model) -> torch.Tensor:
    """Last 24 rows of cano_all['smpl'] = SMPL joints in canonical space."""
    cano = model.cano_all["smpl"]
    return cano[-24:].contiguous()


SMPLX55_JOINT_NAMES = [
    "pelvis", "left_hip", "right_hip", "spine1", "left_knee", "right_knee",
    "spine2", "left_ankle", "right_ankle", "spine3", "left_foot", "right_foot",
    "neck", "left_collar", "right_collar", "head", "left_shoulder", "right_shoulder",
    "left_elbow", "right_elbow", "left_wrist", "right_wrist", "jaw", "left_eye",
    "right_eye", "left_index1", "left_index2", "left_index3", "left_middle1",
    "left_middle2", "left_middle3", "left_pinky1", "left_pinky2", "left_pinky3",
    "left_ring1", "left_ring2", "left_ring3", "left_thumb1", "left_thumb2",
    "left_thumb3", "right_index1", "right_index2", "right_index3", "right_middle1",
    "right_middle2", "right_middle3", "right_pinky1", "right_pinky2", "right_pinky3",
    "right_ring1", "right_ring2", "right_ring3", "right_thumb1", "right_thumb2",
    "right_thumb3",
]


def smplx55_canonical(model) -> torch.Tensor:
    """Last 55 rows of cano_all['smplx'] in the standard SMPL-X joint order."""
    cano = model.cano_all["smplx"]
    return cano[-len(SMPLX55_JOINT_NAMES) :].contiguous()


def smpl_surface_canonical(model) -> torch.Tensor:
    """First 1024 rows of cano_all['smpl'] = SMPL surface samples (not joints)."""
    cano = model.cano_all["smpl"]
    return cano[:-24].contiguous()


def x55_plus_surface_weights(model) -> tuple[dict[str, torch.Tensor], int, int]:
    """One NLF query: 55 SMPL-X joints followed by 1024 SMPL surface points."""
    x55 = smplx55_canonical(model)
    surf = smpl_surface_canonical(model)
    pts = torch.cat([x55, surf], dim=0)
    return model.get_weights_for_canonical_points(pts), int(x55.shape[0]), int(surf.shape[0])


def smpl24_hand_surface_indices(model) -> dict[str, list[int]]:
    """Surface-point indices nearest to SMPL-24 wrist/hand joints."""
    surf = smpl_surface_canonical(model)
    joints = smpl24_canonical(model)
    assign = torch.cdist(surf, joints).argmin(dim=1).cpu().numpy()
    names = {
        "left_wrist": 20,
        "right_wrist": 21,
        "left_hand": 22,
        "right_hand": 23,
    }
    return {name: np.flatnonzero(assign == idx).tolist() for name, idx in names.items()}


def lab_joint_indices_smpl24() -> list[int]:
    """SMPL24 indices covering lab trunk/limbs used by residual panel."""
    return [0, 1, 2, 4, 5, 7, 8, 16, 17, 18, 19, 20, 21]


def get_joint_weights(model, mode: str = "joints24") -> tuple[dict[str, torch.Tensor], list[int] | None]:
    """
    mode:
      joints24 — all 24 SMPL joints
    lab13 — subset mapped to lab skeleton coverage
    smplx55 — body, face anchors, and articulated fingers for retarget probing
    Returns (weights_dict, smpl_index_list or None if full 24 in order).
    """
    joints = smpl24_canonical(model)
    if mode == "joints24":
        return model.get_weights_for_canonical_points(joints), None
    if mode == "lab13":
        idx = lab_joint_indices_smpl24()
        tidx = torch.tensor(idx, device=joints.device, dtype=torch.long)
        return model.get_weights_for_canonical_points(joints.index_select(0, tidx)), idx
    if mode == "smplx55":
        return model.get_weights_for_canonical_points(smplx55_canonical(model)), None
    raise ValueError(f"unknown weight mode: {mode}")


def fullframe_box(h: int, w: int, device: str | torch.device) -> torch.Tensor:
    """xywh box covering the whole image (person-centric crops / single-player)."""
    return torch.tensor([[0.0, 0.0, float(w), float(h)]], device=device, dtype=torch.float32)


@torch.inference_mode()
def estimate_joints24(
    model,
    rgb_u8_hwc: np.ndarray,
    weights: dict[str, torch.Tensor],
    device: str = "cuda",
    num_aug: int = 1,
    box: torch.Tensor | None = None,
    *,
    to_numpy: bool = True,
) -> np.ndarray | torch.Tensor | None:
    """
    rgb uint8 HWC → (24,3) joints in mm (NLF camera space), or None if empty.
    Uses estimate_poses_batched (no detector, no SMPL fit). Always pass num_aug=1.
    Set to_numpy=False to keep the tensor on device (lower sync cost in tight loops).
    """
    h, w = rgb_u8_hwc.shape[:2]
    img = (
        torch.from_numpy(np.ascontiguousarray(rgb_u8_hwc))
        .permute(2, 0, 1)
        .to(device, non_blocking=True)
        .unsqueeze(0)
    )
    if box is None:
        box = fullframe_box(h, w, device)
    elif str(box.device) != str(device):
        box = box.to(device, non_blocking=True)
    pred = model.estimate_poses_batched(img, [box], weights, num_aug=num_aug)
    poses = pred.get("poses3d")
    if not poses or len(poses[0]) == 0:
        return None
    j = poses[0][0]
    if j.ndim == 3:
        j = j[0]
    j = j.detach().float()
    if not to_numpy:
        return j
    return j.cpu().numpy()


@torch.inference_mode()
def detect_smpl_joints_nonparam(
    model,
    rgb_u8_hwc: np.ndarray,
    device: str = "cuda",
    joint_key: str = "joints3d_nonparam",
) -> np.ndarray | None:
    """Baseline full API (YOLO + 1048 queries + SMPL fit)."""
    img = torch.from_numpy(rgb_u8_hwc).permute(2, 0, 1).to(device).contiguous().unsqueeze(0)
    pred = model.detect_smpl_batched(img)
    people = pred.get(joint_key) or pred.get("joints3d")
    if not people or len(people[0]) == 0:
        return None
    boxes = pred.get("boxes")
    idx = 0
    if boxes and len(boxes[0]) > 1:
        scores = boxes[0][:, -1]
        idx = int(torch.argmax(scores).item())
    j24 = people[0][idx].detach().float().cpu().numpy()
    if j24.ndim == 3:
        j24 = j24[0]
    return j24


def cuda_ms(fn, n: int = 40, warm: int = 10) -> dict[str, float]:
    """Time a CUDA callable with cuda.Event (ms)."""
    if not torch.cuda.is_available():
        import time

        with torch.inference_mode():
            for _ in range(warm):
                fn()
        times = []
        with torch.inference_mode():
            for _ in range(n):
                t0 = time.perf_counter()
                fn()
                times.append((time.perf_counter() - t0) * 1000.0)
    else:
        with torch.inference_mode():
            for _ in range(warm):
                fn()
        torch.cuda.synchronize()
        starter = torch.cuda.Event(enable_timing=True)
        ender = torch.cuda.Event(enable_timing=True)
        times = []
        with torch.inference_mode():
            for _ in range(n):
                starter.record()
                fn()
                ender.record()
                torch.cuda.synchronize()
                times.append(float(starter.elapsed_time(ender)))
    a = np.asarray(times, dtype=np.float64)
    return {
        "mean": float(a.mean()),
        "p50": float(np.median(a)),
        "p95": float(np.percentile(a, 95)),
        "min": float(a.min()),
        "max": float(a.max()),
        "n": float(n),
    }


def stage_breakdown(model, rgb_u8_hwc: np.ndarray, device: str = "cuda", n: int = 40) -> dict[str, Any]:
    """Profile detector / estimate joints24 / full detect_smpl."""
    weights, _ = get_joint_weights(model, "joints24")
    h, w = rgb_u8_hwc.shape[:2]
    img = torch.from_numpy(rgb_u8_hwc).permute(2, 0, 1).to(device).contiguous().unsqueeze(0)
    box = fullframe_box(h, w, device)
    img_f = img.float() / 255.0

    # Init cano_all weights inside detect_smpl once (amortized cold cost).
    with torch.inference_mode():
        _ = model.detect_smpl_batched(img)
        _ = model.estimate_poses_batched(img, [box], weights, num_aug=1)

    out: dict[str, Any] = {
        "frame_hw": [h, w],
        "detector_yolov8x": cuda_ms(lambda: model.detector(img_f), n=n),
        "estimate_joints24_fullframe_num_aug1": cuda_ms(
            lambda: model.estimate_poses_batched(img, [box], weights, num_aug=1), n=n
        ),
        "detect_smpl_batched_full": cuda_ms(lambda: model.detect_smpl_batched(img), n=n),
    }
    # Approximate fit+verts cost as residual (not exact overlap-free).
    est = out["estimate_joints24_fullframe_num_aug1"]["mean"]
    det = out["detector_yolov8x"]["mean"]
    full = out["detect_smpl_batched_full"]["mean"]
    out["approx_extra_in_full_ms"] = float(full - det - est)
    out["budget_30fps_ms"] = 33.333
    out["fast_path_p95_ok"] = bool(out["estimate_joints24_fullframe_num_aug1"]["p95"] < 33.333)
    return out
