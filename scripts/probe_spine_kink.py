#!/usr/bin/env python3
"""Probe: does the fighter-web spine kink where boxeador does not?

Feeds REAL webcam NLF frames (experiments/nlf_fit_webcam1/fit_smplx.npz)
through the exact bake_seq avatar pipeline (same as live NLF path) for both
avatars, and dumps the spine chain (hips→spine→spine1→spine2→neck→head) with
per-joint turning angles. A "kink" shows up as one joint turning far more than
its neighbours, or the chain bending sideways where the SMPL chain is straight.

Usage: python scripts/probe_spine_kink.py [--avatars boxeador,fighter-web]
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB_ROOT / "scripts"))
sys.path.insert(0, str(LAB_ROOT / "src"))

from check_palm_fidelity import Handler  # noqa: E402
from pose_lab.skeleton import smplx55_avatar_aux_json, smplx55_to_lab  # noqa: E402

NPZ = LAB_ROOT / "experiments" / "nlf_fit_webcam1" / "fit_smplx.npz"
POSE_DIR = LAB_ROOT / "experiments" / "nlf_fit_webcam1"
POSES_NAME = "spine_kink_frames.json"

DUMP_JS = """
() => {
  const THREE = window.__BAKE_THREE__;
  const av = window.__BAKE_AVATAR__;
  const rig = window.__BAKE_RIG__;
  const inv = av.getWorldQuaternion(new THREE.Quaternion()).invert();
  const chain = ["hips", "spine", "spine1", "spine2", "neck", "head"];
  const pts = chain.map((n) => {
    const r = rig.bones.get(n);
    if (!r) return null;
    const p = r.bone.getWorldPosition(new THREE.Vector3()).applyQuaternion(inv);
    return [p.x, p.y, p.z];
  });
  const angles = [];
  for (let i = 1; i < pts.length - 1; i++) {
    const a = new THREE.Vector3(...pts[i - 1]);
    const b = new THREE.Vector3(...pts[i]);
    const c = new THREE.Vector3(...pts[i + 1]);
    const u = b.clone().sub(a).normalize();
    const v = c.clone().sub(b).normalize();
    angles.push(Number((Math.acos(Math.min(1, Math.max(-1, u.dot(v)))) * 180 / Math.PI).toFixed(2)));
  }
  // sideways deviation of each joint from the pelvis->neck line (cm), x/z
  const base = new THREE.Vector3(...pts[0]);
  const tip = new THREE.Vector3(...pts[4]);
  const axis = tip.clone().sub(base).normalize();
  const devs = pts.map((pt) => {
    const v = new THREE.Vector3(...pt).sub(base);
    const along = axis.clone().multiplyScalar(v.dot(axis));
    const perp = v.clone().sub(along);
    return [Number((perp.x * 100).toFixed(1)), Number((perp.y * 100).toFixed(1)), Number((perp.z * 100).toFixed(1))];
  });
  return { pts, angles, devsCm: devs, frame: window.__BAKE_SEQ_FRAME__ };
}
"""


class H(Handler):
    def translate_path(self, path: str) -> str:
        from urllib.parse import unquote, urlparse
        route = unquote(urlparse(path).path)
        if route.startswith("/poses/"):
            return str(POSE_DIR / route[len("/poses/"):])
        return super().translate_path(route)


def build_frames(n_frames: int = 6, seed: int = 0) -> None:
    d = np.load(NPZ)
    fit = np.asarray(d["fit_joints"], dtype=np.float64)  # (T,55,3) metres, opencv-ish
    ok = np.asarray(d["ok"], dtype=bool)
    T = fit.shape[0]

    # Torso lean per frame: angle of pelvis->neck from vertical (opencv y-up).
    neck = fit[:, 12]
    pelv = fit[:, 0]
    up = np.array([0.0, 1.0, 0.0])
    axis = neck - pelv
    axis_len = np.linalg.norm(axis, axis=1)
    lean = np.degrees(np.arccos(np.clip(axis[:, 1] / np.maximum(axis_len, 1e-9), -1, 1)))
    valid = np.where(ok & (axis_len > 0.05))[0]
    if len(valid) == 0:
        raise SystemExit("no valid frames")
    order = valid[np.argsort(lean[valid])]
    picks = np.unique(np.concatenate([
        order[[0, len(order) // 2, -1]],                       # min / median / max lean
        np.random.RandomState(seed).choice(order, max(0, n_frames - 3), replace=False),
    ])).astype(int)[:n_frames]

    frames = []
    for t in picks:
        j55 = fit[t]
        lab = smplx55_to_lab(j55)
        aux = smplx55_avatar_aux_json(j55)
        frames.append({
            "frame": int(t),
            "lean": float(round(lean[t], 1)),
            "joints": np.round(lab, 6).tolist(),
            "aux_smpl": aux,
        })
    out = POSE_DIR / POSES_NAME
    out.write_text(json.dumps(frames, separators=(",", ":")), encoding="utf-8")
    print(f"[frames] {out}  picks={[f['frame'] for f in frames]} lean={[f['lean'] for f in frames]}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--avatars", default="boxeador,fighter-web")
    ap.add_argument("--frames", type=int, default=6)
    args = ap.parse_args()

    build_frames(args.frames)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_port}"
    from playwright.sync_api import sync_playwright

    out = {}
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch(headless=True)
            try:
                for aid in [a.strip() for a in args.avatars.split(",") if a.strip()]:
                    p = b.new_page()
                    msgs = []
                    p.on("console", lambda m: msgs.append(f"[{m.type}] {m.text}"))
                    p.on("pageerror", lambda e: msgs.append(f"[pageerror] {e}"))
                    p.goto(f"{url}/bake_seq?pose=/poses/{POSES_NAME}&side=1&fps=30&ui=0&avatar={aid}",
                           wait_until="domcontentloaded")
                    try:
                        p.wait_for_function("() => window.__BAKE_READY__ || window.__BAKE_ERROR__", timeout=240_000)
                    except Exception:
                        out[aid] = {"error": "TIMEOUT", "console": msgs[:10]}
                        p.close()
                        continue
                    err = p.evaluate("() => window.__BAKE_ERROR__")
                    if err:
                        out[aid] = {"error": err, "console": msgs[:10]}
                        p.close()
                        continue
                    dump = []
                    while True:
                        step = p.evaluate("() => window.__bakeSeqStep()")
                        if step is None:
                            break
                        dump.append(p.evaluate(DUMP_JS))
                    out[aid] = dump
                    p.close()
            finally:
                b.close()
    finally:
        srv.shutdown()
        srv.server_close()

    # Load the frame metadata for printing (lean labels).
    meta = json.loads((POSE_DIR / POSES_NAME).read_text(encoding="utf-8"))
    print("=" * 78)
    for aid, dumps in out.items():
        if isinstance(dumps, dict) and dumps.get("error"):
            print(aid, "ERRO:", dumps["error"])
            for m in dumps.get("console", []):
                print("   ", m)
            continue
        print(f"\n{aid}:")
        for d in dumps:
            m = next((x for x in meta if x["frame"] == d["frame"]), {})
            lean = m.get("lean", "?")
            print(f"  frame {d['frame']} (lean {lean}°): angulos={d['angles']}")
            print(f"    pts   : {[[round(v, 3) for v in pt] for pt in d['pts']]}")
            print(f"    desvio (cm): {d['devsCm']}")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
