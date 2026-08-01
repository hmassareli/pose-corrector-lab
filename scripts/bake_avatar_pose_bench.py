#!/usr/bin/env python3
"""Offline NLF-S fast path → Mixamo/MiKaPo avatar bake for benchmark stills.

For each image under src/benchmark_images/ (or --images):
  1) YOLOv8n sticky crop + estimate_joints24 (same as live NLF path)
  2) smpl24_to_lab + smpl24_avatar_aux, root-centered metres
  3) Headless Playwright render of viewer/avatar_bake.html (real Mixamo+MiKaPo)
  4) Side-by-side overlay: left=photo, right=avatar

Still-photo default: selfie L/R mirror OFF (WIN stills are not mirrored).
Live webcam keeps selfie ON in live.html; this bench does not.

Judge later: trunk-from-waist-down fidelity, shoulder shrug/drop (raised/lowered).

Usage:
  python scripts/bake_avatar_pose_bench.py
  python scripts/bake_avatar_pose_bench.py --out experiments/avatar_pose_bench
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import shutil
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image

LAB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB_ROOT / "src"))
sys.path.insert(0, str(LAB_ROOT / "scripts"))

from nlf_bbox_track import StickyBBox, YoloNanoPerson  # noqa: E402
from nlf_fast_path import estimate_joints24, get_joint_weights, load_nlf  # noqa: E402
from pose_lab.skeleton import LAB_JOINTS, smpl24_avatar_aux_json, smpl24_to_lab  # noqa: E402

DEFAULT_IMAGES = LAB_ROOT / "src" / "benchmark_images"
DEFAULT_OUT = LAB_ROOT / "experiments" / "avatar_pose_bench"
DEFAULT_MODEL = LAB_ROOT / "data" / "models" / "nlf" / "nlf_s_multi_0.2.2.torchscript"
AVATAR_FBX = LAB_ROOT / "assets" / "Ch28_nonPBR.fbx"
BAKE_HTML = LAB_ROOT / "viewer" / "avatar_bake.html"


def list_images(root: Path) -> list[Path]:
    exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
    files = [p for p in sorted(root.iterdir()) if p.is_file() and p.suffix.lower() in exts]
    return files


def infer_nlf_fast(
    model,
    weights,
    detector: YoloNanoPerson | None,
    rgb: np.ndarray,
    device: str,
) -> dict:
    """Same crop+joints path as serve_lab.NlfRuntime.infer_rgb (per-still tracker)."""
    h, w = rgb.shape[:2]
    tracker = StickyBBox(detect_every=6, expand=1.25)
    t0 = time.perf_counter()
    det_ms = 0.0
    detected = None
    ran_det = False
    if detector is not None and tracker.needs_detect():
        ran_det = True
        td = time.perf_counter()
        detected = detector.detect_xywh(rgb)
        if device.startswith("cuda"):
            torch.cuda.synchronize()
        det_ms = (time.perf_counter() - td) * 1000.0
    xywh = tracker.update(h, w, detected)
    box = tracker.as_torch(xywh, device)

    with torch.inference_mode():
        j24 = estimate_joints24(
            model, rgb, weights, device=device, num_aug=1, box=box
        )
    if device.startswith("cuda"):
        torch.cuda.synchronize()
    ms = (time.perf_counter() - t0) * 1000.0

    if j24 is None:
        return {
            "ok": False,
            "error": "no person",
            "ms": round(ms, 2),
            "det_ms": round(det_ms, 2),
            "detected": ran_det,
            "box": xywh.tolist(),
            "device": device,
            "crop": "yolov8n_sticky" if detector is not None else "fullframe",
        }

    j24_m = np.asarray(j24, dtype=np.float64) / 1000.0
    j24_m = j24_m - j24_m[0:1]
    lab = smpl24_to_lab(j24_m).astype(np.float32)
    aux_smpl = smpl24_avatar_aux_json(j24_m)
    return {
        "ok": True,
        "joints": lab.tolist(),
        "aux_smpl": aux_smpl,
        "joint_names": list(LAB_JOINTS),
        "ms": round(ms, 2),
        "nlf_ms": round(ms - det_ms, 2),
        "det_ms": round(det_ms, 2),
        "detected": ran_det,
        "box": [float(x) for x in xywh.tolist()],
        "device": device,
        "units": "metres",
        "space": "opencv_ish_root",
        "crop": "yolov8n_sticky" if detector is not None else "fullframe",
        "selfie_mirror_for_bake": False,
        "viewer_transform": "Y/Z flip; selfie L/R OFF (still photos)",
    }


class _BakeHandler(SimpleHTTPRequestHandler):
    """Serve lab viewer/assets + experiment pred JSON for Playwright."""

    lab_root: Path = LAB_ROOT
    out_root: Path = DEFAULT_OUT

    def log_message(self, fmt, *args):  # quiet
        pass

    def translate_path(self, path: str) -> str:
        from urllib.parse import unquote, urlparse

        p = unquote(urlparse(path).path)
        if p in ("/", "/bake", "/bake.html"):
            return str(BAKE_HTML)
        if p.startswith("/static/"):
            return str(self.lab_root / "viewer" / p[len("/static/") :])
        if p.startswith("/assets/"):
            return str(self.lab_root / "assets" / p[len("/assets/") :])
        if p.startswith("/pred/"):
            return str(self.out_root / "pred" / p[len("/pred/") :])
        if p.startswith("/input/"):
            return str(self.out_root / "input" / p[len("/input/") :])
        # fallback under lab root
        cand = self.lab_root / p.lstrip("/")
        return str(cand)


def start_server(out_root: Path, port: int = 0) -> tuple[ThreadingHTTPServer, str]:
    mimetypes.add_type("model/vnd.fbx", ".fbx")
    mimetypes.add_type("application/javascript", ".js")
    handler = type(
        "BakeHandlerBound",
        (_BakeHandler,),
        {"lab_root": LAB_ROOT, "out_root": out_root},
    )
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    host, real_port = httpd.server_address
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, f"http://{host}:{real_port}"


def compose_side_by_side(photo_path: Path, avatar_png: Path, out_path: Path) -> None:
    left = Image.open(photo_path).convert("RGB")
    right = Image.open(avatar_png).convert("RGB")
    # Match heights
    th = 960
    def fit_h(im: Image.Image, h: int) -> Image.Image:
        w = max(1, int(round(im.width * (h / im.height))))
        return im.resize((w, h), Image.Resampling.LANCZOS)

    left = fit_h(left, th)
    right = fit_h(right, th)
    gap = 8
    canvas = Image.new("RGB", (left.width + gap + right.width, th), (24, 28, 34))
    canvas.paste(left, (0, 0))
    canvas.paste(right, (left.width + gap, 0))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, format="PNG")


def bake_avatar_screenshot(
    base_url: str,
    pose_url_path: str,
    out_png: Path,
    *,
    selfie: bool = False,
    timeout_ms: int = 120_000,
) -> None:
    from playwright.sync_api import sync_playwright

    q_selfie = "1" if selfie else "0"
    url = f"{base_url}/bake?pose={pose_url_path}&selfie={q_selfie}"
    out_png.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(
                viewport={"width": 720, "height": 960},
                device_scale_factor=1,
            )
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_function(
                "() => window.__BAKE_READY__ === true || window.__BAKE_ERROR__",
                timeout=timeout_ms,
            )
            err = page.evaluate("() => window.__BAKE_ERROR__")
            if err:
                raise RuntimeError(f"bake page error: {err}")
            # Prefer canvas pixels (preserveDrawingBuffer).
            png_bytes = page.evaluate(
                """async () => {
                  const c = document.getElementById('canvas3d');
                  const blob = await new Promise((resolve) => c.toBlob(resolve, 'image/png'));
                  const buf = await blob.arrayBuffer();
                  return Array.from(new Uint8Array(buf));
                }"""
            )
            out_png.write_bytes(bytes(png_bytes))
        finally:
            browser.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--images", type=Path, default=DEFAULT_IMAGES)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    ap.add_argument("--device", default=None)
    ap.add_argument("--selfie", action="store_true", help="Enable selfie L/R mirror (default OFF)")
    ap.add_argument("--no-yolo", action="store_true", help="Force full-frame box (no YOLOv8n)")
    ap.add_argument("--skip-render", action="store_true", help="Only run NLF + JSON, no Playwright")
    ap.add_argument("--limit", type=int, default=0, help="Process only first N images (0=all)")
    args = ap.parse_args()

    images = list_images(args.images)
    if args.limit > 0:
        images = images[: args.limit]
    if not images:
        print(f"No images in {args.images}", file=sys.stderr)
        return 2
    if not args.model.is_file():
        print(f"Missing NLF model: {args.model}", file=sys.stderr)
        return 2
    if not AVATAR_FBX.is_file():
        print(f"Missing Mixamo FBX: {AVATAR_FBX}", file=sys.stderr)
        return 2
    if not BAKE_HTML.is_file():
        print(f"Missing bake HTML: {BAKE_HTML}", file=sys.stderr)
        return 2

    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")
    out = args.out.resolve()
    (out / "input").mkdir(parents=True, exist_ok=True)
    (out / "pred").mkdir(parents=True, exist_ok=True)

    notes = {
        "goal": "First-pass NLF→Mixamo avatar bake for visual judgment",
        "judge_priority": [
            "trunk-from-waist-down fidelity",
            "shoulder shrug/drop (raised/lowered) — avatar often feels locked",
        ],
        "selfie_mirror": bool(args.selfie),
        "selfie_note": (
            "OFF for still photos (WIN camera stills are not mirrored). "
            "Live webcam path in live.html defaults selfie ON to match CSS scaleX(-1)."
        ),
        "viewer_transform": "OpenCV-ish → negate Y and Z; optional selfie negate-X + L/R swap",
        "nlf_path": "YOLOv8n sticky crop → estimate_joints24 num_aug=1 → root-center metres",
        "avatar": str(AVATAR_FBX.relative_to(LAB_ROOT).as_posix()),
        "retarget": "viewer/mikapo_mixamo_solver.js via viewer/avatar_bake.html + Playwright",
    }
    (out / "NOTES.md").write_text(
        "# Avatar pose bench (first pass)\n\n"
        + "\n".join(f"- **{k}**: {v}" for k, v in notes.items())
        + "\n",
        encoding="utf-8",
    )

    print(f"[bake] device={device} images={len(images)} out={out}")
    print(f"[bake] loading NLF {args.model.name} …")
    model = load_nlf(args.model, device)
    weights, _ = get_joint_weights(model, "joints24")

    detector = None
    if not args.no_yolo:
        try:
            detector = YoloNanoPerson(device=device, imgsz=320)
            detector.load()
            print("[bake] YOLOv8n sticky crop enabled")
        except Exception as e:
            print(f"[bake] YOLO unavailable ({e}); falling back to fullframe")
            detector = None

    httpd = None
    base_url = ""
    if not args.skip_render:
        httpd, base_url = start_server(out, port=0)
        print(f"[bake] local server {base_url}")

    items = []
    try:
        for i, img_path in enumerate(images):
            stem = img_path.stem
            print(f"[{i+1}/{len(images)}] {img_path.name}")
            # Copy input
            dst_in = out / "input" / img_path.name
            if dst_in.resolve() != img_path.resolve():
                shutil.copy2(img_path, dst_in)

            bgr = cv2.imread(str(img_path), cv2.IMREAD_COLOR)
            if bgr is None:
                items.append({"name": stem, "ok": False, "error": "imread failed"})
                continue
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

            pred = infer_nlf_fast(model, weights, detector, rgb, device)
            pred["name"] = stem
            pred["source_image"] = img_path.name
            joints_path = out / "pred" / f"{stem}_joints.json"
            joints_path.write_text(json.dumps(pred, indent=2), encoding="utf-8")

            entry = {
                "name": stem,
                "ok": bool(pred.get("ok")),
                "input": str(dst_in.relative_to(out).as_posix()),
                "joints": str(joints_path.relative_to(out).as_posix()),
                "ms": pred.get("ms"),
                "nlf_ms": pred.get("nlf_ms"),
                "det_ms": pred.get("det_ms"),
                "device": pred.get("device", device),
                "crop": pred.get("crop"),
                "box": pred.get("box"),
                "error": pred.get("error"),
            }

            if pred.get("ok") and not args.skip_render:
                avatar_png = out / "pred" / f"{stem}_avatar.png"
                overlay_png = out / "pred" / f"{stem}_overlay.png"
                try:
                    bake_avatar_screenshot(
                        base_url,
                        f"/pred/{stem}_joints.json",
                        avatar_png,
                        selfie=bool(args.selfie),
                    )
                    compose_side_by_side(dst_in, avatar_png, overlay_png)
                    entry["avatar"] = str(avatar_png.relative_to(out).as_posix())
                    entry["overlay"] = str(overlay_png.relative_to(out).as_posix())
                except Exception as e:
                    entry["ok"] = False
                    entry["error"] = f"render failed: {e}"
                    print(f"  ! render failed: {e}")

            items.append(entry)
            print(
                f"  ok={entry['ok']} ms={entry.get('ms')} "
                f"overlay={entry.get('overlay', '—')}"
            )
    finally:
        if httpd is not None:
            httpd.shutdown()

    summary = {
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "device": device,
        "model": str(args.model.relative_to(LAB_ROOT).as_posix())
        if args.model.is_relative_to(LAB_ROOT)
        else str(args.model),
        "selfie_mirror": bool(args.selfie),
        "n_images": len(images),
        "n_ok": sum(1 for x in items if x.get("ok")),
        "notes": notes,
        "items": items,
    }
    summary_path = out / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"[bake] wrote {summary_path} ok={summary['n_ok']}/{summary['n_images']}")
    return 0 if summary["n_ok"] == summary["n_images"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
