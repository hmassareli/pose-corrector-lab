#!/usr/bin/env python3
"""Rest-pose geometry of the TRUNK reference axes, per character asset.

The spine solve is rig-independent (same Spine/Spine1/Spine2 chain on both
assets, driven by the same SMPL waypoints), so a character that looks crooked
while another looks straight on the SAME pose must differ in its REST
references. Two of those feed every trunk frame:

  restDirection   the bone's aim axis. If childAliases do not resolve, the
                  builder falls back to children[0] — on Mixamo, Spine2's first
                  child is LeftShoulder, so the "spine" axis becomes a LATERAL
                  vector and the retarget aims sideways-at-vertical.
  restAcross      shoulder span (rightArm - leftArm) in rest, shared by
                  spine/spine1/spine2/neck/head. Its tilt is a CONSTANT twist
                  offset on the whole torso — exactly a permanent lean.

Reports both in root space: angle of restDirection off +Y, its lateral share,
and the across's tilt off horizontal plus its asymmetry.

Usage: python scripts/probe_trunk_rest.py [--avatars boxeador,fighter-web]
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB_ROOT / "scripts"))

from check_palm_fidelity import Handler  # noqa: E402

TRUNK = ["hips", "spine", "spine1", "spine2", "neck", "head"]

PROBE_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"/>
<script type="importmap">{"imports":{"three":"https://unpkg.com/three@0.160.0/build/three.module.js","three/addons/":"https://unpkg.com/three@0.160.0/examples/jsm/"}}</script>
</head><body><script type="module">
window.__R__ = null; window.__E__ = null;
try {
  const THREE = await import("three");
  const { loadAvatar } = await import("/static/avatar_assets.js");
  const { buildAvatarRig } = await import("/static/mikapo_mixamo_solver.js");
  const id = new URLSearchParams(location.search).get("avatar");
  const { root, spec } = await loadAvatar(id);
  const rig = buildAvatarRig(root);
  const V = (v) => [v.x, v.y, v.z];
  const trunk = {};
  for (const k of __TRUNK__) {
    const r = rig.bones.get(k);
    if (!r) continue;
    // The bone's OWN authored rest axes, in root space. If the rigger kept a
    // consistent convention these carry the body's medial-lateral direction
    // regardless of how the limbs were posed for the rest pose, which a
    // cross-body shoulder span does not.
    const axes = {};
    for (const [nm, v] of [["x", [1,0,0]], ["y", [0,1,0]], ["z", [0,0,1]]]) {
      axes[nm] = V(new THREE.Vector3(...v).applyQuaternion(r.restQuaternionInRoot));
    }
    trunk[k] = {
      bone: r.bone.name,
      child: r.child ? r.child.name : null,
      dir: V(r.restDirectionInRoot),
      across: r.restAcrossInRoot ? V(r.restAcrossInRoot) : null,
      hasUpright: !!r.restUprightInRoot,
      axes,
    };
  }
  // The raw span the builder uses for the shared trunk across.
  const la = rig.bones.get("leftArm"), ra = rig.bones.get("rightArm");
  let span = null;
  if (la && ra) {
    const inv = root.getWorldQuaternion(new THREE.Quaternion()).invert();
    span = V(ra.bone.getWorldPosition(new THREE.Vector3())
      .sub(la.bone.getWorldPosition(new THREE.Vector3()))
      .normalize().applyQuaternion(inv));
  }
  window.__R__ = { spec, trunk, span };
} catch (e) { window.__E__ = String(e && e.stack || e); }
</script></body></html>
"""


class H(Handler):
    def translate_path(self, path: str) -> str:
        from urllib.parse import unquote, urlparse
        if unquote(urlparse(path).path) == "/probe":
            return str(LAB_ROOT / "experiments" / "_probe_trunk.html")
        return super().translate_path(path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--avatars", default="boxeador,fighter-web")
    args = ap.parse_args()

    (LAB_ROOT / "experiments").mkdir(exist_ok=True)
    (LAB_ROOT / "experiments" / "_probe_trunk.html").write_text(
        PROBE_HTML.replace("__TRUNK__", json.dumps(TRUNK)), encoding="utf-8")

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_port}"
    from playwright.sync_api import sync_playwright

    import numpy as np

    out = {}
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch(headless=True)
            try:
                for aid in [a.strip() for a in args.avatars.split(",") if a.strip()]:
                    p = b.new_page()
                    p.goto(f"{url}/probe?avatar={aid}", wait_until="domcontentloaded")
                    p.wait_for_function("() => window.__R__ || window.__E__", timeout=240_000)
                    err = p.evaluate("() => window.__E__")
                    out[aid] = {"error": err} if err else p.evaluate("() => window.__R__")
                    p.close()
            finally:
                b.close()
    finally:
        srv.shutdown()
        srv.server_close()

    def ang(a, b):
        a, b = np.asarray(a, float), np.asarray(b, float)
        a, b = a / np.linalg.norm(a), b / np.linalg.norm(b)
        return float(np.degrees(np.arccos(np.clip(a @ b, -1, 1))))

    for aid, r in out.items():
        print("=" * 74)
        print(aid, "" if not r.get("error") else "ERRO: " + r["error"])
        if r.get("error"):
            continue
        print(f"  {r['spec']['label']}")
        print(f"  {'bone':<8}{'off +Y':>9}{'lateral':>9}{'up-ref':>8}  child")
        for k in TRUNK:
            t = r["trunk"].get(k)
            if not t:
                continue
            d = np.array(t["dir"], float)
            d = d / np.linalg.norm(d)
            # Lateral share = |x| component: how much of the aim axis points
            # sideways instead of along the body. A spine axis with a big
            # lateral share is pointing at a shoulder, not up the chain.
            print(f"  {k:<8}{ang(d,[0,1,0]):>8.1f}°{abs(d[0]):>9.2f}"
                  f"{('yes' if t['hasUpright'] else 'NO'):>8}  {t['child']}")
        if r.get("span"):
            s = np.array(r["span"], float)
            print(f"  across ombros: tilt fora do horizontal {abs(np.degrees(np.arcsin(np.clip(s[1],-1,1)))):.1f}°"
                  f"   (x={s[0]:+.3f} y={s[1]:+.3f} z={s[2]:+.3f})")
            # Which authored axis is the lateral one, and does it agree with the
            # span? A gap means the span carries stance asymmetry the authored
            # axis does not (or vice versa) — that gap IS the constant twist.
            print(f"  eixo lateral autorado por osso (o +/-eixo local mais proximo do span):")
            print(f"    {'bone':<8}{'eixo':>6}{'ang p/ span':>13}{'yaw vs span':>13}")
            for k in TRUNK:
                t = r["trunk"].get(k)
                if not t:
                    continue
                best, bang, bvec = None, 1e9, None
                for nm, v in t["axes"].items():
                    v = np.array(v, float)
                    for sg in (1.0, -1.0):
                        a = ang(sg * v, s)
                        if a < bang:
                            best, bang, bvec = f"{'+' if sg > 0 else '-'}{nm}", a, sg * v
                # Yaw-only gap (horizontal plane), which is the "torta" component.
                h = lambda v: np.array([v[0], 0.0, v[2]])
                hv, hs = h(bvec), h(s)
                yaw = np.degrees(np.arctan2(hv[2] * hs[0] - hv[0] * hs[2], hv @ hs))
                print(f"    {k:<8}{best:>6}{bang:>12.1f}°{yaw:>12.1f}°")

    (LAB_ROOT / "experiments" / "trunk_rest_probe.json").write_text(
        json.dumps(out, indent=1), encoding="utf-8")
    print(f"\n[report] {LAB_ROOT / 'experiments' / 'trunk_rest_probe.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
