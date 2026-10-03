#!/usr/bin/env python3
"""Dump every rig bone's world quaternion per frame, for jitter analysis.

Error-vs-the-fit (check_body_fidelity.py) and JITTER are different questions: a
setting can track the fit better on average while shaking more frame to frame.
Raising a bone's `strength` scales the signal AND its noise before the One-Euro
filter sees it, so smoothness has to be measured, not assumed.

Jitter here = angle of the frame-to-frame relative rotation of a bone, compared
against the same quantity on the fit (the reference for how much that bone
SHOULD be moving).

Usage:
  python scripts/dump_bone_quats.py --tag neck04
  python scripts/analyze_bone_jitter.py neck04 neck075
"""
from __future__ import annotations

import argparse
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB_ROOT / "scripts"))

from check_palm_fidelity import Handler  # noqa: E402
from check_body_fidelity import READ_BONES  # noqa: E402
from render_bake_top import DEFAULT_NPZ, OUT_DIR  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tag", required=True)
    args = ap.parse_args()

    T = int(np.load(DEFAULT_NPZ)["fit_joints"].shape[0])
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}"
    per_bone: dict[str, list] = {}
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 720, "height": 960})
                page.goto(f"{url}/bake_seq?pose=/poses/fidelity_frames.json&side=1&fps=30",
                          wait_until="domcontentloaded")
                page.wait_for_function("() => window.__BAKE_READY__ || window.__BAKE_ERROR__",
                                       timeout=90_000)
                if page.evaluate("() => window.__BAKE_ERROR__"):
                    raise RuntimeError(page.evaluate("() => window.__BAKE_ERROR__"))
                # EVERY frame: jitter is a per-frame quantity, so no subsampling.
                for t in range(T):
                    if page.evaluate("() => window.__bakeSeqStep()") is None:
                        break
                    for name, fr in page.evaluate(READ_BONES).items():
                        per_bone.setdefault(name, []).append(fr["q"])
                    if t % 200 == 0:
                        print(f"  [{args.tag}] {t}/{T}", flush=True)
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()

    out = OUT_DIR / f"bone_quats_{args.tag}.npz"
    np.savez(out, **{k: np.array(v, dtype=np.float64) for k, v in per_bone.items()})
    print(f"[dump] {out}  ({len(per_bone)} bones)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
