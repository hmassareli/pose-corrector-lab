#!/usr/bin/env python3
"""Unified Pose Lab: multi-source offline viewer + live webcam corrector / NLF-S.

Usage:
  python scripts/serve_lab.py
  → http://127.0.0.1:8780/          (offline clips: MP / Teacher / Corrector / NLF-S)
  → http://127.0.0.1:8780/live      (webcam + MediaPipe / NLF-S + optional corrector)

Legacy single-source server remains: scripts/serve_viewer.py
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import threading
import time
import traceback
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB_ROOT / "src"))

from pose_lab.align import body_frame_from_pose, from_body_frame, to_body_frame  # noqa: E402
from pose_lab.data import apply_feature_ablation, feature_ablation_kwargs  # noqa: E402
from pose_lab.features import build_feature_sequence, feature_dim  # noqa: E402
from pose_lab.io import (  # noqa: E402
    build_viewer_payload_from_clip,
    clip_has_joints,
    resolve_clip_fps,
    viewer_payload_dict,
)
from pose_lab.models import build_model, take_delta_last  # noqa: E402
from pose_lab.skeleton import (  # noqa: E402
    DELTA_DIM,
    LAB_BONES,
    LAB_JOINTS,
    N_TARGETS,
    TARGET_IDX,
)
from pose_lab.timebase import CANONICAL_FPS, resample_at_times, resample_to_n_frames  # noqa: E402

VIEWER_DIR = LAB_ROOT / "viewer"
ASSETS_DIR = LAB_ROOT / "assets"
RUNS_DIR = LAB_ROOT / "runs"

SOURCE_ROOTS: dict[str, Path] = {
    "teacher": LAB_ROOT / "data" / "teacher",
    "mediapipe": LAB_ROOT / "data" / "mediapipe",
    "corrected": LAB_ROOT / "data" / "corrected",
    "teacher_aligned": LAB_ROOT / "data" / "teacher_aligned",
    "nlf_s": LAB_ROOT / "data" / "nlf_fast",
}

SOURCE_LABELS = {
    "mediapipe": "MediaPipe",
    "teacher": "Teacher",
    "teacher_aligned": "Teacher aligned",
    "corrected": "Corrector exportado",
    "nlf_s": "NLF-S",
}

DEFAULT_CKPT_HINTS = (
    "20260726_092251_gru_noaux_dropaccel_v1",
    "20260727_134842_gru_noaux_dropaccel_win_ft",
)


# ---------------------------------------------------------------------------
# Offline payload helpers (shared with serve_viewer.py)
# ---------------------------------------------------------------------------


def list_ready_clips(root: Path) -> list[str]:
    if not root.exists():
        return []
    return sorted(
        d.name
        for d in root.iterdir()
        if d.is_dir() and not d.name.startswith("_") and clip_has_joints(d)
    )


def payload_bytes_for_clip(clip_dir: Path, source: str) -> bytes:
    clip_dir = Path(clip_dir)
    cached = clip_dir / "viewer_payload.json"
    if cached.is_file():
        payload = json.loads(cached.read_text(encoding="utf-8"))
        meta: dict = {}
        meta_path = clip_dir / "meta.json"
        if meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        n = len(payload.get("frames") or [])
        true_fps = resolve_clip_fps(clip_dir, meta, n_joints=n or None)
        old = float(payload.get("fps") or 0.0)
        if true_fps > 1.0 and (old < 1.0 or abs(old - true_fps) > 0.05):
            payload["fps"] = true_fps
            cached.write_text(json.dumps(payload), encoding="utf-8")
            sys.stderr.write(
                f"[lab] fixed fps {clip_dir.name}: {old} → {true_fps:.4f}\n"
            )
    else:
        if not clip_has_joints(clip_dir):
            raise FileNotFoundError(
                f"No joints3d.npy for clip {clip_dir.name} (source={source})"
            )
        payload = build_viewer_payload_from_clip(clip_dir, source=source, cache=True)

    # Always rewrite video URL for multi-source media routing.
    video = payload.get("video") or ""
    if video.startswith("/media/") and f"/media/{source}/" not in video:
        # /media/<clip>/file.mp4 → /media/<source>/<clip>/file.mp4
        rest = video[len("/media/") :]
        payload["video"] = f"/media/{source}/{rest}"
    # NLF exports often omit source.mp4 — fall back to MediaPipe video for the same clip id.
    if source == "nlf_s":
        vid = payload.get("video") or ""
        nlf_has = False
        if vid.startswith(f"/media/{source}/"):
            rel = vid[len(f"/media/{source}/") :]
            nlf_has = (SOURCE_ROOTS[source] / rel).is_file()
        if not nlf_has:
            mp_dir = SOURCE_ROOTS["mediapipe"] / clip_dir.name
            for name in ("source.mp4", "video.mp4", "clip.mp4"):
                if (mp_dir / name).is_file():
                    payload["video"] = f"/media/mediapipe/{clip_dir.name}/{name}"
                    break
            else:
                # Any video under mediapipe clip dir
                for p in sorted(mp_dir.glob("*.mp4")):
                    payload["video"] = f"/media/mediapipe/{clip_dir.name}/{p.name}"
                    break
    payload["source"] = source
    return json.dumps(payload).encode("utf-8")


def apply_saved_training_delta(mp_pose: np.ndarray, delta: np.ndarray) -> np.ndarray:
    """Apply the stored training residual with export_corrected.apply_delta semantics."""
    R, scale, origin = body_frame_from_pose(mp_pose)
    mp_body = to_body_frame(mp_pose, R, scale, origin)
    target_delta = np.asarray(delta, dtype=np.float64).reshape(N_TARGETS, 3)
    for target_index, joint_index in enumerate(TARGET_IDX):
        mp_body[joint_index] += target_delta[target_index]
    out = mp_pose.copy()
    for joint_index in TARGET_IDX:
        out[joint_index] = from_body_frame(mp_body[joint_index : joint_index + 1], R, scale, origin)[0]
    return out


def training_oracle_payload(clip: str) -> dict:
    """Rebuild MP + exact saved target delta on the source-video frame grid."""
    paired_dir = LAB_ROOT / "data" / "paired" / clip
    mp_path = paired_dir / "mp_30.npy"
    residual_path = paired_dir / "residual_30.npy"
    meta_path = paired_dir / "meta.json"
    if not mp_path.is_file() or not residual_path.is_file():
        raise FileNotFoundError(f"missing paired training arrays for {clip}")
    mp_30 = np.load(mp_path).astype(np.float32)
    residual_30 = np.load(residual_path).astype(np.float32)
    if mp_30.ndim != 3 or residual_30.shape != (mp_30.shape[0], DELTA_DIM):
        raise ValueError(f"bad paired shapes mp={mp_30.shape} residual={residual_30.shape}")
    oracle_30 = np.stack(
        [apply_saved_training_delta(mp_30[i], residual_30[i]) for i in range(mp_30.shape[0])],
    ).astype(np.float32)
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    fps_src = float(meta.get("fps_src") or CANONICAL_FPS)
    n_src = int(meta.get("n_frames_src_mp") or 0)
    if n_src <= 0:
        n_src = int(round((oracle_30.shape[0] - 1) * fps_src / CANONICAL_FPS)) + 1
    oracle_src, _ = resample_to_n_frames(oracle_30, CANONICAL_FPS, fps_src, n_src)
    payload = viewer_payload_dict(
        video_url=f"/media/teacher_aligned/{clip}/source.mp4",
        joints=oracle_src,
        fps=fps_src,
        bones=LAB_BONES,
        joint_names=LAB_JOINTS,
        title="Oraculo de treino: MediaPipe + delta real",
    )
    payload["source"] = "training_oracle"
    payload["prediction"] = False
    payload["gate"] = False
    payload["input"] = "data/paired/<clip>/mp_30.npy"
    payload["delta"] = "data/paired/<clip>/residual_30.npy"
    payload["target_joints"] = [LAB_JOINTS[i] for i in TARGET_IDX]
    return payload


# ---------------------------------------------------------------------------
# Checkpoint discovery + live inference
# ---------------------------------------------------------------------------


_CKPT_CACHE: list[dict] | None = None


def discover_checkpoints(*, force: bool = False) -> list[dict]:
    """List best_hard.pt / last.pt under runs/*/checkpoints/ (compatible heads only)."""
    global _CKPT_CACHE
    if _CKPT_CACHE is not None and not force:
        return _CKPT_CACHE

    import torch

    out: list[dict] = []
    if not RUNS_DIR.is_dir():
        _CKPT_CACHE = out
        return out
    for run_dir in sorted(RUNS_DIR.iterdir()):
        ckpt_dir = run_dir / "checkpoints"
        if not ckpt_dir.is_dir():
            continue
        for name in ("best_hard.pt", "last.pt"):
            path = ckpt_dir / name
            if not path.is_file():
                continue
            short = f"{run_dir.name}/{name.replace('.pt', '')}"
            tag = "best" if name.startswith("best") else "last"
            run_short = run_dir.name
            parts = run_short.split("_", 2)
            if len(parts) >= 3 and parts[0].isdigit() and parts[1].isdigit():
                pretty = f"{parts[2]} · {parts[0]}_{parts[1]}"
            else:
                pretty = run_short

            # Skip archaic heads (e.g. delta_dim=12 before shoulders were targets).
            try:
                ckpt = torch.load(path, map_location="cpu", weights_only=False)
                F = int(ckpt.get("F") or 0)
                T = int(ckpt.get("T") or 15)
                w = ckpt["model"].get("head_delta.4.weight")
                delta_dim = int(w.shape[0]) if w is not None else DELTA_DIM
                if delta_dim != DELTA_DIM:
                    sys.stderr.write(
                        f"[lab] skip incompatible ckpt {short} delta_dim={delta_dim}\n"
                    )
                    continue
                fcfg = (ckpt.get("cfg") or {}).get("features") or {}
                hidden = int(((ckpt.get("cfg") or {}).get("model") or {}).get("hidden", 256))
            except Exception as e:
                sys.stderr.write(f"[lab] skip unreadable ckpt {short}: {e}\n")
                continue

            out.append(
                {
                    "id": short,
                    "path": str(path.relative_to(LAB_ROOT).as_posix()),
                    "run": run_dir.name,
                    "file": name,
                    "tag": tag,
                    "label": f"{pretty} · {tag}",
                    "preferred": any(h in run_dir.name for h in DEFAULT_CKPT_HINTS)
                    and tag == "best",
                    "F": F,
                    "T": T,
                    "hidden": hidden,
                    **feature_ablation_kwargs(fcfg),
                }
            )
    out.sort(
        key=lambda d: (0 if d["preferred"] else 1, d["run"], 0 if d["tag"] == "best" else 1)
    )
    _CKPT_CACHE = out
    return out


# ---------------------------------------------------------------------------
# Live corrector runtime
# ---------------------------------------------------------------------------


class CorrectorRuntime:
    """Lazy-load checkpoints; run causal window inference for live frames."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: dict[str, dict] = {}
        self._device = None

    def _torch_device(self):
        if self._device is None:
            import torch

            self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        return self._device

    def load(self, ckpt_id: str) -> dict:
        with self._lock:
            if ckpt_id in self._cache:
                return self._cache[ckpt_id]
            # Resolve id → path
            path = self._resolve(ckpt_id)
            import torch

            ckpt = torch.load(path, map_location="cpu", weights_only=False)
            cfg = ckpt.get("cfg") or {}
            F = int(ckpt.get("F") or feature_dim(True))
            T = int(ckpt.get("T") or 15)
            w = ckpt["model"].get("head_delta.4.weight")
            if w is None:
                # Fallback: any final Linear in head_delta.*
                for k, v in ckpt["model"].items():
                    if (
                        k.startswith("head_delta.")
                        and k.endswith(".weight")
                        and getattr(v, "ndim", 0) == 2
                    ):
                        w = v  # keep last (final) Linear weight
                if w is None:
                    raise ValueError(f"Checkpoint missing head_delta weight: {ckpt_id}")
            delta_dim = int(w.shape[0])
            if delta_dim != DELTA_DIM:
                raise ValueError(
                    f"Checkpoint delta_dim={delta_dim} incompatible with lab DELTA_DIM={DELTA_DIM}"
                )
            device = self._torch_device()
            model = build_model(cfg, in_dim=F, delta_dim=delta_dim).to(device)
            model.load_state_dict(ckpt["model"])
            model.eval()
            fcfg = cfg.get("features") or {}
            ig = cfg.get("inference_gate") or {}
            include_2d = F >= 113
            entry = {
                "id": ckpt_id,
                "path": str(path),
                "model": model,
                "cfg": cfg,
                "F": F,
                "T": T,
                "device": device,
                **feature_ablation_kwargs(fcfg),
                "include_2d": include_2d,
                "gate_conf": float(ig.get("conf_high", 0.85)),
                "gate_eps": float(ig.get("delta_eps", 0.02)),
                "hidden": int((cfg.get("model") or {}).get("hidden", 256)),
            }
            self._cache[ckpt_id] = entry
            sys.stderr.write(
                f"[lab] loaded ckpt {ckpt_id} F={F} T={T} device={device}\n"
            )
            return entry

    def _resolve(self, ckpt_id: str) -> Path:
        # Accept: "run/best_hard", "run/best_hard.pt", relative path, absolute
        raw = ckpt_id.replace("\\", "/").strip()
        candidates = [
            LAB_ROOT / raw,
            LAB_ROOT / "runs" / raw,
            LAB_ROOT / "runs" / f"{raw}.pt",
        ]
        if "/" in raw and not raw.endswith(".pt"):
            run, tag = raw.rsplit("/", 1)
            candidates.append(LAB_ROOT / "runs" / run / "checkpoints" / f"{tag}.pt")
        for c in candidates:
            if c.is_file():
                return c
        raise FileNotFoundError(f"Checkpoint not found: {ckpt_id}")

    @staticmethod
    def apply_delta(mp_pose: np.ndarray, delta: np.ndarray) -> np.ndarray:
        from pose_lab.align import body_frame_from_pose, from_body_frame, to_body_frame

        R, scale, origin = body_frame_from_pose(mp_pose)
        mp_b = to_body_frame(mp_pose, R, scale, origin)
        d = np.asarray(delta, dtype=np.float64).reshape(N_TARGETS, 3)
        assert d.size == DELTA_DIM
        for k, ji in enumerate(TARGET_IDX):
            mp_b[ji] = mp_b[ji] + d[k]
        out = mp_pose.copy()
        for ji in TARGET_IDX:
            out[ji] = from_body_frame(mp_b[ji : ji + 1], R, scale, origin)[0]
        return out

    def correct(
        self,
        ckpt_id: str,
        joints: np.ndarray,
        conf: np.ndarray,
        joints_2d: np.ndarray | None,
        fps: float,
        apply_gate: bool = True,
        timestamps: np.ndarray | None = None,
    ) -> dict:
        """joints (T,J,3) chronological — correct last frame."""
        import torch

        t0 = time.perf_counter()
        entry = self.load(ckpt_id)
        model = entry["model"]
        device = entry["device"]
        T_win = entry["T"]
        J = len(LAB_JOINTS)

        joints = np.asarray(joints, dtype=np.float32)
        conf = np.asarray(conf, dtype=np.float32)
        if joints.ndim != 3 or joints.shape[-1] != 3:
            raise ValueError(f"joints must be (T,J,3), got {joints.shape}")
        if joints.shape[1] != J:
            raise ValueError(f"expected J={J}, got {joints.shape[1]}")
        if conf.shape != joints.shape[:2]:
            raise ValueError(f"conf shape {conf.shape} != joints {joints.shape[:2]}")

        mp_2d = None
        if entry["include_2d"]:
            if joints_2d is not None:
                mp_2d = np.asarray(joints_2d, dtype=np.float32)
                if mp_2d.shape[:2] != joints.shape[:2]:
                    raise ValueError("joints_2d length mismatch")
            else:
                mp_2d = np.zeros((joints.shape[0], J, 2), dtype=np.float32)

        source_fps = float(fps) or CANONICAL_FPS
        max_source_gap_ms = 0.0
        resampled_30hz = False
        if timestamps is not None:
            src_times = np.asarray(timestamps, dtype=np.float64)
            if src_times.shape != (joints.shape[0],):
                raise ValueError(
                    f"timestamps shape {src_times.shape} != ({joints.shape[0]},)"
                )
            gaps = np.diff(src_times)
            if gaps.size:
                if not np.all(gaps > 0):
                    raise ValueError("timestamps must be strictly increasing")
                max_source_gap_ms = float(gaps.max() * 1000.0)
                source_fps = float(gaps.size / (src_times[-1] - src_times[0]))
            dst_times = src_times[-1] - np.arange(T_win - 1, -1, -1) / CANONICAL_FPS
            joints = resample_at_times(joints, src_times, dst_times)
            conf = resample_at_times(conf, src_times, dst_times)
            if mp_2d is not None:
                mp_2d = resample_at_times(mp_2d, src_times, dst_times)
            resampled_30hz = True
            fps = CANONICAL_FPS

        # Training pairs are stored in viewer convention (Y-up, Z flipped), while
        # the live browser sends raw MediaPipe world landmarks.
        model_joints = joints.copy()
        model_joints[..., 1:] *= -1.0
        feats = build_feature_sequence(
            model_joints,
            conf,
            poses_2d_norm=mp_2d,
            fps=float(fps) or CANONICAL_FPS,
        )
        feats = apply_feature_ablation(
            feats,
            zero_accel=bool(entry.get("zero_accel", False)),
            zero_2d=bool(entry.get("zero_2d", False)),
            zero_ipsi=bool(entry.get("zero_ipsi", False)),
            zero_bones=bool(entry.get("zero_bones", False)),
            zero_inv_conf=bool(entry.get("zero_inv_conf", False)),
            multilag=bool(entry.get("multilag", False)),
            multilag_steps=tuple(entry.get("multilag_steps") or (1, 3, 6)),
            multilag_mode=str(entry.get("multilag_mode", "mean")),
        )
        if feats.shape[-1] != entry["F"]:
            raise ValueError(
                f"feature dim {feats.shape[-1]} != checkpoint F={entry['F']}"
            )

        t = joints.shape[0] - 1
        start = max(0, t - T_win + 1)
        window = feats[start : t + 1]
        if window.shape[0] < T_win:
            pad = np.repeat(window[:1], T_win - window.shape[0], axis=0)
            window = np.concatenate([pad, window], axis=0)

        with self._lock:
            with torch.no_grad():
                x = torch.from_numpy(window[None].astype(np.float32)).to(device)
                delta = take_delta_last(model(x)["delta"])[0].cpu().numpy()

        gated = False
        pose_in = model_joints[t]
        if apply_gate:
            if (
                float(conf[t, TARGET_IDX].mean()) >= entry["gate_conf"]
                and float(np.linalg.norm(delta)) < entry["gate_eps"]
            ):
                gated = True
                pose_out = pose_in.copy()
            else:
                pose_out = self.apply_delta(pose_in, delta)
        else:
            pose_out = self.apply_delta(pose_in, delta)

        pose_out_raw = pose_out.copy()
        pose_out_raw[..., 1:] *= -1.0
        mean_displacement = float(
            np.linalg.norm(pose_out_raw[TARGET_IDX] - joints[t, TARGET_IDX], axis=-1).mean()
        )

        ms = (time.perf_counter() - t0) * 1000.0
        return {
            "joints": pose_out_raw.astype(np.float32).tolist(),
            "raw_joints": joints[t].astype(np.float32).tolist(),
            "delta": delta.astype(np.float32).tolist(),
            "delta_norm": float(np.linalg.norm(delta)),
            "mean_displacement": mean_displacement,
            "gated": gated,
            "ms": round(ms, 2),
            "T": T_win,
            "F": entry["F"],
            "checkpoint": ckpt_id,
            "input_fps": source_fps,
            "inference_fps": CANONICAL_FPS,
            "resampled_30hz": resampled_30hz,
            "max_source_gap_ms": max_source_gap_ms,
        }


RUNTIME = CorrectorRuntime()


# ---------------------------------------------------------------------------
# Live NLF-S (TorchScript fast path)
# ---------------------------------------------------------------------------


class NlfRuntime:
    """Lazy NLF-S fast path: YOLOv8n sticky crop + estimate_poses_batched (no NLF YOLO-x / fit)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._model = None
        self._weights = None
        self._weights_dense = None
        self._dense = False
        self._n_x55 = 55
        self._n_surf = 1024
        self._hand_surf_idx: dict[str, list[int]] = {}
        self._device = "cpu"
        self._model_path = LAB_ROOT / "data" / "models" / "nlf" / "nlf_s_multi_0.2.2.torchscript"
        self._ready = False
        self._error: str | None = None
        self._tracker = None
        self._detector = None
        self._ws_url: str | None = None
        self._engine = None
        self._backend = "auto"
        self._backend_forced = False
        self._no_cache = False
        self._calibrated = False
        self._rebalanced = 0
        self._last_rebal = 0.0
        self._rebal_lock = threading.Lock()
        # Server-level latency baseline (JPEG decode + box plumbing + infer) used
        # by the runtime rebalance monitor — the calibration baseline measures
        # only the bare pose path and would false-positive on steady-state.
        self._monitor_baseline: dict = {}

    @property
    def ready(self) -> bool:
        return self._ready

    def status(self) -> dict:
        return {
            "ready": self._ready,
            "device": self._device,
            "model": str(self._model_path.relative_to(LAB_ROOT).as_posix())
            if self._model_path.is_file()
            else str(self._model_path),
            "error": self._error,
            "ws_url": self._ws_url,
            "crop": "yolov8n_sticky",
            "nlf_query": "x55+surface1024" if self._dense else "smplx55",
            "dense": self._dense,
            "backend": self._engine.backend if self._engine is not None else "torch",
            "backend_calibrated": self._calibrated,
            "backend_baseline": (self._engine.baseline if self._engine is not None else {}),
            "backend_candidates": self._measured_backends(),
            "backend_rebalanced": self._rebalanced,
        }

    def _measured_backends(self) -> dict:
        """The full measured table (backend -> p50/p95) from the calibration cache,
        so the viewer can show how the winner was chosen."""
        try:
            from nlf_engine import load_backend_choice  # type: ignore

            c = load_backend_choice()
            bl = (c or {}).get("baseline") or {}
            return {k: v for k, v in bl.items() if isinstance(v, dict) and v.get("p50")}
        except Exception:
            return {}

    def load(self, device: str | None = None, backend: str | None = None) -> dict:
        import torch

        with self._lock:
            if self._ready and self._model is not None:
                return self.status()
            if not self._model_path.is_file():
                self._error = f"missing model {self._model_path}"
                raise FileNotFoundError(self._error)
            sys.path.insert(0, str(LAB_ROOT / "scripts"))
            from nlf_bbox_track import StickyBBox, YoloNanoPerson  # type: ignore
            from nlf_fast_path import get_joint_weights, load_nlf  # type: ignore

            want = device or ("cuda" if torch.cuda.is_available() else "cpu")
            self._device = want
            self._model = load_nlf(self._model_path, want)
            # SMPL-X55: body + eyes/jaw + finger knuckles — live default (not the 1024 surface).
            self._weights, _ = get_joint_weights(self._model, "smplx55")
            self._weights_dense = None
            self._dense = False
            self._tracker = StickyBBox(detect_every=6, expand=1.25)
            self._detector = YoloNanoPerson(device=want, imgsz=320)
            self._detector.load()
            # Accelerated features backend (trt/dml/ov/ort/torch) — build failure
            # is non-fatal: the server keeps working on the reference torch path.
            self._backend = backend or self._backend
            self._backend_forced = bool(backend and backend != "auto")
            self._engine = None
            try:
                from nlf_engine import NlfFeatureEngine, calibrate_backend

                if self._backend == "auto":
                    name, engine, baseline = calibrate_backend(
                        self._model, self._weights, want, use_cache=not self._no_cache
                    )
                    self._engine = engine
                    self._calibrated = True
                    sys.stderr.write(
                        f"[lab] NLF features backend: {name} (measured; baseline p50 {baseline.get('p50', float('nan')):.1f} ms)\n"
                    )
                else:
                    self._engine = NlfFeatureEngine(self._model, self._weights, backend=self._backend, device=want)
                    sys.stderr.write(f"[lab] NLF features backend: {self._engine.backend} (device={self._engine.device})\n")
                # Warm the engine (CUDA context, TRT first run, decode kernels) so
                # the first live frame doesn't pay a ~1s cold start.
                import numpy as np

                self._engine.infer(np.zeros((256, 256, 3), dtype=np.uint8))
            except Exception as e:
                self._engine = None
                sys.stderr.write(f"[lab] NLF engine unavailable ({type(e).__name__}: {e}); using torch path\n")
            self._ready = True
            self._error = None
            # Server-level monitor baseline: full pose path incl. JPEG decode, so
            # steady-state never trips the rebalance (calibration p50 is the bare
            # engine path, ~4-5 ms lower). Also give the system a 2 min grace
            # window after load before any rebalance can fire (cold start noise).
            self._monitor_baseline = {}
            self._last_rebal = time.time()
            if self._engine is not None:
                try:
                    import cv2
                    import numpy as np

                    dummy = np.zeros((540, 960, 3), dtype=np.uint8)
                    okj, buf = cv2.imencode(".jpg", dummy, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
                    box = torch.tensor([[100.0, 100.0, 760.0, 340.0]])
                    # Warm first (one-time CUDA/decode init) so the measured
                    # window reflects steady state, not a 470 ms cold spike.
                    for _ in range(2):
                        bgr = cv2.imdecode(buf, cv2.IMREAD_COLOR)
                        self._engine.infer(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), box)
                    ms = []
                    for _ in range(6):
                        t0 = time.perf_counter()
                        bgr = cv2.imdecode(buf, cv2.IMREAD_COLOR)
                        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                        self._engine.infer(rgb, box)
                        ms.append((time.perf_counter() - t0) * 1000.0)
                    a = np.asarray(ms)
                    self._monitor_baseline = {
                        "p50": float(np.median(a)),
                        "p95": float(np.percentile(a, 95)),
                    }
                    sys.stderr.write(
                        f"[lab] NLF monitor baseline (server path): p50 {self._monitor_baseline['p50']:.1f} ms | "
                        f"p95 {self._monitor_baseline['p95']:.1f} ms\n"
                    )
                except Exception as e:
                    sys.stderr.write(f"[lab] monitor baseline failed: {e}\n")
            sys.stderr.write(f"[lab] NLF-S + YOLOv8n sticky crop on {want} (query=smplx55)\n")
            return self.status()

    def rebalance_if_degraded(self, mean_ms: float, p95_ms: float, drop_rate: float) -> None:
        """Runtime backend rebalancing: if the active engine is degraded vs its
        server-level baseline (thermal throttling, another app on the GPU, driver
        fallback), trigger an async re-bench + hot-swap. Guarded by a lock + 120 s
        backoff so a single hiccup never swaps. The re-bench runs on a background
        thread so the pose path keeps serving during it (no stall/timeouts)."""
        if self._backend_forced or self._engine is None:
            return
        with self._rebal_lock:
            now = time.time()
            if now - self._last_rebal < 120.0:
                return
            bl = self._monitor_baseline or (self._engine.baseline if self._engine is not None else {})
            bl_p50 = float(bl.get("p50") or mean_ms)
            bl_p95 = float(bl.get("p95") or p95_ms)
            if mean_ms <= 1.5 * bl_p50 and p95_ms <= 1.6 * bl_p95 and drop_rate < 0.15:
                self._last_rebal = now
                return
            self._last_rebal = now
            sys.stderr.write(
                f"[lab] NLF backend degraded (mean {mean_ms:.1f} ms vs baseline {bl_p50:.1f}, "
                f"p95 {p95_ms:.1f} vs {bl_p95:.1f}, drop {drop_rate:.0%}) — rebalancing async\n"
            )
            threading.Thread(target=self._do_rebalance, daemon=True, name="nlf-rebalance").start()

    def _do_rebalance(self) -> None:
        """Re-bench all loadable backends (fresh engines) and hot-swap the live
        engine if a different backend is now meaningfully faster."""
        try:
            from nlf_engine import NlfFeatureEngine, available_backends

            weights = self._weights_dense if self._dense and self._weights_dense is not None else self._weights
            results: dict[str, dict] = {}
            engines: dict[str, NlfFeatureEngine] = {}
            for name in available_backends(self._device):
                try:
                    e = NlfFeatureEngine(self._model, weights, name, self._device)
                    engines[name] = e
                    results[name] = e.bench_ms(n=5)
                except Exception as ex:
                    sys.stderr.write(f"[lab] rebalance {name} failed: {ex}\n")
            if not results:
                return
            best = min(results, key=lambda k: results[k]["p50"])
            eng = self._engine
            if eng is None:
                return
            cur = eng.backend
            if best != cur and results[best]["p50"] < 0.95 * results.get(cur, results[best])["p50"]:
                eng.set_backend(best)
                eng.baseline = dict(results[best])
                self._rebalanced += 1
                sys.stderr.write(
                    f"[lab] NLF backend rebalanced: {cur} -> {best} (p50 {results[best]['p50']:.1f} ms)\n"
                )
            else:
                sys.stderr.write(
                    f"[lab] NLF backend recheck: keeping {cur} (p50 {results[cur]['p50']:.1f} ms)\n"
                )
            engines.clear()  # drop non-winner sessions
        except Exception as e:
            sys.stderr.write(f"[lab] rebalance failed: {e}\n")

    def set_dense(self, enabled: bool) -> dict:
        """Switch live query between 55 SMPL-X joints and 55+1024 surface points."""
        if not self._ready:
            self.load()
        with self._lock:
            self._dense = bool(enabled)
            if self._dense and self._weights_dense is None:
                sys.path.insert(0, str(LAB_ROOT / "scripts"))
                from nlf_fast_path import smpl24_hand_surface_indices, x55_plus_surface_weights  # type: ignore

                self._weights_dense, self._n_x55, self._n_surf = x55_plus_surface_weights(self._model)
                self._hand_surf_idx = smpl24_hand_surface_indices(self._model)
                if self._engine is not None:
                    self._engine.update_weights(self._weights_dense)
                sys.stderr.write(
                    f"[lab] NLF dense weights ready x55={self._n_x55} surface={self._n_surf}\n"
                )
            sys.stderr.write(f"[lab] NLF query={'x55+surface1024' if self._dense else 'smplx55'}\n")
            return self.status()

    def infer_rgb(
        self,
        rgb_u8: np.ndarray,
        *,
        box: torch.Tensor | None = None,
        skip_detect: bool = False,
    ) -> dict:
        """rgb HWC uint8 → lab joints metres, OpenCV-ish (same as MediaPipe disk).

        box=xywh [1,4] tensor + skip_detect=True is the async-path entry: the
        caller (AsyncPoseWorker) already ran the sticky tracker / detection.
        """
        import torch

        from pose_lab.skeleton import JOINT_TO_IDX, smplx55_avatar_aux_json, smplx55_to_lab

        if not self._ready:
            self.load()
        assert self._model is not None and self._weights is not None
        assert self._tracker is not None and self._detector is not None
        sys.path.insert(0, str(LAB_ROOT / "scripts"))
        from nlf_fast_path import SMPLX55_JOINT_NAMES, estimate_joints24  # type: ignore

        h, w = rgb_u8.shape[:2]
        t0 = time.perf_counter()
        det_ms = 0.0
        detected = None
        ran_det = False
        if skip_detect:
            assert box is not None, "skip_detect requires a caller-supplied box"
            box = box.detach().to(self._device).float()
        else:
            if self._tracker.needs_detect():
                ran_det = True
                td = time.perf_counter()
                detected = self._detector.detect_xywh(rgb_u8)
                if self._device.startswith("cuda"):
                    torch.cuda.synchronize()
                det_ms = (time.perf_counter() - td) * 1000.0
            xywh = self._tracker.update(h, w, detected)
            box = self._tracker.as_torch(xywh, self._device)

        dense = self._dense
        weights = self._weights_dense if dense and self._weights_dense is not None else self._weights
        with torch.inference_mode():
            if self._engine is not None:
                pred = self._engine.infer(rgb_u8, box)
            else:
                pred = estimate_joints24(
                    self._model,
                    rgb_u8,
                    weights,
                    device=self._device,
                    num_aug=1,
                    box=box,
                )
        if self._device.startswith("cuda"):
            torch.cuda.synchronize()
        ms = (time.perf_counter() - t0) * 1000.0
        if pred is None:
            return {
                "ok": False,
                "error": "no person",
                "ms": round(ms, 2),
                "det_ms": round(det_ms, 2),
                "detected": ran_det,
                "box": [float(x) for x in box[0, :4].tolist()],
            }

        pts_m = np.asarray(pred, dtype=np.float64) / 1000.0
        n_x55 = int(self._n_x55) if dense else 55
        if pts_m.shape[0] < n_x55:
            return {"ok": False, "error": f"short nlf pred {pts_m.shape}", "ms": round(ms, 2)}
        j55_m = pts_m[:n_x55] - pts_m[0:1]
        surf_m = None
        if dense and pts_m.shape[0] >= n_x55 + int(self._n_surf):
            surf_m = pts_m[n_x55 : n_x55 + int(self._n_surf)] - pts_m[0:1]
        lab = smplx55_to_lab(j55_m).astype(np.float32)
        aux_smpl = smplx55_avatar_aux_json(j55_m)
        out = {
            "ok": True,
            "joints": lab.tolist(),
            # Preserve camera translation separately from the established
            # root-relative retarget payload. Locomotion needs this information.
            "camera_joints": smplx55_to_lab(pts_m[:n_x55]).astype(np.float32).tolist(),
            "image_size": [w, h],
            "camera_fov": 55.0,
            "aux_smpl": aux_smpl,
            "smplx55": np.round(j55_m, 5).tolist(),
            "smplx55_names": list(SMPLX55_JOINT_NAMES),
            "nlf_query": "x55+surface1024" if surf_m is not None else "smplx55",
            "joint_names": LAB_JOINTS,
            "ms": round(ms, 2),
            "nlf_ms": round(ms - det_ms, 2),
            "det_ms": round(det_ms, 2),
            "detected": ran_det,
            "box": [float(x) for x in box[0, :4].tolist()],
            "device": self._device,
            "units": "metres",
            "space": "opencv_ish_root",
            "crop": "yolov8n_sticky",
        }
        if surf_m is not None:
            out["surface1024"] = np.round(surf_m, 4).tolist()
            out["surface_hand_idx"] = self._hand_surf_idx
        return out


NLF_RUNTIME = NlfRuntime()

# Binary WS frame: magic "NLF1" + u32 LE frame_id + JPEG bytes
NLF_WS_MAGIC = b"NLF1"


def _decode_nlf_ws_frame(payload: bytes) -> tuple[int | None, bytes]:
    if len(payload) >= 8 and payload[:4] == NLF_WS_MAGIC:
        frame_id = int.from_bytes(payload[4:8], "little", signed=False)
        return frame_id, payload[8:]
    return None, payload


def start_nlf_websocket(host: str, port: int) -> str:
    """Background asyncio websockets server; returns ws URL.

    Pose frames go through an AsyncPoseWorker (decode/detect/infer off the event
    loop, latest-frame-wins) — the WS handler only enqueues and a background
    sender task drains results.
    """
    import asyncio

    import websockets
    from websockets.asyncio.server import serve

    from nlf_engine import AsyncPoseWorker

    ws_url = f"ws://{host}:{port}/nlf"
    NLF_RUNTIME._ws_url = ws_url

    async def _send_result(websocket, worker: AsyncPoseWorker) -> None:
        try:
            while True:
                result = await worker.get()
                await websocket.send(json.dumps(result))
        except websockets.exceptions.ConnectionClosed:
            return
        except Exception:
            return

    async def handler(websocket):
        path = getattr(websocket, "request", None)
        req_path = getattr(path, "path", "/") if path is not None else "/"
        if req_path not in ("/nlf", "/", "/nlf/"):
            await websocket.close(1008, "use /nlf")
            return
        worker = AsyncPoseWorker(NLF_RUNTIME)
        worker.attach_loop(asyncio.get_running_loop())
        worker.start()
        sender = asyncio.create_task(_send_result(websocket, worker))
        try:
            async for message in websocket:
                if isinstance(message, str):
                    if message.strip().lower() in ("ping", "warmup"):
                        try:
                            st = NLF_RUNTIME.load()
                            await websocket.send(json.dumps({"ok": True, "type": "warmup", **st}))
                        except Exception as e:
                            await websocket.send(json.dumps({"ok": False, "error": str(e)}))
                    elif message.strip().lower() in ("dense", "dense_on"):
                        st = NLF_RUNTIME.set_dense(True)
                        await websocket.send(json.dumps({"ok": True, "type": "query", **st}))
                    elif message.strip().lower() in ("x55", "dense_off"):
                        st = NLF_RUNTIME.set_dense(False)
                        await websocket.send(json.dumps({"ok": True, "type": "query", **st}))
                    continue
                frame_id, jpeg = _decode_nlf_ws_frame(message)
                if not jpeg:
                    await websocket.send(json.dumps({"ok": False, "error": "empty frame"}))
                    continue
                worker.submit(frame_id, jpeg)
        except websockets.exceptions.ConnectionClosed:
            return
        finally:
            sender.cancel()

    async def runner():
        async with serve(handler, host, port, max_size=8 * 1024 * 1024):
            sys.stderr.write(f"[lab] NLF WebSocket {ws_url}\n")
            await asyncio.Future()

    def thread_main():
        asyncio.run(runner())

    t = threading.Thread(target=thread_main, name="nlf-ws", daemon=True)
    t.start()
    return ws_url


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------


class Handler(SimpleHTTPRequestHandler):
    default_source: str = "corrected"
    default_clip: str = ""

    def translate_path(self, path: str) -> str:
        parsed = urlparse(path)
        p = parsed.path
        if p in ("/", "/index.html"):
            return str(VIEWER_DIR / "index.html")
        if p in ("/live", "/live.html"):
            return str(VIEWER_DIR / "live.html")
        if p in ("/bake", "/bake_seq"):
            return str(VIEWER_DIR / "avatar_bake_seq.html")
        if p.startswith("/static/"):
            return str(VIEWER_DIR / unquote(p[len("/static/") :]))
        # Baked pose sequences + the /watch preview page and its videos. Without
        # these, /bake_seq?pose=/poses/... fell through to the index.html
        # fallback below and the viewer died parsing HTML as JSON.
        if p.startswith("/poses/"):
            return str(LAB_ROOT / "experiments" / "bake_top" / unquote(p[len("/poses/") :]))
        if p in ("/watch", "/watch.html"):
            return str(LAB_ROOT / "experiments" / "watch.html")
        if p.startswith("/experiments/"):
            return str(LAB_ROOT / "experiments" / unquote(p[len("/experiments/") :]))
        if p.startswith("/compare/"):
            return str(LAB_ROOT / "data" / "compare" / unquote(p[len("/compare/") :]))
        if p.startswith("/assets/"):
            return str(ASSETS_DIR / unquote(p[len("/assets/") :]))
        # /media/<source>/<clip>/file
        if p.startswith("/media/"):
            rel = unquote(p[len("/media/") :])
            parts = rel.split("/", 2)
            if len(parts) >= 2 and parts[0] in SOURCE_ROOTS:
                source, rest = parts[0], "/".join(parts[1:])
                return str(SOURCE_ROOTS[source] / rest)
            # Legacy: /media/<clip>/file → default source root
            return str(SOURCE_ROOTS.get(Handler.default_source, SOURCE_ROOTS["mediapipe"]) / rel)
        return str(VIEWER_DIR / "index.html")

    def end_headers(self):
        path = urlparse(self.path).path
        if (
            path in ("/", "/index.html", "/live", "/live.html")
            or path.startswith("/api/")
            or path.startswith("/static/")
        ):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _json(self, obj: dict | list, status: int = 200) -> None:
        body = json.dumps(obj).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            # Client navigated away / aborted a slow NLF pose request.
            return

    def _read_json(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    def _send_overlay(self, clip: str, root: Path, source: str, label: str) -> None:
        clip_dir = root / clip
        try:
            data = payload_bytes_for_clip(clip_dir, source)
        except FileNotFoundError as e:
            self.send_error(404, str(e))
            return
        except Exception as e:
            self.send_error(500, f"{label} overlay failed: {e}")
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Frame-Id")
        self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/correct":
            try:
                body = self._read_json()
                ckpt = body.get("checkpoint") or body.get("ckpt") or ""
                if not ckpt:
                    # Prefer baseline best_hard
                    discovered = discover_checkpoints()
                    pref = next((d for d in discovered if d["preferred"]), None)
                    if not pref and discovered:
                        pref = discovered[0]
                    if not pref:
                        self._json({"error": "no checkpoints found under runs/"}, 404)
                        return
                    ckpt = pref["id"]
                joints = np.asarray(body["joints"], dtype=np.float32)
                conf = np.asarray(body.get("conf") or np.ones(joints.shape[:2]), dtype=np.float32)
                j2 = body.get("joints_2d")
                joints_2d = np.asarray(j2, dtype=np.float32) if j2 is not None else None
                ts = body.get("timestamps")
                timestamps = np.asarray(ts, dtype=np.float64) if ts is not None else None
                fps = float(body.get("fps") or CANONICAL_FPS)
                frame_id = body.get("frame_id")
                apply_gate = bool(body.get("apply_gate", True))
                result = RUNTIME.correct(
                    ckpt,
                    joints,
                    conf,
                    joints_2d,
                    fps,
                    apply_gate,
                    timestamps,
                )
                result["frame_id"] = frame_id
                self._json(result)
            except FileNotFoundError as e:
                self._json({"error": str(e)}, 404)
            except Exception as e:
                sys.stderr.write("[lab] /api/correct error:\n" + traceback.format_exc())
                self._json({"error": str(e)}, 500)
            return
        if parsed.path == "/api/warmup":
            try:
                body = self._read_json()
                ckpt = body.get("checkpoint") or ""
                if not ckpt:
                    discovered = discover_checkpoints()
                    pref = next((d for d in discovered if d["preferred"]), None)
                    ckpt = (pref or discovered[0])["id"] if discovered else ""
                if not ckpt:
                    self._json({"error": "no checkpoints"}, 404)
                    return
                entry = RUNTIME.load(ckpt)
                self._json(
                    {
                        "ok": True,
                        "checkpoint": ckpt,
                        "F": entry["F"],
                        "T": entry["T"],
                        "device": str(entry["device"]),
                        "zero_accel": entry["zero_accel"],
                        "zero_2d": entry["zero_2d"],
                    }
                )
            except Exception as e:
                self._json({"error": str(e)}, 500)
            return
        if parsed.path == "/api/nlf_warmup":
            try:
                body = self._read_json() if int(self.headers.get("Content-Length") or 0) else {}
                device = (body or {}).get("device")
                self._json({"ok": True, **NLF_RUNTIME.load(device)})
            except Exception as e:
                sys.stderr.write("[lab] /api/nlf_warmup error:\n" + traceback.format_exc())
                self._json({"error": str(e), **NLF_RUNTIME.status()}, 500)
            return
        if parsed.path == "/api/nlf_pose":
            try:
                import base64

                import cv2

                n = int(self.headers.get("Content-Length") or 0)
                frame_id = self.headers.get("X-Frame-Id")
                payload = self.rfile.read(n) if n else b""
                # Prefer raw JPEG (blob upload). Sniff SOI marker — do not UTF-8-decode binary.
                if len(payload) >= 3 and payload[:2] == b"\xff\xd8":
                    raw = payload
                else:
                    try:
                        body = json.loads(payload.decode("utf-8") if payload else "{}")
                    except UnicodeDecodeError:
                        self._json(
                            {"error": "expected image/jpeg body or JSON with image_b64"},
                            400,
                        )
                        return
                    frame_id = body.get("frame_id", frame_id)
                    b64 = body.get("image_b64") or body.get("jpeg_b64") or ""
                    if not b64:
                        self._json({"error": "missing image (raw jpeg or image_b64)"}, 400)
                        return
                    if "," in b64:
                        b64 = b64.split(",", 1)[1]
                    raw = base64.b64decode(b64)
                if not raw:
                    self._json({"error": "empty image body"}, 400)
                    return
                arr = np.frombuffer(raw, dtype=np.uint8)
                bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if bgr is None:
                    self._json({"error": "jpeg decode failed"}, 400)
                    return
                # Client already downscales; clamp again if a huge frame sneaks in.
                h, w = bgr.shape[:2]
                max_side = 512
                m = max(h, w)
                if m > max_side:
                    s = max_side / float(m)
                    bgr = cv2.resize(
                        bgr, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA
                    )
                rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                result = NLF_RUNTIME.infer_rgb(rgb)
                result["frame_id"] = frame_id
                self._json(result)
            except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                return
            except Exception as e:
                sys.stderr.write("[lab] /api/nlf_pose error:\n" + traceback.format_exc())
                try:
                    self._json({"error": str(e)}, 500)
                except Exception:
                    return
            return
        self.send_error(404)

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)

        if parsed.path in ("/api/shadow.json", "/api/shadow"):
            clip = qs.get("clip", [Handler.default_clip])[0]
            self._send_overlay(clip, SOURCE_ROOTS["mediapipe"], "mediapipe", "shadow")
            return

        if parsed.path in ("/api/corrected_shadow.json", "/api/corrected_shadow"):
            clip = qs.get("clip", [Handler.default_clip])[0]
            self._send_overlay(clip, SOURCE_ROOTS["corrected"], "corrected", "corrected_shadow")
            return

        if parsed.path == "/api/nlf_status":
            self._json(NLF_RUNTIME.status())
            return

        if parsed.path in ("/api/teacher.json", "/api/teacher_shadow.json"):
            clip = qs.get("clip", [Handler.default_clip])[0]
            self._send_overlay(
                clip, SOURCE_ROOTS["teacher_aligned"], "teacher_aligned", "teacher"
            )
            return

        if parsed.path == "/api/training-oracle.json":
            clip = qs.get("clip", [Handler.default_clip])[0]
            try:
                self._json(training_oracle_payload(clip))
            except FileNotFoundError as e:
                self._json({"error": str(e)}, 404)
            except Exception as e:
                sys.stderr.write("[lab] training oracle error:\n" + traceback.format_exc())
                self._json({"error": str(e)}, 500)
            return

        if parsed.path == "/api/pose-aux.json":
            # Pose-33 subset (head + palms) from MediaPipe landmarks33_world, viewer YZ flip.
            clip = qs.get("clip", [Handler.default_clip])[0]
            mp_dir = SOURCE_ROOTS["mediapipe"] / clip
            npy = mp_dir / "landmarks33_world.npy"
            if not npy.is_file():
                self._json({"error": f"no landmarks33_world for {clip}"}, 404)
                return
            try:
                full = np.load(npy)
                if full.ndim != 3 or full.shape[-1] != 3 or full.shape[1] < 23:
                    self._json({"error": f"bad landmarks33 shape {full.shape}"}, 500)
                    return
                names = [
                    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
                    "left_wrist", "right_wrist",
                    "left_pinky", "right_pinky", "left_index", "right_index",
                    "left_thumb", "right_thumb",
                ]
                idx = [0, 2, 5, 7, 8, 15, 16, 17, 18, 19, 20, 21, 22]
                pts = full[:, idx, :].astype(np.float64).copy()
                pts[..., 1] *= -1.0
                pts[..., 2] *= -1.0
                self._json({
                    "source": "mediapipe",
                    "names": names,
                    "indices": idx,
                    "n_frames": int(pts.shape[0]),
                    "frames": pts.astype(np.float32).tolist(),
                })
            except Exception as e:
                sys.stderr.write("[lab] pose-aux error:\n" + traceback.format_exc())
                self._json({"error": str(e)}, 500)
            return

        if parsed.path == "/api/sources":
            sources = []
            for key, root in SOURCE_ROOTS.items():
                clips = list_ready_clips(root)
                sources.append(
                    {
                        "id": key,
                        "label": SOURCE_LABELS.get(key, key),
                        "n_clips": len(clips),
                        "root": str(root.relative_to(LAB_ROOT).as_posix()),
                    }
                )
            self._json({"sources": sources, "default": Handler.default_source})
            return

        if parsed.path == "/api/clips":
            source = qs.get("source", [Handler.default_source])[0]
            if source not in SOURCE_ROOTS:
                self._json({"error": f"unknown source {source}"}, 400)
                return
            clips = list_ready_clips(SOURCE_ROOTS[source])
            current = Handler.default_clip if Handler.default_clip in clips else (clips[0] if clips else "")
            self._json(
                {
                    "clips": clips,
                    "current": current,
                    "source": source,
                    "label": SOURCE_LABELS.get(source, source),
                    "sources": [
                        {
                            "id": k,
                            "label": SOURCE_LABELS[k],
                            "n_clips": len(list_ready_clips(SOURCE_ROOTS[k])),
                        }
                        for k in SOURCE_ROOTS
                    ],
                }
            )
            return

        if parsed.path == "/api/payload.json":
            source = qs.get("source", [Handler.default_source])[0]
            clip = qs.get("clip", [Handler.default_clip])[0]
            if source not in SOURCE_ROOTS:
                self.send_error(400, f"unknown source {source}")
                return
            clip_dir = SOURCE_ROOTS[source] / clip
            try:
                data = payload_bytes_for_clip(clip_dir, source)
            except FileNotFoundError as e:
                self.send_error(404, str(e))
                return
            except Exception as e:
                self.send_error(500, f"payload build failed: {e}")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        if parsed.path == "/api/checkpoints":
            ckpts = discover_checkpoints()
            default = next((c["id"] for c in ckpts if c["preferred"]), None)
            if default is None and ckpts:
                default = ckpts[0]["id"]
            self._json(
                {
                    "checkpoints": ckpts,
                    "default": default,
                    "joint_names": LAB_JOINTS,
                    "bones": [{"a": a, "b": b} for a, b in LAB_BONES],
                }
            )
            return

        if parsed.path == "/api/skeleton":
            self._json(
                {
                    "joint_names": LAB_JOINTS,
                    "bones": [{"a": a, "b": b} for a, b in LAB_BONES],
                }
            )
            return

        return SimpleHTTPRequestHandler.do_GET(self)

    def log_message(self, fmt, *args):
        sys.stderr.write("[lab] " + (fmt % args) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--clip", default="", help="Default clip id")
    ap.add_argument(
        "--source",
        choices=tuple(SOURCE_ROOTS.keys()),
        default="corrected",
        help="Default offline source",
    )
    ap.add_argument("--port", type=int, default=8780)
    ap.add_argument("--ws-port", type=int, default=0, help="NLF WebSocket port (default: HTTP+1)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument(
        "--backend",
        default="auto",
        help="NLF features backend: auto (measured) | torch | trt | dml | ov | ort",
    )
    ap.add_argument(
        "--no-cache",
        action="store_true",
        help="Skip the per-hardware backend cache and re-measure on this boot",
    )
    ap.add_argument("--warmup", action="store_true", help="Preload preferred checkpoint")
    args = ap.parse_args()

    Handler.default_source = args.source
    NLF_RUNTIME._backend = args.backend
    NLF_RUNTIME._no_cache = args.no_cache
    root = SOURCE_ROOTS[args.source]
    clips = list_ready_clips(root)
    clip = args.clip or (clips[0] if clips else "")
    Handler.default_clip = clip

    mimetypes.add_type("video/mp4", ".mp4")
    mimetypes.add_type("application/wasm", ".wasm")

    if args.warmup:
        discovered = discover_checkpoints()
        pref = next((d for d in discovered if d["preferred"]), None)
        if pref:
            try:
                RUNTIME.load(pref["id"])
            except Exception as e:
                print(f"[lab] warmup failed: {e}", file=sys.stderr)

    ws_port = args.ws_port or (args.port + 1)
    ws_url = start_nlf_websocket(args.host, ws_port)

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    base = f"http://{args.host}:{args.port}"
    print("=" * 60, flush=True)
    print("Pose Corrector Lab — unified server", flush=True)
    print(f"  Offline:  {base}/?source={args.source}" + (f"&clip={clip}" if clip else ""), flush=True)
    print(f"  Live:     {base}/live", flush=True)
    print(f"  NLF WS:   {ws_url}  (binary JPEG)", flush=True)
    print(f"  Default source: {args.source} ({len(clips)} clips)", flush=True)
    print("  Checkpoints: lazy via /api/checkpoints", flush=True)
    print("=" * 60, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
