#!/usr/bin/env python3
"""Report which rig bones the solver actually maps, per character asset.

Exists because a silent mapping gap is invisible from the render: `spine1`/
`spine2` were never matched (normalizedBoneName stripped digits), so the torso
was driven by ONE spine bone and nothing warned about it. Run this whenever a
new character is added.

Usage: python scripts/probe_rig_mapping.py [--avatars boxeador,fighter-web]
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

EXPECTED = [
    "hips", "spine", "spine1", "spine2", "neck", "head",
    "leftShoulder", "rightShoulder", "leftArm", "rightArm",
    "leftForeArm", "rightForeArm", "leftHand", "rightHand",
    "leftUpLeg", "rightUpLeg", "leftLeg", "rightLeg", "leftFoot", "rightFoot",
]

PROBE_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"/>
<script type="importmap">{"imports":{"three":"https://unpkg.com/three@0.160.0/build/three.module.js","three/addons/":"https://unpkg.com/three@0.160.0/examples/jsm/"}}</script>
</head><body><script type="module">
window.__R__ = null; window.__E__ = null;
try {
  const { loadAvatar } = await import("/static/avatar_assets.js");
  const { buildAvatarRig } = await import("/static/mikapo_mixamo_solver.js");
  const id = new URLSearchParams(location.search).get("avatar");
  const { root, spec } = await loadAvatar(id);
  const all = []; root.traverse(n => { if (n.isBone || n.type === "Bone") all.push(n.name); });
  const rig = buildAvatarRig(root);
  const mapped = {};
  for (const [k, v] of rig.bones) mapped[k] = { bone: v.bone.name, child: v.child ? v.child.name : null };
  const fingers = {};
  for (const side of ["left","right"]) {
    const hand = rig.bones.get(side === "left" ? "leftHand" : "rightHand");
    fingers[side] = hand ? hand.bone.children.filter(c => c.isBone || c.type === "Bone").map(c => c.name) : [];
  }
  window.__R__ = { spec, bone_nodes: all.length, unique: [...new Set(all)].length,
                   names: [...new Set(all)], mapped, fingers };
} catch (e) { window.__E__ = String(e && e.stack || e); }
</script></body></html>
"""


class H(Handler):
    def translate_path(self, path: str) -> str:
        from urllib.parse import unquote, urlparse
        if unquote(urlparse(path).path) == "/probe":
            return str(LAB_ROOT / "experiments" / "_probe_rig.html")
        return super().translate_path(path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--avatars", default="boxeador,fighter-web")
    args = ap.parse_args()

    (LAB_ROOT / "experiments").mkdir(exist_ok=True)
    (LAB_ROOT / "experiments" / "_probe_rig.html").write_text(PROBE_HTML, encoding="utf-8")

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
                    p.on("requestfailed", lambda r: msgs.append(f"[reqfail] {r.url}"))
                    p.goto(f"{url}/probe?avatar={aid}", wait_until="domcontentloaded")
                    try:
                        p.wait_for_function("() => window.__R__ || window.__E__", timeout=240_000)
                    except Exception:
                        out[aid] = {"error": "TIMEOUT", "console": msgs[:10]}
                        p.close()
                        continue
                    err = p.evaluate("() => window.__E__")
                    out[aid] = {"error": err, "console": msgs[:10]} if err else p.evaluate("() => window.__R__")
                    p.close()
            finally:
                b.close()
    finally:
        srv.shutdown()
        srv.server_close()

    for aid, r in out.items():
        print("=" * 66)
        print(aid)
        if r.get("error"):
            print("  ERRO:", r["error"])
            for m in r.get("console", []):
                print("   ", m)
            continue
        print(f"  {r['spec']['label']}  ({r['spec']['format']}, scale {r['spec']['scale']})")
        print(f"  nós de osso: {r['bone_nodes']}   nomes únicos: {r['unique']}")
        print(f"  MAPEADOS: {len(r['mapped'])}/{len(EXPECTED)}")
        missing = [k for k in EXPECTED if k not in r["mapped"]]
        print(f"  FALTANDO: {missing or 'nenhum'}")
        for k in ["spine", "spine1", "spine2", "head", "leftHand", "rightHand"]:
            if k in r["mapped"]:
                m = r["mapped"][k]
                print(f"    {k:<11} bone={m['bone']:<26} child={m['child']}")
        for side, f in r["fingers"].items():
            print(f"    dedos {side}: {f}")

    (LAB_ROOT / "experiments" / "rig_mapping_probe.json").write_text(
        json.dumps(out, indent=1), encoding="utf-8")
    print(f"\n[report] {LAB_ROOT / 'experiments' / 'rig_mapping_probe.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
