#!/usr/bin/env python3
"""Interactive shot cutter UI for data/input videos.

Usage:
  python scripts/serve_cutter.py
  python scripts/serve_cutter.py --port 8766

Open http://127.0.0.1:8766/
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import shutil
import subprocess
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

LAB_ROOT = Path(__file__).resolve().parents[1]
CUTTER_DIR = LAB_ROOT / "cutter"
INPUT_DIR = LAB_ROOT / "data" / "input"
SHOTS_DIR = INPUT_DIR / "shots"

VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}


def list_videos() -> list[dict]:
    if not INPUT_DIR.exists():
        return []
    out: list[dict] = []
    for p in sorted(INPUT_DIR.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in VIDEO_EXTS:
            continue
        rel = p.relative_to(INPUT_DIR).as_posix()
        # Keep sidebar focused on source footage (not previous exports)
        if rel.startswith("shots/"):
            continue
        out.append(
            {
                "id": rel,
                "name": p.name,
                "rel": rel,
                "url": f"/media/{rel}",
                "size": p.stat().st_size,
            }
        )
    return out


def safe_input_path(rel: str) -> Path | None:
    """Resolve a relative path under data/input (no traversal)."""
    rel = rel.replace("\\", "/").lstrip("/")
    if ".." in rel.split("/"):
        return None
    path = (INPUT_DIR / rel).resolve()
    try:
        path.relative_to(INPUT_DIR.resolve())
    except ValueError:
        return None
    return path if path.is_file() else None


def export_segments(rel: str, segments: list[dict]) -> dict:
    src = safe_input_path(rel)
    if src is None:
        raise FileNotFoundError(f"Video not found: {rel}")
    if not segments:
        raise ValueError("No segments to export")

    ff = shutil.which("ffmpeg")
    if not ff:
        raise RuntimeError("ffmpeg not found on PATH")

    stem = src.stem
    out_dir = SHOTS_DIR / stem
    out_dir.mkdir(parents=True, exist_ok=True)

    # clear previous shot_*.mp4 from this stem (keep other files)
    for old in out_dir.glob("shot_*.mp4"):
        old.unlink()

    entries = []
    for i, seg in enumerate(segments):
        start = float(seg["start"])
        end = float(seg["end"])
        if end - start < 0.05:
            continue
        name = f"shot_{i:03d}.mp4"
        out_path = out_dir / name
        duration = end - start
        cmd = [
            ff,
            "-y",
            "-ss",
            f"{start:.3f}",
            "-i",
            str(src),
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
        entries.append(
            {
                "id": f"shot_{i:03d}",
                "file": name,
                "start_sec": round(start, 3),
                "end_sec": round(end, 3),
                "duration_sec": round(duration, 3),
            }
        )

    manifest = {
        "source": str(src.as_posix()),
        "source_name": src.name,
        "source_rel": rel,
        "n_shots": len(entries),
        "shots": entries,
        "editor": "serve_cutter",
    }
    (out_dir / "shots_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"ok": True, "out_dir": str(out_dir.as_posix()), "manifest": manifest}


class Handler(SimpleHTTPRequestHandler):
    def _json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ("/", "/index.html"):
            data = (CUTTER_DIR / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
            return

        if path == "/api/videos":
            self._json(200, {"videos": list_videos(), "input_dir": str(INPUT_DIR.as_posix())})
            return

        if path.startswith("/media/"):
            rel = unquote(path[len("/media/") :])
            file_path = safe_input_path(rel)
            if file_path is None:
                self.send_error(404, "Video not found")
                return
            # Delegate range-aware file serve
            self.path = "/"  # unused by override below
            return self._serve_file(file_path)

        self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/export":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
            rel = payload["video"]
            segments = payload["segments"]
            result = export_segments(rel, segments)
            self._json(200, result)
        except Exception as e:
            self._json(400, {"ok": False, "error": str(e)})

    def _serve_file(self, file_path: Path) -> None:
        ctype = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        file_size = file_path.stat().st_size
        range_header = self.headers.get("Range")

        if range_header:
            # bytes=start-end
            units, _, rng = range_header.partition("=")
            if units != "bytes":
                self.send_error(400, "Invalid range")
                return
            start_s, _, end_s = rng.partition("-")
            start = int(start_s) if start_s else 0
            end = int(end_s) if end_s else file_size - 1
            end = min(end, file_size - 1)
            if start > end or start >= file_size:
                self.send_error(416, "Range not satisfiable")
                return
            length = end - start + 1
            self.send_response(206)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(length))
            self.end_headers()
            with file_path.open("rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(256 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
            return

        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(file_size))
        self.end_headers()
        with file_path.open("rb") as f:
            shutil.copyfileobj(f, self.wfile)

    def log_message(self, fmt, *args):
        sys.stderr.write("[cutter] " + (fmt % args) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    CUTTER_DIR.mkdir(parents=True, exist_ok=True)
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    mimetypes.add_type("video/mp4", ".mp4")
    mimetypes.add_type("video/webm", ".webm")

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}/"
    print(f"Cutter: {url}")
    print(f"Videos from: {INPUT_DIR}")
    print("Space=play/pause  C=cut  Delete=remove segment  then Gerar recortes")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
