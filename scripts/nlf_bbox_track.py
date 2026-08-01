#!/usr/bin/env python3
"""Light person bbox helpers for NLF fast path (no YOLOv8x every frame).

Use with estimate_poses_batched when the frame is not a tight person crop:
  - sticky IoU tracker from an occasional YOLOv8n (or external) box
  - full-frame only as last-resort fallback
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import torch


def xyxy_to_xywh(box_xyxy: np.ndarray) -> np.ndarray:
    x1, y1, x2, y2 = [float(v) for v in box_xyxy[:4]]
    return np.array([x1, y1, max(1.0, x2 - x1), max(1.0, y2 - y1)], dtype=np.float32)


def expand_xywh(box: np.ndarray, h: int, w: int, scale: float = 1.25) -> np.ndarray:
    """Pad box so limbs are not clipped; clamp to image."""
    x, y, bw, bh = [float(v) for v in box[:4]]
    cx, cy = x + 0.5 * bw, y + 0.5 * bh
    bw2, bh2 = bw * scale, bh * scale
    x2 = max(0.0, cx - 0.5 * bw2)
    y2 = max(0.0, cy - 0.5 * bh2)
    x2e = min(float(w), cx + 0.5 * bw2)
    y2e = min(float(h), cy + 0.5 * bh2)
    return np.array([x2, y2, max(1.0, x2e - x2), max(1.0, y2e - y2)], dtype=np.float32)


def iou_xywh(a: np.ndarray, b: np.ndarray) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ax2, ay2 = ax + aw, ay + ah
    bx2, by2 = bx + bw, by + bh
    ix1, iy1 = max(ax, bx), max(ay, by)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    union = aw * ah + bw * bh - inter
    return float(inter / union) if union > 0 else 0.0


@dataclass
class StickyBBox:
    """Re-detect every `detect_every` frames; otherwise keep last box if IoU ok."""

    detect_every: int = 6
    min_iou: float = 0.1
    expand: float = 1.25
    last_xywh: np.ndarray | None = None
    frame_i: int = 0

    def needs_detect(self) -> bool:
        nxt = self.frame_i + 1
        return self.last_xywh is None or (nxt % self.detect_every == 1)

    def update(
        self,
        h: int,
        w: int,
        detected_xywh: np.ndarray | None = None,
        *,
        force_fullframe: bool = False,
    ) -> np.ndarray:
        self.frame_i += 1
        full = np.array([0.0, 0.0, float(w), float(h)], dtype=np.float32)
        if force_fullframe:
            self.last_xywh = full
            return full
        if detected_xywh is not None:
            det = expand_xywh(detected_xywh.astype(np.float32), h, w, self.expand)
            if self.last_xywh is None:
                self.last_xywh = det
                return self.last_xywh
            if iou_xywh(self.last_xywh, det) >= self.min_iou:
                self.last_xywh = 0.75 * self.last_xywh + 0.25 * det
            else:
                self.last_xywh = det
            return self.last_xywh
        return self.last_xywh if self.last_xywh is not None else full

    def as_torch(self, xywh: np.ndarray, device: str | torch.device) -> torch.Tensor:
        return torch.tensor(xywh[None, :], device=device, dtype=torch.float32)


@dataclass
class YoloNanoPerson:
    """Ultralytics YOLOv8n — person class only. ~ms on RTX, not NLF's YOLOv8x."""

    device: str = "cuda"
    conf: float = 0.35
    imgsz: int = 320
    _model: object = field(default=None, repr=False)

    def load(self) -> None:
        if self._model is not None:
            return
        from pathlib import Path

        from ultralytics import YOLO

        # Prefer lab-local weights; Ultralytics downloads on first miss.
        candidates = [
            Path(__file__).resolve().parents[1] / "data" / "models" / "yolo" / "yolov8n.pt",
            Path(__file__).resolve().parents[1] / "yolov8n.pt",
            Path("yolov8n.pt"),
        ]
        weights = next((p for p in candidates if p.is_file()), candidates[0])
        weights.parent.mkdir(parents=True, exist_ok=True)
        self._model = YOLO(str(weights))

    def detect_xywh(self, rgb_u8: np.ndarray) -> np.ndarray | None:
        """Largest-area person box as xywh, or None."""
        self.load()
        assert self._model is not None
        # Ultralytics expects BGR ndarray.
        bgr = rgb_u8[:, :, ::-1]
        res = self._model.predict(
            bgr,
            classes=[0],
            conf=self.conf,
            imgsz=self.imgsz,
            device=self.device if self.device != "cpu" else "cpu",
            verbose=False,
        )
        if not res:
            return None
        boxes = res[0].boxes
        if boxes is None or len(boxes) == 0:
            return None
        xyxy = boxes.xyxy.detach().float().cpu().numpy()
        areas = (xyxy[:, 2] - xyxy[:, 0]) * (xyxy[:, 3] - xyxy[:, 1])
        i = int(np.argmax(areas))
        return xyxy_to_xywh(xyxy[i])
