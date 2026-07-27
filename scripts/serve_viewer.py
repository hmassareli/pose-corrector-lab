#!/usr/bin/env python3
"""Serve the HTML viewer: video | interactive 3D skeleton.

Loads joints on demand from joints3d.npy (caches viewer_payload.json on first open).

Prefer the unified lab (multi-source + live):
  python scripts/serve_lab.py
  → http://127.0.0.1:8780/

Legacy single-source usage:
  python scripts/serve_viewer.py --source mediapipe
  python scripts/serve_viewer.py --source mediapipe --clip burn_500_shots__shot_000__person_000
  python scripts/serve_viewer.py --clip shadow_clip_45s --source teacher
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

LAB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB_ROOT / "src"))

from pose_lab.io import (  # noqa: E402
    build_viewer_payload_from_clip,
    clip_has_joints,
    resolve_clip_fps,
)

VIEWER_DIR = LAB_ROOT / "viewer"
SOURCE_ROOTS = {
    "teacher": LAB_ROOT / "data" / "teacher",
    "mediapipe": LAB_ROOT / "data" / "mediapipe",
    "corrected": LAB_ROOT / "data" / "corrected",
    "teacher_aligned": LAB_ROOT / "data" / "teacher_aligned",
}


class Handler(SimpleHTTPRequestHandler):
    clip_id: str = ""
    source: str = "teacher"
    data_root: Path = SOURCE_ROOTS["teacher"]
    # Overlays for the corrected viewer (same clip id).
    mediapipe_root: Path = SOURCE_ROOTS["mediapipe"]
    teacher_aligned_root: Path = SOURCE_ROOTS["teacher_aligned"]

    def translate_path(self, path: str) -> str:
        parsed = urlparse(path)
        p = parsed.path
        if p in ("/", "/index.html"):
            return str(VIEWER_DIR / "index.html")
        if p.startswith("/static/"):
            return str(VIEWER_DIR / p[len("/static/") :])
        if p.startswith("/media/"):
            rel = p[len("/media/") :]
            return str(Handler.data_root / rel)
        return str(VIEWER_DIR / "index.html")

    def end_headers(self):
        # Avoid stale index.html (e.g. missing frame-jump UI) across ports.
        path = urlparse(self.path).path
        if path in ("/", "/index.html") or path.startswith("/api/"):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _send_overlay_json(self, clip: str, root: Path, source: str, label: str) -> None:
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

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ("/api/shadow.json", "/api/shadow"):
            # MediaPipe joints for the same clip — ghost overlay on Corrector.
            qs = parse_qs(parsed.query)
            clip = qs.get("clip", [Handler.clip_id])[0]
            self._send_overlay_json(clip, Handler.mediapipe_root, "mediapipe", "shadow")
            return
        if parsed.path in ("/api/teacher.json", "/api/teacher_shadow.json"):
            # Teacher aligned (same space as MP/corrector) — ghost overlay.
            qs = parse_qs(parsed.query)
            clip = qs.get("clip", [Handler.clip_id])[0]
            self._send_overlay_json(
                clip, Handler.teacher_aligned_root, "teacher_aligned", "teacher"
            )
            return
        if parsed.path == "/api/clips":
            clips = list_ready_clips(Handler.data_root)
            body = json.dumps(
                {
                    "clips": clips,
                    "current": Handler.clip_id,
                    "source": Handler.source,
                }
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/api/payload.json":
            qs = parse_qs(parsed.query)
            clip = qs.get("clip", [Handler.clip_id])[0]
            clip_dir = Handler.data_root / clip
            try:
                data = payload_bytes_for_clip(clip_dir, Handler.source)
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
        return SimpleHTTPRequestHandler.do_GET(self)

    def log_message(self, fmt, *args):
        sys.stderr.write("[viewer] " + (fmt % args) + "\n")


def list_ready_clips(root: Path) -> list[str]:
    """Clips with joints3d.npy (payload JSON optional — built on demand)."""
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
        # Stale caches often have fps=30 while source.mp4 is ~24 — fix in place.
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
                f"[viewer] fixed fps {clip_dir.name}: {old} → {true_fps:.4f}\n"
            )
        return json.dumps(payload).encode("utf-8")
    if not clip_has_joints(clip_dir):
        raise FileNotFoundError(f"No joints3d.npy for clip {clip_dir.name} (source={source})")
    payload = build_viewer_payload_from_clip(clip_dir, source=source, cache=True)
    return json.dumps(payload).encode("utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", default="", help="Clip id (optional: picks first ready)")
    ap.add_argument(
        "--source",
        choices=("teacher", "mediapipe", "corrected", "teacher_aligned"),
        default="mediapipe",
    )
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--wait", action="store_true", help="wait until at least one clip is ready")
    args = ap.parse_args()

    root = SOURCE_ROOTS[args.source]
    Handler.source = args.source
    Handler.data_root = root

    import time

    clips = list_ready_clips(root)
    if not clips and args.wait:
        print(f"Waiting for first {args.source} joints3d.npy under {root} ...")
        while not clips:
            time.sleep(2)
            clips = list_ready_clips(root)

    clip = args.clip or (clips[0] if clips else "")
    if not clip:
        raise SystemExit(
            f"No ready clips in {root}.\n"
            f"Run MediaPipe/teacher first, or pass --wait."
        )
    if not clip_has_joints(root / clip):
        raise SystemExit(f"Missing {root / clip / 'joints3d.npy'}")

    Handler.clip_id = clip
    mimetypes.add_type("video/mp4", ".mp4")

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}/?clip={clip}"
    print(f"Source: {args.source}")
    print(f"Viewer: {url}")
    print(f"Ready clips: {len(list_ready_clips(root))} (joints3d.npy; payload built on open)")
    print("Drag on the 3D panel to orbit. Scroll to zoom. Space = play/pause sync.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
