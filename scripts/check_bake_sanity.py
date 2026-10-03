#!/usr/bin/env python3
"""Sanity-check the baker-top avatar pose (v2, positions+twist).

Opens avatar_bake_seq.html with the rendered top_frames.json, steps to sample
frames and reads the avatar's bone world positions to verify the pose is a
standing human: feet planted on the ground, knees below hips (not on chest),
shoulders above hips (torso not inverted), head above shoulders.

The viewer is Y-down: down = +Y, so hip.y < knee.y < ankle.y for a standing
pose, and a knee-on-chest pose has knee.y ≈ hip.y (or above).
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = LAB_ROOT / "experiments" / "bake_top"


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


def main() -> int:
    frames_path = OUT_DIR / "top_frames.json"
    if not frames_path.is_file():
        raise SystemExit(f"missing {frames_path}")
    total = len(json.loads(frames_path.read_text(encoding="utf-8")))

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url_base = f"http://127.0.0.1:{server.server_port}"

    from playwright.sync_api import sync_playwright

    bad = []
    rows = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 720, "height": 960}, device_scale_factor=1)
            page.goto(f"{url_base}/bake_seq?pose=/poses/top_frames.json&side=1&fps=30&label=sanity",
                      wait_until="domcontentloaded")
            page.wait_for_function("() => window.__BAKE_READY__ || window.__BAKE_ERROR__", timeout=60_000)
            err = page.evaluate("() => window.__BAKE_ERROR__")
            if err:
                raise SystemExit(f"bake error: {err}")

            samples = sorted({0, total // 4, total // 2, 3 * total // 4, total - 1})
            for t in samples:
                # __bakeSeqStep applies frame k and returns k+1; step until the
                # returned index passes t (frame 0 needs one step too).
                r = 0
                while r is not None and r <= t:
                    r = page.evaluate("() => window.__bakeSeqStep()")
                if r is None or r - 1 != t:
                    continue
                data = page.evaluate("""() => {
                  const THREE = window.__BAKE_THREE__;
                  const rig = window.__BAKE_RIG__;
                  // Joint positions: proximal joint = bone origin; distal joint = child origin.
                  const P = (n, end) => {
                    const b = rig.bones.get(n);
                    if (!b) return null;
                    const v = end === 'child' ? b.child.getWorldPosition(new THREE.Vector3()) : b.bone.getWorldPosition(new THREE.Vector3());
                    return {x: v.x, y: v.y, z: v.z};
                  };
                  return {
                    hip: P('hips'), kneeL: P('leftUpLeg', 'child'), ankleL: P('leftLeg', 'child'),
                    footL: P('leftFoot', 'child'), kneeR: P('rightUpLeg', 'child'), ankleR: P('rightLeg', 'child'),
                    footR: P('rightFoot', 'child'), shL: P('leftArm'), shR: P('rightArm'),
                    neck: P('neck'), head: P('head', 'child'),
                  };
                }""")
                rows.append({"t": t, **data})

                def y(name):
                    return data.get(name, {}).get("y")

                hip = y("hip")
                lk, la = y("kneeL"), y("ankleL")
                rk, ra = y("kneeR"), y("ankleR")
                lf, rf = y("footL"), y("footR")
                sh_l, sh_r = y("shL"), y("shR")
                neck, head = y("neck"), y("head")
                if None in (hip, lk, la, lf, rk, ra, rf, sh_l, sh_r, neck, head):
                    bad.append((t, "missing bones"))
                    continue
                # Viewer is Y-up, units METERS, ground at y=0 after planting.
                min_foot = min(lf, rf)
                if min_foot > 0.05 or min_foot < -0.05:
                    bad.append((t, f"feet not planted: min foot y={min_foot:.3f}"))
                if not (lk < hip - 0.05 and la < lk):
                    bad.append((t, f"left leg not down: hip {hip:.3f} knee {lk:.3f} ankle {la:.3f}"))
                if not (rk < hip - 0.05 and ra < rk):
                    bad.append((t, f"right leg not down: hip {hip:.3f} knee {rk:.3f} ankle {ra:.3f}"))
                if not (sh_l > hip and sh_r > hip):
                    bad.append((t, f"shoulders not above hips: hip {hip:.3f} shL {sh_l:.3f} shR {sh_r:.3f}"))
                # Compare the neck to the shoulder MIDPOINT, not to one shoulder.
                # In a boxing guard a single shoulder is often raised above the
                # neck — the fit itself does this at t=0 (neck 1030.9 vs left
                # shoulder 1038.4) — so `neck > sh_l` flagged a pose that was
                # faithfully reproducing the source. The midpoint is the
                # anatomically meaningful reference for "head not sunk into the
                # torso", which is the inversion this gate exists to catch.
                sh_mid = (sh_l + sh_r) / 2
                if not (neck > sh_mid):
                    bad.append((t, f"neck below shoulder midpoint: neck {neck:.3f} "
                                   f"mid {sh_mid:.3f} (shL {sh_l:.3f} shR {sh_r:.3f})"))
                if not (head > neck):
                    bad.append((t, f"head not above neck: neck {neck:.3f} head {head:.3f}"))
        finally:
            browser.close()

    print(f"sanity: {len(rows)} frames sampled of {total} (units: meters, y-up)")
    for r in rows:
        print(f"  t={r['t']:4d} hip.y={r['hip']['y']:6.2f} kneeL={r['kneeL']['y']:6.2f} ankL={r['ankleL']['y']:6.2f} "
              f"footL={r['footL']['y']:6.2f} shL={r['shL']['y']:6.2f} head={r['head']['y']:6.2f}")
    if bad:
        print("FAIL:")
        for t, msg in bad:
            print(f"  t={t}: {msg}")
        return 1
    print("OK — feet planted, legs down, torso upright at all sampled frames")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
