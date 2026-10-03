#!/usr/bin/env python3
"""Visual A/B of the spine-upright retarget fix on identical real frames.

Renders the SAME real NLF frames (from experiments/nlf_fit_webcam1/fit_smplx.npz)
through viewer/avatar_bake_seq.html-style viewer three ways:

  panel A: fighter-web with the OLD solver (experiments/_solver_no_upright.js)
  panel B: fighter-web with the CURRENT solver (viewer/mikapo_mixamo_solver.js)
  panel C: boxeador with the CURRENT solver (reference rig)

and hstacks the three panels per frame into experiments/avatar_spine_ab/*.png.

Usage:
  python scripts/render_spine_ab.py [--frames 67,500,1052] [--step 1]
"""
from __future__ import annotations

import argparse
import json
import shutil
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

import numpy as np
from PIL import Image

LAB_ROOT = Path(__file__).resolve().parents[1]
NPZ = LAB_ROOT / "experiments" / "nlf_fit_webcam1" / "fit_smplx.npz"
OUT_DIR = LAB_ROOT / "experiments" / "avatar_spine_ab"
OLD_SOLVER = "/experiments/_solver_no_upright.js"
NEW_SOLVER = "/static/mikapo_mixamo_solver.js"

LAB16 = [
    "pelvis", "left_hip", "right_hip", "left_knee", "right_knee", "left_ankle",
    "right_ankle", "spine2", "left_shoulder", "right_shoulder", "left_elbow",
    "right_elbow", "left_wrist", "right_wrist", "neck", "head",
]

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
        route = unquote(urlparse(path).path)
        if route in {"/", "/bake", "/bake_ab"}:
            return str(LAB_ROOT / "experiments" / "_bake_seq_ab.html")
        if route.startswith("/static/"):
            return str(LAB_ROOT / "viewer" / route[len("/static/"):])
        if route.startswith("/assets/"):
            return str(LAB_ROOT / "assets" / route[len("/assets/"):])
        if route.startswith("/experiments/"):
            return str(LAB_ROOT / "experiments" / route[len("/experiments/"):])
        if route.startswith("/poses/"):
            return str(OUT_DIR / route[len("/poses/"):])
        return super().translate_path(route)


def build_frames(joints55: np.ndarray, names: list[str], indices: list[int]) -> list[dict]:
    name_to_i = {n: i for i, n in enumerate(names)}
    frames: list[dict] = []
    for t in indices:
        aux = {}
        for src, dst in AUX_MAP.items():
            aux[dst] = [float(c) for c in joints55[t, name_to_i[src]]]
        joints = [joints55[t, name_to_i[n]].tolist() for n in LAB16]
        frames.append({"joints": joints, "aux_smpl": aux})
    return frames


def render_panel(url_base: str, frames_name: str, avatar: str, solver: str,
                 label: str, name: str) -> list[Path]:
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
                f"{url_base}/bake_ab?pose=/poses/{frames_name}.json&side=1&avatar={avatar}"
                f"&solver={solver}&label={label}&ui=0",
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
            print(f"  [{name}] {total} frames, solver={solver.split('/')[-1]}", flush=True)
            shots: list[Path] = []
            for _ in range(total):
                done = page.evaluate("() => window.__bakeSeqStep()")
                if done is None:
                    break
                idx = page.evaluate("() => window.__BAKE_SEQ_FRAME__")
                shot = png_dir / f"frame_{idx:04d}.png"
                page.locator("#stage").screenshot(path=str(shot))
                shots.append(shot)
            return shots
        finally:
            browser.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--frames", type=str, default="67,500,1052")
    args = ap.parse_args()
    indices = [int(x) for x in args.frames.split(",")]

    if not NPZ.is_file():
        raise SystemExit(f"missing npz: {NPZ}")
    d = np.load(NPZ)
    names = [str(n) for n in d["smplx55_names"]]
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    frames = build_frames(d["fit_joints"].astype(np.float64), names, indices)
    (OUT_DIR / "frames.json").write_text(json.dumps(frames), encoding="utf-8")
    print(f"[frames] {len(frames)} at indices {indices}", flush=True)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url_base = f"http://127.0.0.1:{server.server_port}"
    print(f"[srv] {url_base}", flush=True)

    try:
        panels = {
            "old_fighter": render_panel(url_base, "frames", "fighter-web", OLD_SOLVER,
                                        "fighter-web SEM fix", "old_fighter"),
            "new_fighter": render_panel(url_base, "frames", "fighter-web", NEW_SOLVER,
                                        "fighter-web COM fix", "new_fighter"),
            "boxeador": render_panel(url_base, "frames", "boxeador", NEW_SOLVER,
                                     "boxeador (ref)", "boxeador"),
        }
        for i, idx in enumerate(indices):
            imgs = [Image.open(panels[key][i]) for key in ("old_fighter", "new_fighter", "boxeador")]
            w = sum(im.width for im in imgs)
            h = max(im.height for im in imgs)
            canvas = Image.new("RGB", (w, h), (34, 42, 49))
            x = 0
            for im in imgs:
                canvas.paste(im, (x, 0))
                x += im.width
            out = OUT_DIR / f"cmp_frame_{idx:04d}.png"
            canvas.save(out)
            print(f"[cmp] {out} ({canvas.width}x{canvas.height})", flush=True)
    finally:
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
