#!/usr/bin/env python3
"""Measure the avatar's SKINNED-MESH SURFACE, not the bones.

The user reports a sunken belly and "mountain" ridges on the back. Those are
surface deformations — the skinned mesh stretched or compressed by bones sitting
far from their bind pose. Bone-angle probes cannot see them; this one reads the
actual rendered vertex positions.

For each chosen real frame it loads the avatar through the bake_seq viewer,
skins every vertex to world space, then measures the TORSO cylinder between the
hips and the neck:

  belly_depth : for FRONT (chest-side) vertices around the pelvis level, how far
                the surface dips INWARD from the band's own p85 baseline. A
                sunken belly shows as a positive depth in centimetres.
  back_bumps  : for BACK vertices, RMS (and p99) deviation of the radial
                distance from a smooth quadratic baseline along the torso.
                "Mountains" show as a large RMS (high-frequency ridges).

The vertex filter runs IN THE PAGE so high-poly assets (boxeador: 730k verts)
do not move megabytes over the browser bridge.

Usage:
  python scripts/probe_mesh_surface.py --frames 440 --avatar boxeador
  python scripts/probe_mesh_surface.py --ab   # serve the A/B solver copy
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

from compare_palm_frames import Handler  # noqa: E402

POSE_DIR = LAB_ROOT / "experiments" / "bake_top"
POSES_NAME = "fidelity_frames.json"

# Torso cylinder (fraction of hips->neck length, metres) used to cut the vertex
# set down to the region of interest BEFORE the browser bridge.
U_MIN, U_MAX = -0.15, 0.70
R_MAX = 0.40

DUMP_JS = r"""
() => {
  const THREE = window.__BAKE_THREE__;
  const av = window.__BAKE_AVATAR__;
  const rig = window.__BAKE_RIG__;
  av.updateMatrixWorld(true);
  const gp = (n) => {
    const r = rig.bones.get(n);
    if (!r) return null;
    return r.bone.getWorldPosition(new THREE.Vector3());
  };
  const hips = gp('hips'), neck = gp('neck'), lu = gp('leftUpLeg'), ru = gp('rightUpLeg');
  if (!hips || !neck || !lu || !ru) return { error: 'missing trunk bones' };
  const axis = neck.clone().sub(hips);
  const L = axis.length();
  axis.normalize();
  const across = ru.clone().sub(lu);
  const fwd = new THREE.Vector3().crossVectors(across, axis).normalize();

  const meshes = [];
  av.traverse((n) => { if (n.isSkinnedMesh) meshes.push(n); });
  const pts = [];
  const v = new THREE.Vector3(), rel = new THREE.Vector3(), rad = new THREE.Vector3();
  for (const m of meshes) {
    m.skeleton.update();
    m.updateWorldMatrix(true, true);
    const pos = m.geometry.attributes.position;
    for (let i = 0; i < pos.count; i++) {
      m.boneTransform(i, v);
      v.applyMatrix4(m.matrixWorld);
      rel.copy(v).sub(hips);
      const u = rel.dot(axis);
      if (u < -0.15 * L || u > 0.70 * L) continue;
      rad.copy(rel).addScaledVector(axis, -u);
      const r = rad.length();
      if (r > 0.40) continue;
      pts.push(u, r, rad.dot(fwd) / Math.max(r, 1e-9));
    }
  }
  return { pts, hips: hips.toArray(), neck: neck.toArray(), L, frame: window.__BAKE_SEQ_FRAME__ };
}
"""


def step_to(page, target: int) -> bool:
    cur = page.evaluate("() => window.__BAKE_SEQ_FRAME__")
    guard = 0
    while cur < target:
        if page.evaluate("() => window.__bakeSeqStep()") is None:
            return False
        cur = page.evaluate("() => window.__BAKE_SEQ_FRAME__")
        guard += 1
        if guard > target + 5:
            return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--avatar", default="fighter-web")
    ap.add_argument("--frames", default="440")
    ap.add_argument("--ab", action="store_true",
                    help="serve the A/B solver (experiments/_solver_no_upright.js)")
    args = ap.parse_args()
    Handler.ab = args.ab

    frames_want = [int(x) for x in args.frames.split(",") if x.strip()]
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_port}"
    from playwright.sync_api import sync_playwright

    rows = []
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch(headless=True)
            try:
                p = b.new_page()
                msgs = []
                p.on("pageerror", lambda e: msgs.append(f"[pageerror] {e}"))
                p.goto(f"{url}/bake_seq?pose=/poses/{POSES_NAME}&side=1&fps=30&ui=0&avatar={args.avatar}",
                       wait_until="domcontentloaded")
                p.wait_for_function("() => window.__BAKE_READY__ || window.__BAKE_ERROR__",
                                    timeout=240_000)
                if p.evaluate("() => window.__BAKE_ERROR__"):
                    print("BAKE ERROR:", p.evaluate("() => window.__BAKE_ERROR__"))
                    print("\n".join(msgs[:6]))
                    return 1
                for t in frames_want:
                    if not step_to(p, t):
                        print(f"t={t}: could not step to frame")
                        continue
                    d = p.evaluate(DUMP_JS)
                    rows.append(analyze(d, t))
            finally:
                b.close()
    finally:
        srv.shutdown()
        srv.server_close()

    print("=" * 78)
    print(f"SURFACE (skinned mesh), avatar={args.avatar}, solver={'A/B' if args.ab else 'ATUAL'}")
    print("=" * 78)
    for r in rows:
        if r.get("error"):
            print(r["error"])
            continue
        print(f"\nt={r['t']}: {r['nverts']} verts no cilindro do tronco "
              f"(u {r['u0']:.2f}..{r['u1']:.2f}, r<{R_MAX}m)")
        print(f"  BELLY : depth={r['belly_depth']:+.2f}cm (dip>0 = afundada)   "
              f"p5..p95={r['belly_p5']:+.2f}..{r['belly_p95']:+.2f}cm")
        print(f"  BACK  : bump RMS={r['back_rms']:.2f}cm  "
              f"p99={r['back_p99']:+.2f}cm  max={r['back_max']:+.2f}cm  min={r['back_min']:+.2f}cm")
    return 0


def analyze(d: dict, t: int) -> dict:
    out = {"t": t, "error": None}
    if d.get("error"):
        out["error"] = f"t={t}: {d['error']}"
        return out
    pts = np.asarray(d["pts"], float).reshape(-1, 3)
    if len(pts) < 200:
        out["error"] = f"t={t}: too few torso verts ({len(pts)})"
        return out
    u, r, dot = pts[:, 0], pts[:, 1], pts[:, 2]
    L = float(d["L"])
    out["nverts"] = int(len(pts))
    out["u0"], out["u1"] = float(u.min() / L), float(u.max() / L)

    front = dot > 0.35
    back = dot < -0.35

    # Belly: abdomen around the pelvis level — the belly button is AT the hips
    # bone, not above it. u in [0.0, 0.45] of the hips->neck span.
    m = (u > 0.0) & (u < 0.45 * L) & front
    if m.sum() < 40:
        out["error"] = f"t={t}: too few belly verts ({m.sum()})"
        return out
    base = np.percentile(r[m], 85)
    depth = base - r[m]
    out["belly_depth"] = float(np.percentile(depth, 50))
    out["belly_p5"] = float(np.percentile(depth, 5))
    out["belly_p95"] = float(np.percentile(depth, 95))

    # Back: same cylinder, back hemisphere.
    mb = (u > 0.0) & (u < 0.55 * L) & back
    if mb.sum() < 40:
        out["error"] = f"t={t}: too few back verts ({mb.sum()})"
        return out
    ub, rb = u[mb] / L, r[mb]
    coef = np.polyfit(ub, rb, 2)
    resid = rb - np.polyval(coef, ub)
    out["back_rms"] = float(np.sqrt((resid ** 2).mean()))
    out["back_p99"] = float(np.percentile(resid, 99))
    out["back_max"] = float(resid.max())
    out["back_min"] = float(resid.min())
    return out


if __name__ == "__main__":
    raise SystemExit(main())
