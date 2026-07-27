#!/usr/bin/env python3
"""Unified Pose Lab: multi-source offline viewer + live webcam corrector.

Usage:
  python scripts/serve_lab.py
  → http://127.0.0.1:8780/          (offline clips, source toggle)
  → http://127.0.0.1:8780/live      (webcam + MediaPipe + corrector)

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

from pose_lab.data import apply_feature_ablation  # noqa: E402
from pose_lab.features import build_feature_sequence, feature_dim  # noqa: E402
from pose_lab.io import (  # noqa: E402
    build_viewer_payload_from_clip,
    clip_has_joints,
    resolve_clip_fps,
)
from pose_lab.models import build_model  # noqa: E402
from pose_lab.skeleton import (  # noqa: E402
    DELTA_DIM,
    LAB_BONES,
    LAB_JOINTS,
    N_TARGETS,
    TARGET_IDX,
)
from pose_lab.timebase import CANONICAL_FPS, resample_at_times  # noqa: E402

VIEWER_DIR = LAB_ROOT / "viewer"
RUNS_DIR = LAB_ROOT / "runs"

SOURCE_ROOTS: dict[str, Path] = {
    "teacher": LAB_ROOT / "data" / "teacher",
    "mediapipe": LAB_ROOT / "data" / "mediapipe",
    "corrected": LAB_ROOT / "data" / "corrected",
    "teacher_aligned": LAB_ROOT / "data" / "teacher_aligned",
}

SOURCE_LABELS = {
    "mediapipe": "MediaPipe",
    "teacher": "Teacher",
    "teacher_aligned": "Teacher aligned",
    "corrected": "Corrector exportado",
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
    payload["source"] = source
    return json.dumps(payload).encode("utf-8")


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
                    "zero_accel": bool(fcfg.get("zero_accel", False)),
                    "zero_2d": bool(fcfg.get("zero_2d", False)),
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
                "zero_accel": bool(fcfg.get("zero_accel", False)),
                "zero_2d": bool(fcfg.get("zero_2d", False)),
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
            feats, zero_accel=entry["zero_accel"], zero_2d=entry["zero_2d"]
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
                delta = model(x)["delta"][0].cpu().numpy()

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
        if p.startswith("/static/"):
            return str(VIEWER_DIR / p[len("/static/") :])
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
        if path in ("/", "/index.html", "/live", "/live.html") or path.startswith("/api/"):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _json(self, obj: dict | list, status: int = 200) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
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
        self.send_error(404)

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)

        if parsed.path in ("/api/shadow.json", "/api/shadow"):
            clip = qs.get("clip", [Handler.default_clip])[0]
            self._send_overlay(clip, SOURCE_ROOTS["mediapipe"], "mediapipe", "shadow")
            return

        if parsed.path in ("/api/teacher.json", "/api/teacher_shadow.json"):
            clip = qs.get("clip", [Handler.default_clip])[0]
            self._send_overlay(
                clip, SOURCE_ROOTS["teacher_aligned"], "teacher_aligned", "teacher"
            )
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
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--warmup", action="store_true", help="Preload preferred checkpoint")
    args = ap.parse_args()

    Handler.default_source = args.source
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

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    base = f"http://{args.host}:{args.port}"
    print("=" * 60)
    print("Pose Corrector Lab — unified server")
    print(f"  Offline:  {base}/?source={args.source}" + (f"&clip={clip}" if clip else ""))
    print(f"  Live:     {base}/live")
    print(f"  Default source: {args.source} ({len(clips)} clips)")
    print(f"  Checkpoints: {len(discover_checkpoints())} under runs/")
    print("=" * 60)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
