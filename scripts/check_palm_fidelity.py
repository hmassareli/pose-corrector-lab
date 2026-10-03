#!/usr/bin/env python3
"""Non-circular palm-fidelity check: does the RENDERED avatar's hand track the FIT's palm?

Why this exists
---------------
`render_bake_top.py --verify` is CIRCULAR: it reconstructs the avatar's across from
`rest.restAcrossInRoot` — the exact vector `rotateBoneWithAcross` just solved onto the
target. It measures the solver's own objective, so it passes by construction even when
`restAcrossInRoot` is the wrong axis for this mesh.

This check never touches `restAcrossInRoot`.

  * FIT side (ground truth): a palm frame built from real SMPL-X anatomy —
        across = unit(pinky1 - index1)              # true knuckle axis, well conditioned
        fwd    = unit(mid(index1,pinky1) - wrist)   # along the hand, orthogonalized
        normal = unit(fwd x across)                 # palm facing direction
  * AVATAR side (measurement): the hand bone's WORLD QUATERNION, taken straight off the
    rendered rig. Exact and noise-free — no finger geometry, no rig assumption.
    (An earlier version derived the avatar frame from its index chain; the boxing glove's
    chain is nearly collinear (S2/S1 ~ 0.10) so that estimate was unusable — it reported a
    spurious 140 deg offset on the right hand. The bone quaternion has no such problem.)

The avatar's bone frame and the fit's anatomical frame differ by an unknown but CONSTANT
rig offset, so the metric splits R_err(t) = R_avatar(t) @ R_fit(t)^T into:

    rest offset  = geodesic mean of R_err   -> arbitrary rig constant, NOT a defect
    tracking err = spread of R_err about it -> THE DEFECT. Should be ~0 for a correct
                                               retarget. This is the number that matters.

Then, with that constant removed, the avatar's calibrated palm normal is directly
comparable to the fit's, which gives the metric the eye actually judges:
"during the punch, does the palm turn toward the ground?" (normal_y -> -1).

Usage:  python scripts/check_palm_fidelity.py [--tag baseline] [--step 4]
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

from render_bake_top import (  # noqa: E402
    DEFAULT_NPZ,
    OUT_DIR,
    SMPLX_NPZ,
    SmplxCanon,
    build_fk,
    build_frames,
)

# Frames the author flagged as the punch (palm should turn toward the ground).
PUNCH_WINDOW = (440, 510)


def unit(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else np.zeros(3)


def fit_palm_frame(wrist, index1, pinky1):
    """Orthonormal palm frame from SMPL-X anatomy. Columns = [across, fwd, normal]."""
    across = unit(pinky1 - index1)
    fwd_raw = (index1 + pinky1) / 2.0 - wrist
    if np.linalg.norm(across) < 1e-9 or np.linalg.norm(fwd_raw) < 1e-9:
        return None
    fwd = unit(fwd_raw - across * float(np.dot(fwd_raw, across)))
    if np.linalg.norm(fwd) < 1e-9:
        return None
    normal = unit(np.cross(fwd, across))
    if np.linalg.norm(normal) < 1e-9:
        return None
    return np.column_stack([across, fwd, normal])


def quat_to_mat(q: np.ndarray) -> np.ndarray:
    x, y, z, w = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def mat_to_quat(R: np.ndarray) -> np.ndarray:
    t = np.trace(R)
    if t > 0:
        s = np.sqrt(t + 1.0) * 2
        return np.array([(R[2, 1] - R[1, 2]) / s, (R[0, 2] - R[2, 0]) / s,
                         (R[1, 0] - R[0, 1]) / s, 0.25 * s])
    i = int(np.argmax(np.diag(R)))
    if i == 0:
        s = np.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2]) * 2
        return np.array([0.25 * s, (R[0, 1] + R[1, 0]) / s, (R[0, 2] + R[2, 0]) / s,
                         (R[2, 1] - R[1, 2]) / s])
    if i == 1:
        s = np.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2]) * 2
        return np.array([(R[0, 1] + R[1, 0]) / s, 0.25 * s, (R[1, 2] + R[2, 1]) / s,
                         (R[0, 2] - R[2, 0]) / s])
    s = np.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1]) * 2
    return np.array([(R[0, 2] + R[2, 0]) / s, (R[1, 2] + R[2, 1]) / s, 0.25 * s,
                     (R[1, 0] - R[0, 1]) / s])


def geodesic_mean(rots: list[np.ndarray]) -> np.ndarray:
    qs = np.array([mat_to_quat(R) for R in rots])
    ref = qs[0]
    qs[qs @ ref < 0] *= -1
    q = qs.mean(axis=0)
    return quat_to_mat(q / np.linalg.norm(q))


def angle_deg(R: np.ndarray) -> float:
    return float(np.degrees(np.arccos(np.clip((np.trace(R) - 1) / 2, -1, 1))))


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def translate_path(self, path: str) -> str:
        from urllib.parse import unquote, urlparse

        route = unquote(urlparse(path).path)
        if route in {"/", "/bake", "/bake_seq"}:
            return str(LAB_ROOT / "viewer" / "avatar_bake_seq.html")
        if route.startswith("/static/"):
            return str(LAB_ROOT / "viewer" / route[len("/static/"):])
        if route.startswith("/assets/"):
            return str(LAB_ROOT / "assets" / route[len("/assets/"):])
        if route.startswith("/poses/"):
            return str(OUT_DIR / route[len("/poses/"):])
        return super().translate_path(route)


# Hand bone world quaternion, expressed in ROOT space (same space as the fit dirs).
READ_HANDS = """() => {
  const THREE = window.__BAKE_THREE__;
  const av = window.__BAKE_AVATAR__;
  const inv = av.getWorldQuaternion(new THREE.Quaternion()).invert();
  const rig = window.__BAKE_RIG__;
  const out = {};
  for (const side of ['left', 'right']) {
    const rest = rig.bones.get(side === 'left' ? 'leftHand' : 'rightHand');
    if (!rest) continue;
    const q = rest.bone.getWorldQuaternion(new THREE.Quaternion());
    const r = inv.clone().multiply(q);
    out[side] = [r.x, r.y, r.z, r.w];
  }
  return out;
}"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tag", default="baseline")
    ap.add_argument("--step", type=int, default=4)
    ap.add_argument("--npz", type=Path, default=DEFAULT_NPZ)
    args = ap.parse_args()

    d = np.load(args.npz)
    names = [str(n) for n in d["smplx55_names"]]
    idx = {n: i for i, n in enumerate(names)}
    fj = d["fit_joints"].astype(np.float64)
    T = fj.shape[0]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cache = OUT_DIR / "fidelity_frames.json"
    reuse = False
    if cache.is_file():
        try:
            reuse = len(json.loads(cache.read_text(encoding="utf-8"))) == T
        except Exception:
            reuse = False
    if reuse:
        print(f"[fit] reusing cached {cache.name} ({T} frames)", flush=True)
    else:
        canon = SmplxCanon(SMPLX_NPZ).canon
        kt = np.asarray(np.load(SMPLX_NPZ, allow_pickle=True)["kintree_table"])
        print(f"[fit] building FK for {T} frames...", flush=True)
        Rw = build_fk(d["pose"].astype(np.float64), kt)
        cache.write_text(json.dumps(build_frames(fj, names, "fk", Rw, canon)), encoding="utf-8")

    sample = list(range(0, T, args.step))

    # --- ground truth: fit palm frames (NLF -> viewer dirs via (x,-y,-z), det +1) ---
    flip = np.diag([1.0, -1.0, -1.0])
    fit_R: dict[str, dict[int, np.ndarray]] = {"left": {}, "right": {}}
    for side in ("left", "right"):
        w, a, p = idx[f"{side}_wrist"], idx[f"{side}_index1"], idx[f"{side}_pinky1"]
        for t in sample:
            R = fit_palm_frame(flip @ fj[t, w], flip @ fj[t, a], flip @ fj[t, p])
            if R is not None:
                fit_R[side][t] = R

    # --- measurement: avatar hand bone quaternions off the rendered rig ---
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}"
    av_R: dict[str, dict[int, np.ndarray]] = {"left": {}, "right": {}}
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 720, "height": 960})
                errs: list[str] = []
                page.on("pageerror", lambda e: errs.append(str(e)))
                page.goto(f"{url}/bake_seq?pose=/poses/fidelity_frames.json&side=1&fps=30",
                          wait_until="domcontentloaded")
                page.wait_for_function("() => window.__BAKE_READY__ || window.__BAKE_ERROR__",
                                       timeout=90_000)
                err = page.evaluate("() => window.__BAKE_ERROR__")
                if err:
                    raise RuntimeError(f"viewer error: {err}; {errs[:3]}")
                want = set(sample)
                for t in range(T):
                    if page.evaluate("() => window.__bakeSeqStep()") is None:
                        break
                    if t not in want:
                        continue
                    hands = page.evaluate(READ_HANDS)
                    for side in ("left", "right"):
                        q = hands.get(side)
                        if q:
                            av_R[side][t] = quat_to_mat(np.array(q, float))
                    if t % 200 == 0:
                        print(f"  [avatar] {t}/{T}", flush=True)
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()

    # Dump raw per-frame rotations so the (slow) render happens ONCE and any
    # number of metrics can be tried offline against the same measurement.
    dump: dict[str, np.ndarray] = {}
    for side in ("left", "right"):
        common = sorted(set(fit_R[side]) & set(av_R[side]))
        dump[f"{side}_t"] = np.array(common, dtype=np.int32)
        dump[f"{side}_fit"] = np.stack([fit_R[side][t] for t in common]) if common else np.zeros((0, 3, 3))
        dump[f"{side}_av"] = np.stack([av_R[side][t] for t in common]) if common else np.zeros((0, 3, 3))
    np.savez(OUT_DIR / f"palm_raw_{args.tag}.npz", **dump)
    print(f"[dump] {OUT_DIR / f'palm_raw_{args.tag}.npz'}")

    report: dict = {"tag": args.tag, "frames_sampled": len(sample), "sides": {}}
    print()
    print(f"=== PALM FIDELITY [{args.tag}] — avatar vs fit, {len(sample)} frames ===")
    for side in ("left", "right"):
        common = sorted(set(fit_R[side]) & set(av_R[side]))
        if len(common) < 8:
            print(f"{side}: too few usable frames ({len(common)})")
            continue
        # Both frames are rigidly attached to the SAME hand, so with hand world
        # rotation R_t: A_t = R_t A_0, F_t = R_t F_0  =>  A_t = F_t . C, i.e. the
        # constant rig offset multiplies on the RIGHT. Modelling it as C . F is
        # wrong and inflates the residual (it pinned it at a bogus ~90 deg).
        errs_R = [fit_R[side][t].T @ av_R[side][t] for t in common]
        M = geodesic_mean(errs_R)
        offset = angle_deg(M)
        resid = np.array([angle_deg(M.T @ E) for E in errs_R])

        # NOTE: removing the constant offset answers "does the hand TRACK the
        # fit?" — it deliberately HIDES a constant palm rotation, which is
        # exactly the "fist faces sideways" defect. For the absolute,
        # uncalibrated error use scripts/absolute_palm_error.py.
        lo, hi = PUNCH_WINDOW
        win = [t for t in common if lo <= t <= hi]
        fit_ny = np.array([fit_R[side][t][:, 2][1] for t in win])
        av_ny = np.array([(av_R[side][t] @ M.T)[:, 2][1] for t in win])
        # Whole-clip correlation of the palm-down signal.
        f_all = np.array([fit_R[side][t][:, 2][1] for t in common])
        a_all = np.array([(av_R[side][t] @ M.T)[:, 2][1] for t in common])
        corr = float(np.corrcoef(f_all, a_all)[0, 1]) if f_all.std() > 1e-6 else float("nan")

        s = {
            "usable_frames": len(common),
            "rest_offset_deg": round(offset, 1),
            "tracking_resid_deg": {
                "p50": round(float(np.percentile(resid, 50)), 1),
                "p95": round(float(np.percentile(resid, 95)), 1),
                "max": round(float(resid.max()), 1),
            },
            "palm_down_corr": round(corr, 3),
            "punch_window_palm_normal_y": {
                "fit_mean": round(float(fit_ny.mean()), 2) if fit_ny.size else None,
                "avatar_mean": round(float(av_ny.mean()), 2) if av_ny.size else None,
                "fit_min": round(float(fit_ny.min()), 2) if fit_ny.size else None,
                "avatar_min": round(float(av_ny.min()), 2) if av_ny.size else None,
                "mean_abs_diff": round(float(np.abs(fit_ny - av_ny).mean()), 2) if fit_ny.size else None,
            },
        }
        report["sides"][side] = s
        print(f"\n[{side}]  usable {len(common)}/{len(sample)}")
        print(f"  rig offset (constant, not a defect) : {offset:6.1f} deg")
        print(f"  TRACKING RESIDUAL (the defect)      : p50 {s['tracking_resid_deg']['p50']:5.1f}  "
              f"p95 {s['tracking_resid_deg']['p95']:5.1f}  max {s['tracking_resid_deg']['max']:5.1f} deg")
        print(f"  palm-down correlation (1.0 = ideal) : {corr:+.3f}")
        print(f"  punch {lo}-{hi} palm-normal Y (-1 = facing ground):")
        print(f"      fit    mean {s['punch_window_palm_normal_y']['fit_mean']}  "
              f"min {s['punch_window_palm_normal_y']['fit_min']}")
        print(f"      avatar mean {s['punch_window_palm_normal_y']['avatar_mean']}  "
              f"min {s['punch_window_palm_normal_y']['avatar_min']}  "
              f"(mean |diff| {s['punch_window_palm_normal_y']['mean_abs_diff']})")

    out = OUT_DIR / f"palm_fidelity_{args.tag}.json"
    out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"\n[report] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
