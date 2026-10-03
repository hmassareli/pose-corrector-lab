#!/usr/bin/env python3
"""Write NLF-S fast + current-dev Mixamo renders beside benchmark photos."""

from __future__ import annotations

import json
import mimetypes
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PIL import Image

LAB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB_ROOT / "scripts"))


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def translate_path(self, path: str) -> str:
        from urllib.parse import unquote, urlparse

        route = unquote(urlparse(path).path)
        if route in {"/", "/bake"}:
            return str(LAB_ROOT / "viewer" / "avatar_bake.html")
        if route.startswith("/static/"):
            return str(LAB_ROOT / "viewer" / route[len("/static/") :])
        if route.startswith("/assets/"):
            return str(LAB_ROOT / "assets" / route[len("/assets/") :])
        if route.startswith("/poses/"):
            return str(Handler.out_dir / route[len("/poses/") :])
        return super().translate_path(route)


def save_compare(photo: Path, avatar: Path, output: Path) -> None:
    def resized(image: Image.Image) -> Image.Image:
        height = 960
        width = max(1, round(image.width * height / image.height))
        return image.resize((width, height), Image.Resampling.LANCZOS)

    left = resized(Image.open(photo).convert("RGB"))
    right = resized(Image.open(avatar).convert("RGB"))
    composite = Image.new("RGB", (left.width + right.width + 8, 960), (24, 28, 34))
    composite.paste(left, (0, 0))
    composite.paste(right, (left.width + 8, 0))
    composite.save(output)


def main() -> int:
    import argparse
    from playwright.sync_api import sync_playwright
    from measure_avatar_angles import write_pose_json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    benchmark_dir = LAB_ROOT / "src" / "benchmark_images"
    out_dir = benchmark_dir / "avatar_dev"
    pose_dir = out_dir / "poses"
    report = json.loads((LAB_ROOT / "experiments" / "nlf_dense_surface" / "report.json").read_text())
    probe = json.loads((LAB_ROOT / "experiments" / "nlf_smplx55_probe" / "report.json").read_text())
    probe_by_img = {i["image"]: i for i in probe["items"] if i.get("ok")}
    pose_dir.mkdir(parents=True, exist_ok=True)
    Handler.out_dir = pose_dir
    mimetypes.add_type("model/vnd.fbx", ".fbx")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                items = [item for item in report["items"] if item.get("ok")]
                for item in items[: args.limit]:
                    stem = Path(item["image"]).stem
                    sx = probe_by_img.get(item["image"], {}).get("smplx55")
                    write_pose_json(pose_dir, stem, item, sx)
                    json_name = f"{stem}.json"
                    for suffix, surface in (("current", False), ("surface", True)):
                        page = browser.new_page(viewport={"width": 720, "height": 960}, device_scale_factor=1)
                        errors: list[str] = []
                        page.on("console", lambda message: errors.append(f"console {message.type}: {message.text}") if message.type == "error" else None)
                        page.on("pageerror", lambda error: errors.append(f"page: {error}"))
                        page.goto(f"{base_url}/bake?pose=/poses/{json_name}&surface={int(surface)}", wait_until="domcontentloaded")
                        try:
                            page.wait_for_function("() => window.__BAKE_READY__ || window.__BAKE_ERROR__", timeout=30_000)
                        except Exception as error:
                            detail = "\n".join(errors) or "no browser error was emitted"
                            raise RuntimeError(f"{stem} ({suffix}) did not finish: {detail}") from error
                        error = page.evaluate("() => window.__BAKE_ERROR__")
                        if error:
                            raise RuntimeError(f"{stem} ({suffix}): {error}")
                        avatar = out_dir / f"{stem}_{suffix}.png"
                        page.locator("#canvas").screenshot(path=str(avatar))
                        page.close()
                    save_compare(
                        benchmark_dir / item["image"],
                        out_dir / f"{stem}_surface.png",
                        out_dir / f"{stem}_compare.png",
                    )
                    print(f"[ok] {stem}")
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())