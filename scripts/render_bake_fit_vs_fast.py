#!/usr/bin/env python3
"""Bake the Mixamo avatar from NLF-S fit joints vs fast x55 joints, side-by-side.

Reads experiments/nlf_fit_webcam1/fit_smplx.npz (fit_joints + x55, both T×55×3
in mm NLF camera space, same joint order), builds the avatar_bake_seq frame
JSONs (16 lab joints + SMPL-X aux with fingers/eyes/collars), renders each
source through viewer/avatar_bake_seq.html with the side camera, and hstacks
the two panels into one comparison video.

Usage:
  python scripts/render_bake_fit_vs_fast.py [--step 2] [--max-frames 0]
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
OUT_DIR = LAB_ROOT / "experiments" / "bake_fit_vs_fast"

# 16-lab order consumed by avatar_bake_seq (pose[0]=pelvis, pose[5]/[6]=ankles)
LAB16 = [
    "pelvis", "left_hip", "right_hip", "left_knee", "right_knee", "left_ankle",
    "right_ankle", "spine2", "left_shoulder", "right_shoulder", "left_elbow",
    "right_elbow", "left_wrist", "right_wrist", "neck", "head",
]

# SMPL-X 55 joint -> aux key expected by mikapo_mixamo_solver (auxFromSmpl)
AUX_MAP = {
    "pelvis": "pelvis", "left_hip": "left_hip", "right_hip": "right_hip",
    "left_ankle": "left_ankle", "right_ankle": "right_ankle",
    "left_foot": "left_foot", "right_foot": "right_foot",
    "left_wrist": "left_wrist", "right_wrist": "right_wrist",
    "left_elbow": "left_elbow", "right_elbow": "right_elbow",
    "left_shoulder": "left_shoulder", "right_shoulder": "right_shoulder",
    "left_collar": "left_collar", "right_collar": "right_collar",
    "spine1": "spine1", "spine2": "spine2", "spine3": "spine3",
    "neck": "neck", "head": "head", "jaw": "jaw",
    "left_eye": "left_eye", "right_eye": "right_eye",
    "left_index1": "left_index", "left_pinky1": "left_pinky",
    "left_middle1": "left_middle", "left_thumb1": "left_thumb",
    "right_index1": "right_index", "right_pinky1": "right_pinky",
    "right_middle1": "right_middle", "right_thumb1": "right_thumb",
}


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def translate_path(self, path: str) -> str:
        from urllib.parse import unquote, urlparse

        route = unquote(urlparse(path).path)
        if route in {"/", "/bake", "/bake_seq"}:
            return str(LAB_ROOT / "viewer" / "avatar_bake_seq.html")
        if route.startswith("/static/"):
            return str(LAB_ROOT / "viewer" / route[len("/static/") :])
        if route.startswith("/assets/"):
            return str(LAB_ROOT / "assets" / route[len("/assets/") :])
        if route.startswith("/poses/"):
            return str(OUT_DIR / route[len("/poses/") :])
        return super().translate_path(route)


def build_frames(joints55: np.ndarray, names: list[str]) -> list[dict]:
    """T×55×3 mm NLF camera space -> avatar_bake_seq frames [{joints, aux_smpl}]."""
    name_to_i = {n: i for i, n in enumerate(names)}
    frames: list[dict] = []
    for t in range(joints55.shape[0]):
        aux = {}
        for src, dst in AUX_MAP.items():
            p = joints55[t, name_to_i[src]]
            aux[dst] = [float(c) for c in p]
        joints = [joints55[t, name_to_i[n]].tolist() for n in LAB16]
        frames.append({"joints": joints, "aux_smpl": aux})
    return frames


def render_panel(url_base: str, frames_name: str, label: str, name: str,
                 step: int, fps: int, max_frames: int) -> int:
    from playwright.sync_api import sync_playwright

    png_dir = OUT_DIR / f"{name}_png"
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
                f"{url_base}/bake_seq?pose=/poses/{frames_name}.json&side=1&fps={fps}&label={label}",
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
    args = ap.parse_args()

    if not args.npz.is_file():
        raise SystemExit(f"missing npz: {args.npz}")
    d = np.load(args.npz)
    names = [str(n) for n in d["smplx55_names"]]
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for key, fname in (("fit_joints", "fit_frames"), ("x55", "fast_frames")):
        frames = build_frames(d[key].astype(np.float64), names)
        (OUT_DIR / f"{fname}.json").write_text(json.dumps(frames), encoding="utf-8")
        print(f"[frames] {fname}.json ({len(frames)} frames)")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url_base = f"http://127.0.0.1:{server.server_port}"
    print(f"[srv] {url_base}", flush=True)

    try:
        n_fit = render_panel(url_base, "fit_frames", "NLF-S FIT (rotations)", "bake_fit", args.step, args.fps, args.max_frames)
        n_fast = render_panel(url_base, "fast_frames", "NLF-S FAST x55 (game path)", "bake_fast", args.step, args.fps, args.max_frames)

        if n_fit:
            to_mp4(OUT_DIR / "bake_fit_png", OUT_DIR / "henrique_webcam_1_bake_fit.mp4", args.fps)
        if n_fast:
            to_mp4(OUT_DIR / "bake_fast_png", OUT_DIR / "henrique_webcam_1_bake_fast.mp4", args.fps)
        if n_fit and n_fast:
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-i", str(OUT_DIR / "henrique_webcam_1_bake_fit.mp4"),
                    "-i", str(OUT_DIR / "henrique_webcam_1_bake_fast.mp4"),
                    "-filter_complex", "[0:v][1:v]hstack=inputs=2[v]",
                    "-map", "[v]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
                    "-movflags", "+faststart",
                    str(OUT_DIR / "henrique_webcam_1_bake_fit_vs_fast.mp4"),
                ],
                check=True,
            )
            print(f"[video] {OUT_DIR / 'henrique_webcam_1_bake_fit_vs_fast.mp4'}")
    finally:
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
