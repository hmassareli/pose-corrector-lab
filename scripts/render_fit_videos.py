#!/usr/bin/env python3
"""Render the NLF-S SMPL-X fit (mesh, rotations) vs the fast x55 skeleton.

Prep: reads experiments/nlf_fit_webcam1/fit_smplx.npz (verts T×10475×3 mm,
fit_joints T×55×3, x55 T×55×3) and writes binary assets + meta for
viewer/smpl_fit_seq.html:

  render/verts.bin        float32 T×10475×3 (mesh mode)
  render/faces.bin        uint32 20908×3     (from SMPLX_NEUTRAL.npz)
  render/joints.bin       float32 T×55×3     (fit_joints → per-frame pelvis center)
  render_skel/joints.bin  float32 T×55×3     (x55 → fast-path skeleton)
  each: meta.json         {T, V, F, n_joints, joint_names, subsample}

Then playwright drives smpl_fit_seq.html per frame (subsampled), screenshots
720×960, and ffmpeg assembles the two panels + a side-by-side mp4.

Usage:
  python scripts/render_fit_videos.py [--frames N] [--step 2]
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NPZ = LAB_ROOT / "experiments" / "nlf_fit_webcam1" / "fit_smplx.npz"
DEFAULT_SMPLX = LAB_ROOT / "external" / "GVHMR" / "inputs" / "checkpoints" / "body_models" / "smplx" / "SMPLX_NEUTRAL.npz"
OUT_DIR = LAB_ROOT / "experiments" / "nlf_fit_webcam1" / "render"
FONT = LAB_ROOT / "data" / "compare" / "arialbd.ttf"


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def translate_path(self, path: str) -> str:
        from urllib.parse import unquote, urlparse

        route = unquote(urlparse(path).path)
        if route in {"/", "/seq"}:
            return str(LAB_ROOT / "viewer" / "smpl_fit_seq.html")
        if route.startswith("/static/"):
            return str(LAB_ROOT / "viewer" / route[len("/static/") :])
        if route.startswith("/data/"):
            return str(OUT_DIR / route[len("/data/") :])
        if route.startswith("/skeldata/"):
            return str(OUT_DIR.parent / "render_skel" / route[len("/skeldata/") :])
        return super().translate_path(route)


def prepare() -> dict:
    d = np.load(DEFAULT_NPZ)
    T = int(d["verts"].shape[0])
    V = int(d["verts"].shape[1])
    n_joints = int(d["fit_joints"].shape[1])
    names = [str(n) for n in d["smplx55_names"]]

    smplx = np.load(DEFAULT_SMPLX, allow_pickle=True)
    faces = np.ascontiguousarray(smplx["f"], dtype=np.uint32)

    mesh_dir = OUT_DIR
    skel_dir = OUT_DIR.parent / "render_skel"
    mesh_dir.mkdir(parents=True, exist_ok=True)
    skel_dir.mkdir(parents=True, exist_ok=True)

    verts = np.ascontiguousarray(d["verts"], dtype=np.float32)
    (mesh_dir / "verts.bin").write_bytes(verts.tobytes())
    (mesh_dir / "faces.bin").write_bytes(faces.tobytes())
    (mesh_dir / "joints.bin").write_bytes(np.ascontiguousarray(d["fit_joints"], dtype=np.float32).tobytes())
    (skel_dir / "joints.bin").write_bytes(np.ascontiguousarray(d["x55"], dtype=np.float32).tobytes())

    meta = {"T": T, "V": V, "F": int(faces.shape[0]), "n_joints": n_joints, "joint_names": names}
    (mesh_dir / "meta.json").write_text(json.dumps(meta))
    (skel_dir / "meta.json").write_text(json.dumps(meta))
    print(f"[prep] T={T} V={V} faces={faces.shape} → {mesh_dir}, {skel_dir}")
    return meta


def render_panel(url_base: str, data_base: str, mode: str, name: str, step: int, fps: int, max_frames: int, label: str = "") -> int:
    from playwright.sync_api import sync_playwright

    png_dir = OUT_DIR.parent / f"render_{name}_png"
    shutil.rmtree(png_dir, ignore_errors=True)
    png_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 720, "height": 960}, device_scale_factor=1)
            errors: list[str] = []
            page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
            page.on("pageerror", lambda err: errors.append(str(err)))
            page.goto(
                f"{url_base}/seq?data={data_base}&mode={mode}&side=1&fps={fps}&label={label}",
                wait_until="domcontentloaded",
            )
            try:
                page.wait_for_function("() => window.__BAKE_READY__ || window.__BAKE_ERROR__", timeout=60_000)
            except Exception as e:
                raise RuntimeError(f"{name}: not ready: {e}; console={errors[:5]}") from e
            err = page.evaluate("() => window.__BAKE_ERROR__")
            if err:
                raise RuntimeError(f"{name}: {err}")
            total = page.evaluate("() => window.__BAKE_SEQ_TOTAL__")
            limit = min(total, max_frames * step) if max_frames else total
            captured = 0
            for i in range(0, limit, step):
                done = page.evaluate("() => window.__bakeSeqStep()")
                if done is None:
                    break
                page.locator("#stage").screenshot(path=str(png_dir / f"{captured:05d}.png"))
                captured += 1
                if captured % 100 == 0:
                    print(f"  [{name}] {captured}/{limit // step}", flush=True)
            print(f"  [{name}] captured {captured} frames", flush=True)
            return captured
        finally:
            browser.close()


def to_mp4(png_dir: Path, out_mp4: Path, fps: int) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-framerate", str(fps),
            "-i", str(png_dir / "%05d.png"),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-movflags", "+faststart",
            str(out_mp4),
        ],
        check=True,
    )
    print(f"[video] {out_mp4} ({out_mp4.stat().st_size / 1e6:.1f} MB)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--npz", type=Path, default=DEFAULT_NPZ)
    ap.add_argument("--step", type=int, default=2, help="render every Nth frame")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--max-frames", type=int, default=0, help="cap frames (0 = all)")
    ap.add_argument("--only", choices=["mesh", "skel"], default=None)
    args = ap.parse_args()

    if not args.npz.is_file():
        raise SystemExit(f"missing npz: {args.npz}")
    meta = prepare()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url_base = f"http://127.0.0.1:{server.server_port}"
    print(f"[srv] {url_base}")

    try:
        n_mesh = 0
        n_skel = 0
        if args.only in (None, "mesh"):
            n_mesh = render_panel(url_base, "/data", "mesh", "fit_mesh", args.step, args.fps, args.max_frames, label="NLF-S FIT SMPL-X (rotations)")
        if args.only in (None, "skel"):
            n_skel = render_panel(url_base, "/skeldata", "skeleton", "x55_skel", args.step, args.fps, args.max_frames, label="NLF-S FAST x55 (game path)")

        out = OUT_DIR.parent
        if n_mesh:
            to_mp4(out / "render_fit_mesh_png", out / "henrique_webcam_1_nlf_fit_mesh.mp4", args.fps)
        if n_skel:
            to_mp4(out / "render_x55_skel_png", out / "henrique_webcam_1_nlf_x55_fast.mp4", args.fps)
        if n_mesh and n_skel:
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-i", str(out / "henrique_webcam_1_nlf_fit_mesh.mp4"),
                    "-i", str(out / "henrique_webcam_1_nlf_x55_fast.mp4"),
                    "-filter_complex", "[0:v][1:v]hstack=inputs=2[v]",
                    "-map", "[v]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
                    "-movflags", "+faststart",
                    str(out / "henrique_webcam_1_nlf_fit_vs_fast.mp4"),
                ],
                check=True,
            )
            print(f"[video] {out / 'henrique_webcam_1_nlf_fit_vs_fast.mp4'}")
    finally:
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
