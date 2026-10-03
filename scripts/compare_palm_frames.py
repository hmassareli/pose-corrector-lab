#!/usr/bin/env python3
"""Side-by-side close-ups: FIT MESH hand vs BAKED AVATAR hand, same frames, matched camera.

The numeric check lives in check_palm_fidelity.py; this is the eyeball check that
goes with it. For each requested frame it renders two panels framed on the SAME
anatomical point (the wrist) from the SAME world-space direction, so "is the palm
facing the ground or the side?" is directly comparable.

Panels: LEFT = SMPL-X fit mesh (ground truth), RIGHT = retargeted Mixamo avatar.
Each is labelled with that hand's palm-normal Y (-1 = palm facing the ground),
measured by the same index-chain construction check_palm_fidelity.py uses.

Usage:
  python scripts/compare_palm_frames.py --frames 440,470,480,500 --side right --tag baseline
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB_ROOT / "scripts"))

from absolute_palm_error import frame, unit  # noqa: E402

BAKE_DIR = LAB_ROOT / "experiments" / "bake_top"
MESH_DIR = LAB_ROOT / "experiments" / "nlf_fit_webcam1" / "render"
OUT_DIR = LAB_ROOT / "experiments" / "palm_compare"

# Close-up framing, in world/viewer space, relative to the wrist. A 3/4
# front-above view: palm-down vs palm-sideways is unambiguous from here.
CAM_OFFSET = np.array([0.34, 0.26, 0.42])
# Camera distance is expressed in hand lengths: HAND_REF is the wrist->index1
# distance that corresponds to CAM_OFFSET as written above.
HAND_REF = 0.09
# Same idea for the torso focus, but the natural yardstick there is the
# pelvis->neck length rather than a hand. Framing on a body-sized reference is
# what lets the two viewers (SMPL-X mesh ~1.7 m, avatar ~0.82) be compared: the
# panels end up showing the same fraction of the body, not the same metres.
TORSO_REF = 0.5
# A/B solver served at /static/ when --ab is passed (see probe_torso_twist.py:
# write_ab_solver writes the patched copy here).
SOLVER_AB = LAB_ROOT / "experiments" / "_solver_no_upright.js"


class Handler(SimpleHTTPRequestHandler):
    ab = False

    def log_message(self, fmt, *args):
        pass

    def translate_path(self, path: str) -> str:
        from urllib.parse import unquote, urlparse

        route = unquote(urlparse(path).path)
        if Handler.ab and route == "/static/mikapo_mixamo_solver.js":
            return str(SOLVER_AB)
        if route in {"/", "/bake", "/bake_seq"}:
            return str(LAB_ROOT / "viewer" / "avatar_bake_seq.html")
        if route == "/seq":
            return str(LAB_ROOT / "viewer" / "smpl_fit_seq.html")
        if route.startswith("/static/"):
            return str(LAB_ROOT / "viewer" / route[len("/static/"):])
        if route.startswith("/assets/"):
            return str(LAB_ROOT / "assets" / route[len("/assets/"):])
        if route.startswith("/poses/"):
            return str(BAKE_DIR / route[len("/poses/"):])
        if route.startswith("/data/"):
            return str(MESH_DIR / route[len("/data/"):])
        return super().translate_path(route)


READ_AVATAR = """(side) => {
  const THREE = window.__BAKE_THREE__;
  const av = window.__BAKE_AVATAR__;
  const norm = (s) => s.toLowerCase().replace(/[^a-z0-9]/g, '');
  const bones = [];
  av.traverse((n) => { if (n.isBone || n.type === 'Bone') bones.push(n); });
  const g = (suffix) => {
    const want = norm(suffix);
    const b = bones.find((n) => norm(n.name).endsWith(want));
    if (!b) return null;
    const p = b.getWorldPosition(new THREE.Vector3());
    return [p.x, p.y, p.z];
  };
  return {
    hand: g(side + 'hand'), i1: g(side + 'handindex1'),
    i2: g(side + 'handindex2'), i3: g(side + 'handindex3'),
    i4: g(side + 'handindex4'),
  };
}"""


def step_to(page, target: int) -> None:
    """Advance the viewer to frame `target` (viewers are step-only)."""
    cur = page.evaluate("() => window.__BAKE_SEQ_FRAME__")
    while cur < target:
        if page.evaluate("() => window.__bakeSeqStep()") is None:
            break
        cur = page.evaluate("() => window.__BAKE_SEQ_FRAME__")


def shoot(page, wrist: np.ndarray, label: str, out: Path, scale: float = 1.0) -> None:
    """`scale` normalises for the two viewers' different world scales (the GLB is
    ~1.0 units tall, the SMPL-X mesh ~1.7 m), so both panels frame the hand the
    same way. It is derived per-viewer from that rig's own hand length."""
    eye = wrist + CAM_OFFSET * scale
    page.evaluate("([e, t]) => window.__bakeLookAt(e, t)",
                  [[float(v) for v in eye], [float(v) for v in wrist]])
    page.evaluate("(t) => window.__bakeSetLabel(t)", label)
    page.locator("#stage").screenshot(path=str(out))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--frames", default="440,470,480,500")
    ap.add_argument("--side", default="right", choices=["left", "right"])
    ap.add_argument("--tag", default="baseline")
    ap.add_argument("--focus", default="hand", choices=["hand", "head", "torso"],
                    help="what to frame the close-up on")
    ap.add_argument("--avatar", default="boxeador",
                    help="character id from viewer/avatar_assets.js")
    ap.add_argument("--cam", default="0.34,0.26,0.42",
                    help="camera offset from the wrist, world space (x,y,z)")
    ap.add_argument("--zoom", type=float, default=1.0,
                    help="camera distance multiplier (>1 pulls back for context)")
    ap.add_argument("--poses", default="fidelity_frames.json",
                    help="frames JSON under experiments/bake_top/ to drive the avatar")
    ap.add_argument("--ab", action="store_true",
                    help="serve the A/B solver (experiments/_solver_no_upright.js) at /static/")
    args = ap.parse_args()
    Handler.ab = args.ab

    global CAM_OFFSET
    CAM_OFFSET = np.array([float(v) for v in args.cam.split(",")])
    frames = [int(x) for x in args.frames.split(",") if x.strip()]
    side = args.side
    out_dir = OUT_DIR / args.tag
    out_dir.mkdir(parents=True, exist_ok=True)

    meta = json.loads((MESH_DIR / "meta.json").read_text(encoding="utf-8"))
    jn = meta["joint_names"]
    ji = {n: i for i, n in enumerate(jn)}
    w_i, a_i, p_i = ji[f"{side}_wrist"], ji[f"{side}_index1"], ji[f"{side}_pinky1"]
    sgn = -1.0 if side == "left" else 1.0

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}"
    from playwright.sync_api import sync_playwright

    rows = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                mesh = browser.new_page(viewport={"width": 720, "height": 960})
                mesh.goto(f"{url}/seq?data=/data&mode=mesh&side=1", wait_until="domcontentloaded")
                mesh.wait_for_function("() => window.__BAKE_READY__ || window.__BAKE_ERROR__", timeout=90_000)
                if mesh.evaluate("() => window.__BAKE_ERROR__"):
                    raise RuntimeError("mesh viewer: " + mesh.evaluate("() => window.__BAKE_ERROR__"))

                av = browser.new_page(viewport={"width": 720, "height": 960})
                av.goto(f"{url}/bake_seq?pose=/poses/{args.poses}&side=1&fps=30"
                        f"&ui=0&avatar={args.avatar}",
                        wait_until="domcontentloaded")
                av.wait_for_function("() => window.__BAKE_READY__ || window.__BAKE_ERROR__", timeout=90_000)
                if av.evaluate("() => window.__BAKE_ERROR__"):
                    raise RuntimeError("avatar viewer: " + av.evaluate("() => window.__BAKE_ERROR__"))

                for t in frames:
                    step_to(mesh, t)
                    step_to(av, t)

                    # Fit mesh: anatomical palm frame from real SMPL-X knuckles.
                    jv = np.array(mesh.evaluate("() => window.__BAKE_JOINTS_VIEW__"), float).reshape(-1, 3)
                    m_wrist = jv[w_i]
                    Rm = frame((jv[a_i] + jv[p_i]) / 2 - jv[w_i], sgn * (jv[p_i] - jv[a_i]))
                    m_ny = float(Rm[1, 2]) if Rm is not None else float("nan")

                    # Avatar: same frame, across = plane normal of the posed
                    # hand+finger chain (rig geometry, not the solver's variable).
                    fg = av.evaluate(READ_AVATAR, side)
                    a_pts = {k: np.array(v, float) for k, v in fg.items() if v}
                    a_wrist = a_pts["hand"]
                    chain = np.array([a_pts[k] for k in ("hand", "i1", "i2", "i3", "i4")
                                      if k in a_pts], float)
                    a_ny = float("nan")
                    if len(chain) >= 4:
                        cen = chain.mean(axis=0)
                        _, _, Vt = np.linalg.svd(chain - cen)
                        n_pl = unit(Vt[2])
                        ref = unit(np.cross(unit(a_pts["i1"] - a_pts["hand"]), np.array([0, 1.0, 0])))
                        if np.dot(n_pl, ref) < 0:
                            n_pl = -n_pl
                        Ra = frame(a_pts["i1"] - a_pts["hand"], n_pl)
                        if Ra is not None:
                            a_ny = float(Ra[1, 2])

                    # Frame both panels at the same multiple of hand length.
                    m_scale = float(np.linalg.norm(jv[a_i] - jv[w_i])) / HAND_REF * args.zoom
                    a_scale = float(np.linalg.norm(a_pts["i1"] - a_pts["hand"])) / HAND_REF * args.zoom
                    if args.focus == "torso":
                        # The reported symptom (caved abdomen, ridged back) is a
                        # SKIN artifact, so frame the trunk and let the mesh be
                        # the evidence — every other probe here reads bones and
                        # is blind to how the skin lands on them.
                        m_pelvis, m_neck = jv[ji["pelvis"]], jv[ji["neck"]]
                        m_wrist = (m_pelvis + m_neck) / 2
                        m_scale = float(np.linalg.norm(m_neck - m_pelvis)) / TORSO_REF * args.zoom
                        tb = av.evaluate("""() => {
                          const THREE = window.__BAKE_THREE__;
                          const rig = window.__BAKE_RIG__;
                          const P = (n) => {
                            const b = rig.bones.get(n);
                            if (!b) return null;
                            const p = b.bone.getWorldPosition(new THREE.Vector3());
                            return [p.x, p.y, p.z];
                          };
                          return { hips: P('hips'), neck: P('neck') };
                        }""")
                        if tb and tb["hips"] and tb["neck"]:
                            a_hips = np.array(tb["hips"], float)
                            a_neck = np.array(tb["neck"], float)
                            a_wrist = (a_hips + a_neck) / 2
                            a_scale = float(np.linalg.norm(a_neck - a_hips)) / TORSO_REF * args.zoom
                        m_lab, a_lab = f"FIT MESH  t={t}", f"AVATAR {args.avatar}  t={t}"
                    elif args.focus == "head":
                        # Frame on the head instead; palmY is meaningless here.
                        m_wrist = jv[ji["head"]]
                        hb = av.evaluate("""() => {
                          const THREE = window.__BAKE_THREE__;
                          const b = window.__BAKE_RIG__.bones.get('head');
                          if (!b) return null;
                          const p = b.bone.getWorldPosition(new THREE.Vector3());
                          return [p.x, p.y, p.z];
                        }""")
                        if hb:
                            a_wrist = np.array(hb, float)
                        m_lab, a_lab = f"FIT MESH  t={t}", f"AVATAR  t={t}"
                    else:
                        m_lab = f"FIT MESH  t={t}  palmY={m_ny:+.2f}"
                        a_lab = f"AVATAR  t={t}  palmY={a_ny:+.2f}"
                    shoot(mesh, m_wrist, m_lab, out_dir / f"t{t:04d}_a_mesh.png", m_scale)
                    shoot(av, a_wrist, a_lab, out_dir / f"t{t:04d}_b_avatar.png", a_scale)
                    rows.append({"t": t, "mesh_palm_y": round(m_ny, 3),
                                 "avatar_palm_y": round(a_ny, 3),
                                 "delta": round(abs(m_ny - a_ny), 3)})
                    print(f"  t={t:4d}  mesh palmY {m_ny:+.2f}   avatar palmY {a_ny:+.2f}"
                          f"   |diff| {abs(m_ny - a_ny):.2f}", flush=True)
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()

    # Stitch each frame's two panels into one image.
    try:
        from PIL import Image
        for t in frames:
            pa = out_dir / f"t{t:04d}_a_mesh.png"
            pb = out_dir / f"t{t:04d}_b_avatar.png"
            if not (pa.is_file() and pb.is_file()):
                continue
            ia, ib = Image.open(pa), Image.open(pb)
            comp = Image.new("RGB", (ia.width + ib.width, max(ia.height, ib.height)), (14, 17, 22))
            comp.paste(ia, (0, 0))
            comp.paste(ib, (ia.width, 0))
            comp.save(out_dir / f"compare_t{t:04d}.png")
        print(f"[img] stitched -> {out_dir}")
    except ImportError:
        print("[img] PIL not available; panels saved unstitched")

    (out_dir / "summary.json").write_text(
        json.dumps({"side": side, "tag": args.tag, "rows": rows}, indent=1), encoding="utf-8")
    print(f"[report] {out_dir / 'summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
