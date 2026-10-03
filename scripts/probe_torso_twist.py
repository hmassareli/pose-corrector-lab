#!/usr/bin/env python3
"""Is the avatar's torso TWISTED relative to its pelvis, compared to the fit?

probe_spine_kink measures the pelvis->neck line and per-joint turning angles.
Both are invariant to rotation ABOUT that line, so a torso yawed a constant N
degrees relative to the hips is completely invisible to it — which is why the
spine chain looked "equivalent" on both assets while one still reads crooked.

Measured here instead: the signed horizontal angle between the HIP across
(leftUpLeg->rightUpLeg) and the SHOULDER across (leftArm->rightArm). That is
definition-free — it is the physical "how far are the shoulders twisted from the
pelvis", so the avatar's value and the fit's value are directly comparable with
no rig-convention constant to subtract. A constant bias between them is a
permanent torso twist; a large spread is tracking noise.

The trunk twist is driven by rest.restAcrossInRoot, which the builder sets for
spine/spine1/spine2/neck/head from the REST shoulder span. That span is assumed
lateral (purely +/-X). When a character is authored in an asymmetric stance
instead of a T/A-pose, the span is yawed, and every trunk frame inherits that
yaw as a constant error. probe_trunk_rest reports the rest span; this reports
what it costs on real frames.

Usage: python scripts/probe_torso_twist.py [--avatars boxeador,fighter-web]
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
POSES_NAME = "torso_twist_frames.json"

# SMPL-X 55 indices (same convention the other probes use).
J_PELVIS, J_LHIP, J_RHIP = 0, 1, 2
J_LSH, J_RSH = 16, 17

DUMP_JS = """
() => {
  const THREE = window.__BAKE_THREE__;
  const av = window.__BAKE_AVATAR__;
  const rig = window.__BAKE_RIG__;
  const inv = av.getWorldQuaternion(new THREE.Quaternion()).invert();
  const P = (n) => {
    const r = rig.bones.get(n);
    if (!r) return null;
    const p = r.bone.getWorldPosition(new THREE.Vector3()).applyQuaternion(inv);
    return [p.x, p.y, p.z];
  };
  // How far each trunk bone is driven from its BIND pose. Skinning weights are
  // authored at the bind pose, so this is the quantity that predicts mesh
  // distortion (sunken belly / bulging back) — independent of whether the bone
  // ANGLE is correct. A bone can track the fit perfectly and still wreck the
  // mesh if it sits far from where the weights were painted.
  const bind = {};
  for (const n of ["hips", "spine", "spine1", "spine2", "neck"]) {
    const r = rig.bones.get(n);
    if (!r) continue;
    bind[n] = Number((2 * Math.acos(Math.min(1, Math.abs(
      r.bone.quaternion.clone().dot(r.restLocalQuaternion)))) * 180 / Math.PI).toFixed(2));
  }
  // Bone TRANSLATION, in world centimetres. Rotating a skinned joint is what
  // the mesh was built for; TRANSLATING one stretches the skin across it, which
  // is what tears a belly inward or raises a ridge on a back. updateJointTranslations
  // offsets leftUpLeg/rightUpLeg (hips) and leftArm/rightArm (shoulders).
  //
  // It computes the offset in WORLD metres and adds it straight to bone.position,
  // which is in PARENT-LOCAL units. Those differ by the cumulative scale, so the
  // applied displacement is off by that factor on any asset not loaded at 1.0.
  const scale = av.getWorldScale(new THREE.Vector3()).x;
  const trans = {};
  for (const n of ["leftUpLeg", "rightUpLeg", "leftArm", "rightArm"]) {
    const r = rig.bones.get(n);
    if (!r) continue;
    trans[n] = Number((r.bone.position.distanceTo(r.restLocalPosition) * scale * 100).toFixed(3));
  }
  return {
    frame: window.__BAKE_SEQ_FRAME__,
    lUpLeg: P("leftUpLeg"), rUpLeg: P("rightUpLeg"),
    lArm: P("leftArm"), rArm: P("rightArm"),
    hips: P("hips"), neck: P("neck"), head: P("head"),
    bind, trans, scale,
  };
}
"""


def yaw_between(a, b) -> float | None:
    """Signed horizontal angle from across `a` to across `b`, in degrees.

    Both are flattened to the XZ plane (viewer is Y-up) so vertical shoulder
    tilt does not leak into the twist reading.
    """
    if a is None or b is None:
        return None
    a = np.array([a[0], 0.0, a[2]], float)
    b = np.array([b[0], 0.0, b[2]], float)
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na < 1e-6 or nb < 1e-6:
        return None
    a, b = a / na, b / nb
    # Signed about +Y: cross(a,b).y gives the sense of rotation.
    return float(np.degrees(np.arctan2(a[2] * b[0] - a[0] * b[2], a @ b)))


SOLVER = LAB_ROOT / "viewer" / "mikapo_mixamo_solver.js"
# A/B copy with the canonical-upright blend reference disabled. Both call sites
# read `rest.restUprightInRoot ? ... : restWorld`, so simply not assigning it
# restores the previous behaviour exactly — no other edit needed.
SOLVER_AB = LAB_ROOT / "experiments" / "_solver_no_upright.js"


NO_UPRIGHT = (
    "    rest.restUprightInRoot = up.multiply(rest.restQuaternionInRoot.clone());",
    "    // [A/B] upright reference disabled",
)

# Candidate fix under test: give each trunk bone its OWN authored lateral axis
# instead of the shared shoulder chord. The chord is a cross-body measurement, so
# on a character authored in a stance (fighter-web: shoulders yawed +9.5 deg from
# the pelvis in rest) it hands the lower back the shoulder girdle's yaw. The
# per-bone axis is the rigger's own convention and is 0.4 deg from the chord on a
# symmetric rig, so this must be a no-op on boxeador — that is the control.
# `head` is left on the chord: its axis disagrees by 23.6 deg and it runs through
# a different solve, so it is out of scope for this measurement.
AUTHORED_ACROSS = (
    """    for (const name of ["spine", "spine1", "spine2", "head", "neck"]) {
      const spine = bones.get(name);
      if (spine) spine.restAcrossInRoot = shoulderAcross.clone();
    }""",
    """    for (const name of ["spine", "spine1", "spine2", "head", "neck"]) {
      const spine = bones.get(name);
      if (!spine) continue;
      let across = shoulderAcross.clone();
      if (name !== "head") {
        let best = null;
        let bestDot = -Infinity;
        for (const v of [[1, 0, 0], [0, 1, 0], [0, 0, 1]]) {
          const a = new THREE.Vector3(...v).applyQuaternion(spine.restQuaternionInRoot);
          for (const sg of [1, -1]) {
            const c = a.clone().multiplyScalar(sg);
            const d = c.dot(shoulderAcross);
            if (d > bestDot) { bestDot = d; best = c; }
          }
        }
        if (best) across = best;
      }
      spine.restAcrossInRoot = across;
    }""",
)


# Candidate fix under test: name the trunk chain's reference children instead of
# taking children[0]. Without childAliases, Spine2's aim axis is whichever child
# the exporter listed first — on boxeador that is LeftShoulder, so the upper
# spine's "along the chain" axis points 26.5 deg off vertical with a 0.42 lateral
# share, and the retarget aims that sideways axis at a vertical target.
# fighter-web happens to list Neck first, so it is the control: it must not move.
CHILD_ALIASES = (
    """    ["spine", ["spine"]],
    ["spine1", ["spine1"]],
    ["spine2", ["spine2"]],
    ["neck", ["neck"]],""",
    """    ["spine", ["spine"], ["spine1"]],
    ["spine1", ["spine1"], ["spine2"]],
    ["spine2", ["spine2"], ["neck", "spine3"]],
    ["neck", ["neck"], ["head"]],""",
)


# Candidate fix under test: cover the WHOLE SMPL trunk chain.
#
# The rig has 3 spine bones spanning hips->neck; SMPL-X has 4 segments there
# (pelvis->spine1->spine2->spine3->neck). The current mapping takes the upper 3
# and drops pelvis->spine1, so each rig bone is aimed at the segment ABOVE the
# one it occupies. In a forward-bent trunk each successive segment leans further
# forward than the one below it, so that shift biases every bone forward and the
# errors add up the chain — measured as +9.3 deg of excess lean at the neck.
#
# Fix: pass all 5 waypoints and resample, deriving the stride from the waypoint
# count instead of the hardcoded 3 (which silently assumed 4 waypoints). That
# also generalises to rigs with 1, 2 or 4 spine bones.
FULL_CHAIN = (
    """    const waypoints = [aux.spine1, aux.spine2, aux.spine3, aux.neck];
    const present = ["spine", "spine1", "spine2"].filter((n) => rig.bones.get(n));
    const st = isSmplAux ? 0.95 : 0.7;
    const count = present.length;
    for (let i = 0; i < count; i++) {
      const a = waypoints[Math.round((i * 3) / count)];
      const b = waypoints[Math.round(((i + 1) * 3) / count)];""",
    """    const waypoints = [aux.pelvis, aux.spine1, aux.spine2, aux.spine3, aux.neck]
      .filter((p) => p);
    const present = ["spine", "spine1", "spine2"].filter((n) => rig.bones.get(n));
    const st = isSmplAux ? 0.95 : 0.7;
    const count = present.length;
    const seg = waypoints.length - 1;
    // Continuous chain parameterisation: bone i spans chain position
    // [i*seg/count, (i+1)*seg/count], interpolated between waypoints, so no
    // segment is dropped and no segment is doubled (the Math.round variant
    // skipped spine1->spine2 entirely, spiking spine1's bind deviation).
    const chainPoint = (u) => {
      const s = Math.min(seg - 1, Math.floor(u));
      const f = u - s;
      return waypoints[s].clone().lerp(waypoints[s + 1], f);
    };
    for (let i = 0; i < count; i++) {
      const a = chainPoint((i * seg) / count);
      const b = chainPoint(((i + 1) * seg) / count);""",
)


def write_ab_solver(patches) -> None:
    src = SOLVER.read_text(encoding="utf-8")
    for needle, repl in patches:
        if needle not in src:
            raise SystemExit("A/B: anchor not found — solver changed, update the probe")
        src = src.replace(needle, repl)
    SOLVER_AB.write_text(src, encoding="utf-8")


class H(Handler):
    ab = False

    def translate_path(self, path: str) -> str:
        from urllib.parse import unquote, urlparse
        route = unquote(urlparse(path).path)
        if route.startswith("/poses/"):
            return str(POSE_DIR / route[len("/poses/"):])
        if H.ab and route == "/static/mikapo_mixamo_solver.js":
            return str(SOLVER_AB)
        return super().translate_path(route)


def build_frames(n_frames: int) -> list[dict]:
    d = np.load(NPZ)
    fit = np.asarray(d["fit_joints"], dtype=np.float64)
    ok = np.asarray(d["ok"], dtype=bool)
    T = fit.shape[0]
    axis = fit[:, 12] - fit[:, J_PELVIS]
    valid = np.where(ok & (np.linalg.norm(axis, axis=1) > 0.05))[0]
    if len(valid) == 0:
        raise SystemExit("no valid frames")
    picks = valid[np.linspace(0, len(valid) - 1, min(n_frames, len(valid))).astype(int)]

    frames = []
    for t in picks:
        j55 = fit[t]
        # The fit's own hip->shoulder twist, in the SAME viewer space the avatar
        # dump uses: smplx55_to_lab applies the YZ flip, so derive the reference
        # from its output rather than from raw fit_joints.
        lab = smplx55_to_lab(j55)
        frames.append({
            "frame": int(t),
            "joints": np.round(lab, 6).tolist(),
            "aux_smpl": smplx55_avatar_aux_json(j55),
            "fit_hip": (j55[J_RHIP] - j55[J_LHIP]).tolist(),
            "fit_sh": (j55[J_RSH] - j55[J_LSH]).tolist(),
            "fit_axis": (j55[12] - j55[J_PELVIS]).tolist(),
        })
    out = POSE_DIR / POSES_NAME
    out.write_text(json.dumps([{k: v for k, v in f.items()
                               if k in ("frame", "joints", "aux_smpl")} for f in frames],
                              separators=(",", ":")), encoding="utf-8")
    print(f"[frames] {out}  n={len(frames)}")
    return frames


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--avatars", default="boxeador,fighter-web")
    ap.add_argument("--frames", type=int, default=24)
    ap.add_argument("--no-upright", action="store_true",
                    help="A/B: serve a solver without the canonical-upright blend reference")
    ap.add_argument("--authored-across", action="store_true",
                    help="A/B: trunk bones use their own authored lateral axis, not the shoulder chord")
    ap.add_argument("--child-aliases", action="store_true",
                    help="A/B: name the trunk chain's reference children instead of taking children[0]")
    ap.add_argument("--full-chain", action="store_true",
                    help="A/B: map the whole SMPL trunk chain, including pelvis->spine1")
    args = ap.parse_args()
    patches = []
    if args.no_upright:
        patches.append(NO_UPRIGHT)
        print("[A/B] solver SEM a referencia ereta canonica")
    if args.authored_across:
        patches.append(AUTHORED_ACROSS)
        print("[A/B] solver com across lateral AUTORADO por osso")
    if args.child_aliases:
        patches.append(CHILD_ALIASES)
        print("[A/B] solver com childAliases nomeados na cadeia do tronco")
    if args.full_chain:
        patches.append(FULL_CHAIN)
        print("[A/B] solver mapeando a cadeia SMPL COMPLETA (inclui pelve->spine1)")
    if patches:
        write_ab_solver(patches)
        H.ab = True

    meta = build_frames(args.frames)
    # Fit reference twist, in the SAME space as the avatar dump. smplx55_to_lab
    # only reindexes; the YZ flip lives in the viewer, so apply it here (same
    # diag(1,-1,-1) the palm scripts use). It matters for the SIGN: the flip
    # negates z but not x, so the signed yaw about +Y inverts. Comparing an
    # unflipped fit against a flipped avatar would report roughly double the
    # real error and get its direction backwards.
    FLIP = np.diag([1.0, -1.0, -1.0])
    fit_twist = [yaw_between(FLIP @ np.array(m["fit_hip"]), FLIP @ np.array(m["fit_sh"]))
                 for m in meta]
    # Trunk LEAN: angle of the pelvis->neck line off vertical. This is the "hunch"
    # axis, orthogonal to the twist above. probe_spine_kink measured DEVIATION FROM
    # that line, which says whether the chain is straight — not which way it points.
    # A torso folded 20 deg too far forward is a perfectly straight chain.
    fit_lean = [float(np.degrees(np.arccos(np.clip(
        (FLIP @ np.array(m["fit_axis"]))[1] / max(np.linalg.norm(m["fit_axis"]), 1e-9), -1, 1))))
        for m in meta]

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
                    p.on("pageerror", lambda e: msgs.append(f"[pageerror] {e}"))
                    p.goto(f"{url}/bake_seq?pose=/poses/{POSES_NAME}&side=1&fps=30&ui=0&avatar={aid}",
                           wait_until="domcontentloaded")
                    try:
                        p.wait_for_function("() => window.__BAKE_READY__ || window.__BAKE_ERROR__",
                                            timeout=240_000)
                    except Exception:
                        out[aid] = {"error": "TIMEOUT", "console": msgs[:6]}
                        p.close()
                        continue
                    err = p.evaluate("() => window.__BAKE_ERROR__")
                    if err:
                        out[aid] = {"error": err, "console": msgs[:6]}
                        p.close()
                        continue
                    # Rest-pose twist, before any frame is applied.
                    rest = p.evaluate(DUMP_JS)
                    dump = []
                    while True:
                        if p.evaluate("() => window.__bakeSeqStep()") is None:
                            break
                        dump.append(p.evaluate(DUMP_JS))
                    out[aid] = {"rest": rest, "frames": dump}
                    p.close()
            finally:
                b.close()
    finally:
        srv.shutdown()
        srv.server_close()

    print("=" * 78)
    print("TORCAO DO TRONCO: angulo horizontal quadril->ombros (avatar vs fit)")
    print("=" * 78)
    summary = {}
    for aid, r in out.items():
        if r.get("error"):
            print(f"\n{aid}: ERRO {r['error']}")
            for m in r.get("console", []):
                print("   ", m)
            continue
        rest_tw = yaw_between(
            np.array(r["rest"]["rUpLeg"]) - np.array(r["rest"]["lUpLeg"]),
            np.array(r["rest"]["rArm"]) - np.array(r["rest"]["lArm"]))
        errs = []
        rows = []
        # Index by SEQUENCE POSITION, not by d["frame"]: __BAKE_SEQ_FRAME__ is
        # the viewer's index into the pose file, not the original NLF frame
        # number. Keying on it silently kept only the frames where the two
        # happened to coincide (one, frame 0).
        for i, d in enumerate(r["frames"]):
            if i >= len(meta):
                break
            if None in (d["lUpLeg"], d["rUpLeg"], d["lArm"], d["rArm"]):
                continue
            av = yaw_between(np.array(d["rUpLeg"]) - np.array(d["lUpLeg"]),
                             np.array(d["rArm"]) - np.array(d["lArm"]))
            ft = fit_twist[i]
            if av is None or ft is None:
                continue
            d = {**d, "frame": meta[i]["frame"]}
            e = av - ft
            e = (e + 180) % 360 - 180
            errs.append(e)
            rows.append((d["frame"], av, ft, e))
        if not errs:
            print(f"\n{aid}: nenhum frame utilizavel")
            continue
        errs = np.array(errs)
        summary[aid] = errs
        print(f"\n{aid}:  torcao no REPOUSO do rig = {rest_tw:+.1f}°")
        print(f"  {'frame':>7}{'avatar':>10}{'fit':>10}{'erro':>10}")
        for fr, av, ft, e in rows[:10]:
            print(f"  {fr:>7}{av:>9.1f}°{ft:>9.1f}°{e:>9.1f}°")
        if len(rows) > 10:
            print(f"  ... ({len(rows)} frames)")
        print(f"  VIES CONSTANTE (media) = {errs.mean():+.1f}°"
              f"   |  espalhamento (std) = {errs.std():.1f}°"
              f"   |  |erro| p50 = {np.percentile(np.abs(errs), 50):.1f}°")
        keys = [k for k in ("hips", "spine", "spine1", "spine2", "neck")
                if any(k in d.get("bind", {}) for d in r["frames"])]
        if keys:
            print("  desvio da BIND pose (media / p95) — prediz distorcao de malha:")
            tot = []
            for k in keys:
                v = np.array([d["bind"][k] for d in r["frames"] if k in d.get("bind", {})])
                print(f"    {k:<8}{v.mean():>7.1f}°{np.percentile(v, 95):>9.1f}°")
                tot.append(v)
            print(f"    {'SOMA':<8}{np.sum([v.mean() for v in tot]):>7.1f}°"
                  f"{np.sum([np.percentile(v, 95) for v in tot]):>9.1f}°")
        leans = []
        for i, d in enumerate(r["frames"]):
            if i >= len(meta) or not d.get("hips") or not d.get("neck"):
                continue
            ax = np.array(d["neck"], float) - np.array(d["hips"], float)
            n = np.linalg.norm(ax)
            if n < 1e-6:
                continue
            leans.append((float(np.degrees(np.arccos(np.clip(ax[1] / n, -1, 1)))), fit_lean[i]))
        if leans:
            av_l = np.array([a for a, _ in leans])
            ft_l = np.array([f for _, f in leans])
            de = av_l - ft_l
            print(f"  INCLINACAO do tronco (fora da vertical): avatar {av_l.mean():.1f}°"
                  f"  vs fit {ft_l.mean():.1f}°"
                  f"  ->  curvado {de.mean():+.1f}° a mais (max {de.max():+.1f}°)")
        tk = [k for k in ("leftUpLeg", "rightUpLeg", "leftArm", "rightArm")
              if any(k in d.get("trans", {}) for d in r["frames"])]
        if tk:
            sc = r["frames"][0].get("scale")
            print(f"  translacao de osso (media / max, cm no mundo)   escala do root = {sc:.6f}:")
            for k in tk:
                v = np.array([d["trans"][k] for d in r["frames"] if k in d.get("trans", {})])
                print(f"    {k:<11}{v.mean():>8.3f}{v.max():>9.3f}")

    if len(summary) == 2:
        ks = list(summary)
        print(f"\nDiferenca de vies entre os dois personagens: "
              f"{summary[ks[1]].mean() - summary[ks[0]].mean():+.1f}°"
              f"  ({ks[1]} menos {ks[0]})")
    print("\nLeitura: o vies constante e uma torcao PERMANENTE do tronco (o rig")
    print("inteiro sai torto). O espalhamento e erro de rastreio, nao de rig.")
    (LAB_ROOT / "experiments" / "torso_twist_probe.json").write_text(
        json.dumps(out, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
