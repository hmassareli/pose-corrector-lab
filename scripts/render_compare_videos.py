#!/usr/bin/env python3
"""Render side-view avatar videos: GVHMR teacher vs NLF-S, on a user webcam clip.

Pipeline:
  1) NLF-S: run the live runtime (TRT/DML backend, smplx55 query) over the clip,
     saving per-frame lab joints + SMPL-X aux.
  2) Teacher: reuse data/teacher/<clip>/joints3d.npy (lab order) +
     joints3d_smpl.npy (SMPL22) for the aux.
  3) Playwright headless drives viewer/avatar_bake_seq.html frame by frame with a
     side camera; frames go to ffmpeg as h264 mp4.
  4) Benchmark: per-frame joint error (NLF-S vs teacher) after pelvis + shoulder
     normalization, plus the existing avatar angle-fidelity report.

Usage:
  python scripts/render_compare_videos.py --clip henrique_webcam_1 [--max-frames 300] [--only teacher|nlf]
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import shutil
import subprocess
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB_ROOT / "scripts"))
sys.path.insert(0, str(LAB_ROOT / "src"))

import serve_lab  # noqa: E402

SMPL22_AUX = {
    "pelvis": 0,
    "left_hip": 1,
    "right_hip": 2,
    "spine1": 3,
    "left_knee": 4,
    "right_knee": 5,
    "spine2": 6,
    "left_ankle": 7,
    "right_ankle": 8,
    "spine3": 9,
    "left_foot": 10,
    "right_foot": 11,
    "neck": 12,
    "left_collar": 13,
    "right_collar": 14,
    "head": 15,
    "left_shoulder": 16,
    "right_shoulder": 17,
    "left_elbow": 18,
    "right_elbow": 19,
    "left_wrist": 20,
    "right_wrist": 21,
}
LAB16 = [
    "pelvis", "left_hip", "right_hip", "left_knee", "right_knee",
    "left_ankle", "right_ankle", "spine", "left_shoulder", "right_shoulder",
    "left_elbow", "right_elbow", "left_wrist", "right_wrist", "neck", "head",
]


class Handler(SimpleHTTPRequestHandler):
    out_dir: Path = LAB_ROOT / "data" / "compare"

    def log_message(self, format, *args):
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
            return str(Handler.out_dir / route[len("/poses/") :])
        return super().translate_path(route)


def build_nlf_frames(src_video: Path, max_frames: int) -> list[dict]:
    import cv2

    rt = serve_lab.NLF_RUNTIME
    rt.load()
    print(f"[nlf] backend: {rt._engine.backend if rt._engine else 'torch'} device={rt._device}", flush=True)
    cap = cv2.VideoCapture(str(src_video))
    frames: list[dict] = []
    ms_all: list[float] = []
    skipped = 0
    while len(frames) < max_frames:
        ok, bgr = cap.read()
        if not ok:
            break
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        r = rt.infer_rgb(rgb)
        if r.get("ok"):
            frames.append({"joints": r["joints"], "aux_smpl": r["aux_smpl"]})
            ms_all.append(float(r.get("ms", 0)))
        else:
            skipped += 1
    cap.release()
    ms = np.asarray(ms_all, dtype=np.float64)
    if ms.size:
        print(f"[nlf] {len(frames)} posed / {len(frames) + skipped} frames "
              f"({skipped} skipped) | server ms mean {ms.mean():.1f} p50 {np.median(ms):.1f} "
              f"p95 {np.percentile(ms, 95):.1f}", flush=True)
    return frames


def build_teacher_frames(te_dir: Path, max_frames: int) -> list[dict]:
    joints = np.load(te_dir / "joints3d.npy")[:max_frames]
    smpl = np.load(te_dir / "joints3d_smpl.npy")[:max_frames]
    frames: list[dict] = []
    for i in range(joints.shape[0]):
        aux = {name: [float(c) for c in smpl[i][idx]] for name, idx in SMPL22_AUX.items()}
        frames.append({"joints": joints[i].tolist(), "aux_smpl": aux})
    print(f"[teacher] {len(frames)} frames (GVHMR SMPL22 + lab joints)", flush=True)
    return frames


def render_video(url_base: str, frames: list[dict], name: str, out_mp4: Path, fps: int = 30) -> None:
    from playwright.sync_api import sync_playwright

    png_dir = Handler.out_dir / f"{name}_png"
    shutil.rmtree(png_dir, ignore_errors=True)
    png_dir.mkdir(parents=True, exist_ok=True)
    frames_json = Handler.out_dir / f"{name}_frames.json"
    frames_json.write_text(json.dumps(frames), encoding="utf-8")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 720, "height": 960}, device_scale_factor=1)
            errors: list[str] = []
            page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
            page.on("pageerror", lambda err: errors.append(str(err)))
            page.goto(f"{url_base}/bake_seq?pose=/poses/{name}_frames.json&side=1&fps={fps}",
                      wait_until="domcontentloaded")
            try:
                page.wait_for_function("() => window.__BAKE_READY__ || window.__BAKE_ERROR__", timeout=60_000)
            except Exception as error:
                raise RuntimeError(f"{name}: not ready: {error}; console={errors[:5]}") from error
            err = page.evaluate("() => window.__BAKE_ERROR__")
            if err:
                raise RuntimeError(f"{name}: {err}")
            total = page.evaluate("() => window.__BAKE_SEQ_TOTAL__")
            for i in range(total):
                done = page.evaluate("() => window.__bakeSeqStep()")
                if done is None:
                    break
                page.locator("#canvas").screenshot(path=str(png_dir / f"{i:05d}.png"))
                if (i + 1) % 100 == 0:
                    print(f"  [{name}] {i + 1}/{total}", flush=True)
            print(f"  [{name}] captured {total} frames", flush=True)
        finally:
            browser.close()

    subprocess.run(
        [
            "ffmpeg", "-y", "-framerate", str(fps),
            "-i", str(png_dir / "%05d.png"),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-movflags", "+faststart",
            str(out_mp4),
        ],
        check=True,
    )
    print(f"[video] {out_mp4} ({out_mp4.stat().st_size / 1e6:.1f} MB)", flush=True)


def joint_error_bench(nlf_frames: list[dict], teacher_frames: list[dict]) -> dict:
    """Pelvis + shoulder-width normalized joint error (NLF-S vs teacher)."""
    n = min(len(nlf_frames), len(teacher_frames))
    if n == 0:
        return {}
    nlf = np.asarray([f["joints"] for f in nlf_frames[:n]], dtype=np.float64)
    tea = np.asarray([f["joints"] for f in teacher_frames[:n]], dtype=np.float64)
    ls_i, rs_i = 8, 9  # lab order
    pl_i = 0
    # Normalize: pelvis-centered, shoulder-width scale
    nlf_c = nlf - nlf[:, pl_i : pl_i + 1, :]
    tea_c = tea - tea[:, pl_i : pl_i + 1, :]
    nlf_w = np.linalg.norm(nlf_c[:, rs_i] - nlf_c[:, ls_i], axis=1)
    tea_w = np.linalg.norm(tea_c[:, rs_i] - tea_c[:, ls_i], axis=1)
    w = np.maximum(np.minimum(nlf_w, tea_w), 1e-4)
    nlf_n = nlf_c / w[:, None, None]
    tea_n = tea_c / w[:, None, None]
    err = np.linalg.norm(nlf_n - tea_n, axis=2)  # (T, 16) in shoulder-width units
    out: dict = {}
    for j, name in enumerate(LAB16):
        col = err[:, j]
        out[name] = {"mean": float(col.mean()), "p95": float(np.percentile(col, 95))}
    out["_all_mean"] = float(err.mean())
    out["_all_p95"] = float(np.percentile(err, 95))
    out["_n_frames"] = n
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", default="henrique_webcam_1")
    ap.add_argument("--max-frames", type=int, default=0, help="0 = all")
    ap.add_argument("--only", choices=["teacher", "nlf"], default=None)
    ap.add_argument("--render", action="store_true", help="render videos (default when both datasets ready)")
    args = ap.parse_args()

    src = LAB_ROOT / "data" / "input" / "henrique_training" / f"{args.clip}.mp4"
    te_dir = LAB_ROOT / "data" / "teacher" / args.clip
    if not src.is_file():
        print(f"missing source video: {src}")
        return 1
    if not (te_dir / "joints3d.npy").is_file():
        print(f"missing teacher output: {te_dir}")
        return 1

    Handler.out_dir.mkdir(parents=True, exist_ok=True)
    mimetypes.add_type("model/vnd.fbx", ".fbx")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url_base = f"http://127.0.0.1:{server.server_port}"
    print(f"[srv] {url_base}", flush=True)

    nlf_path = Handler.out_dir / "nlf_s_frames.json"
    tea_path = Handler.out_dir / "teacher_frames.json"

    if args.only in (None, "nlf") and not nlf_path.is_file():
        frames = build_nlf_frames(src, args.max_frames or 10**9)
        nlf_path.write_text(json.dumps(frames), encoding="utf-8")
        print(f"[nlf] saved {nlf_path} ({nlf_path.stat().st_size / 1e6:.1f} MB)", flush=True)
    if args.only in (None, "teacher") and not tea_path.is_file():
        frames = build_teacher_frames(te_dir, args.max_frames or 10**9)
        tea_path.write_text(json.dumps(frames), encoding="utf-8")
        print(f"[teacher] saved {tea_path} ({tea_path.stat().st_size / 1e6:.1f} MB)", flush=True)

    nlf_frames = json.loads(nlf_path.read_text(encoding="utf-8")) if nlf_path.is_file() else []
    tea_frames = json.loads(tea_path.read_text(encoding="utf-8")) if tea_path.is_file() else []
    n = min(len(nlf_frames), len(tea_frames))
    if args.max_frames:
        nlf_frames, tea_frames = nlf_frames[: args.max_frames], tea_frames[: args.max_frames]

    bench = joint_error_bench(nlf_frames, tea_frames)
    bench_path = Handler.out_dir / f"{args.clip}_nlf_vs_teacher.json"
    bench_path.write_text(json.dumps(bench, indent=1), encoding="utf-8")
    print(f"\n[bench] NLF-S vs teacher joint error (pelvis/shoulder-normalized, shoulder-width units, n={bench.get('_n_frames')})")
    for name in LAB16:
        row = bench.get(name, {})
        print(f"  {name:<16} mean {row.get('mean', float('nan')):.3f}  p95 {row.get('p95', float('nan')):.3f}")
    print(f"  {'ALL':<16} mean {bench.get('_all_mean', float('nan')):.3f}  p95 {bench.get('_all_p95', float('nan')):.3f}")
    print(f"[bench] saved {bench_path}")

    if args.render or (args.only is None and n > 0):
        if nlf_frames:
            render_video(url_base, nlf_frames, "nlf_s", Handler.out_dir / f"{args.clip}_nlf_s_side.mp4")
        if tea_frames:
            render_video(url_base, tea_frames, "teacher", Handler.out_dir / f"{args.clip}_teacher_side.mp4")

    server.shutdown()
    server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
