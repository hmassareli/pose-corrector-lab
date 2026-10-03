#!/usr/bin/env python3
"""Where else does the retarget lose the fit? Per-bone SWING vs TWIST error.

The palm work (check_palm_fidelity / absolute_palm_error) answered "is the hand
right?". This answers "which OTHER bones are wrong, and wrong in what way?".

Two independent numbers per bone, because the solver treats them differently:

  SWING (aim) — two numbers, because the raw angle between the avatar's bone
    direction and the fit's is NOT purely error: Mixamo and SMPL-X do not define
    every bone the same way (their clavicle and pelvis rest layouts differ a lot),
    and that shows up as a CONSTANT offset.
      swing_raw  = angle(avatar_dir, fit_dir) in viewer space.
      swing_var  = spread of F_t^T . avatar_dir_t around its mean direction.
                   F_t^T maps into the fit's local frame, where a pure definition
                   difference is CONSTANT — so this isolates the part that is
                   actually tracking error. THIS is the one to judge.
    The solver drives aim from the fit's POSITIONS, so swing_var should be small
    everywhere; a large swing_raw with a small swing_var is a rig convention
    difference, not a defect.

  TWIST (roll about the bone's own axis) — the part of the orientation that
    positions cannot carry. Measured as the residual rotation about the bone axis
    after the aim is accounted for, with the constant rig offset removed
    (A_t = F_t . C, offset on the RIGHT; see analyze_palm_raw.py).
    This is where the retarget is expected to be weak: only some bones get a roll
    signal at all (hands/forearms from the palm, spine/head from shoulder/eye
    across, upper arms from the elbow "witness"). A bone with small swing but
    large twist is oriented along the right line while rotated around it.

Reference rotations come from the fit's FK (build_fk), conjugated into viewer
space: R_viewer = FLIP @ R_nlf @ FLIP.T with FLIP = diag(1,-1,-1) (det +1).

Usage: python scripts/check_body_fidelity.py [--step 4]
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

from check_palm_fidelity import Handler, quat_to_mat  # noqa: E402
from analyze_palm_raw import karcher_mean, log_so3  # noqa: E402
from render_bake_top import DEFAULT_NPZ, OUT_DIR, SMPLX_NPZ, build_fk  # noqa: E402

# avatar rig bone -> (fit joint at the bone, fit joint at its child).
# The direction start->end is what the bone should be pointing along.
BONE_MAP = {
    "hips": ("pelvis", "spine1"),
    "spine": ("spine1", "spine2"),
    "spine1": ("spine2", "spine3"),
    "spine2": ("spine3", "neck"),
    "neck": ("neck", "head"),
    "leftShoulder": ("left_collar", "left_shoulder"),
    "rightShoulder": ("right_collar", "right_shoulder"),
    "leftArm": ("left_shoulder", "left_elbow"),
    "rightArm": ("right_shoulder", "right_elbow"),
    "leftForeArm": ("left_elbow", "left_wrist"),
    "rightForeArm": ("right_elbow", "right_wrist"),
    "leftHand": ("left_wrist", "left_index1"),
    "rightHand": ("right_wrist", "right_index1"),
    "leftUpLeg": ("left_hip", "left_knee"),
    "rightUpLeg": ("right_hip", "right_knee"),
    "leftLeg": ("left_knee", "left_ankle"),
    "rightLeg": ("right_knee", "right_ankle"),
    "leftFoot": ("left_ankle", "left_foot"),
    "rightFoot": ("right_ankle", "right_foot"),
}
# SMPL-X joint whose FK world rotation corresponds to each avatar bone (for twist).
TWIST_JOINT = {
    "hips": "pelvis", "spine": "spine1", "spine1": "spine2", "spine2": "spine3",
    "neck": "neck", "leftShoulder": "left_collar", "rightShoulder": "right_collar",
    "leftArm": "left_shoulder", "rightArm": "right_shoulder",
    "leftForeArm": "left_elbow", "rightForeArm": "right_elbow",
    "leftHand": "left_wrist", "rightHand": "right_wrist",
    "leftUpLeg": "left_hip", "rightUpLeg": "right_hip",
    "leftLeg": "left_knee", "rightLeg": "right_knee",
    "leftFoot": "left_ankle", "rightFoot": "right_ankle",
}

READ_BONES = """() => {
  const THREE = window.__BAKE_THREE__;
  const av = window.__BAKE_AVATAR__;
  const rig = window.__BAKE_RIG__;
  const inv = av.getWorldQuaternion(new THREE.Quaternion()).invert();
  const out = {};
  for (const [name, rest] of rig.bones) {
    const p = rest.bone.getWorldPosition(new THREE.Vector3()).applyQuaternion(inv);
    const c = rest.child
      ? rest.child.getWorldPosition(new THREE.Vector3()).applyQuaternion(inv) : null;
    const q = inv.clone().multiply(rest.bone.getWorldQuaternion(new THREE.Quaternion()));
    out[name] = { p: [p.x, p.y, p.z], c: c ? [c.x, c.y, c.z] : null, q: [q.x, q.y, q.z, q.w] };
  }
  return out;
}"""


def unit(v):
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else np.zeros(3)


def ang_between(a, b):
    return float(np.degrees(np.arccos(np.clip(float(np.dot(unit(a), unit(b))), -1, 1))))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--step", type=int, default=4)
    args = ap.parse_args()

    d = np.load(DEFAULT_NPZ)
    names = [str(n) for n in d["smplx55_names"]]
    idx = {n: i for i, n in enumerate(names)}
    fj = d["fit_joints"].astype(np.float64)
    T = fj.shape[0]
    kt = np.asarray(np.load(SMPLX_NPZ, allow_pickle=True)["kintree_table"])
    print(f"[fit] FK for {T} frames...", flush=True)
    Rw = build_fk(d["pose"].astype(np.float64), kt)

    FLIP = np.diag([1.0, -1.0, -1.0])
    sample = list(range(0, T, args.step))

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}"
    av_frames: dict[int, dict] = {}
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
                want = set(sample)
                for t in range(T):
                    if page.evaluate("() => window.__bakeSeqStep()") is None:
                        break
                    if t in want:
                        av_frames[t] = page.evaluate(READ_BONES)
                    if t % 200 == 0:
                        print(f"  [avatar] {t}/{T}", flush=True)
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()

    rows = []
    for bone, (a_name, b_name) in BONE_MAP.items():
        if a_name not in idx or b_name not in idx:
            continue
        swing, twist = [], []
        E, locals_ = [], []
        for t in sample:
            fr = av_frames.get(t, {}).get(bone)
            if not fr or not fr["c"]:
                continue
            av_dir = np.array(fr["c"], float) - np.array(fr["p"], float)
            fit_dir = FLIP @ (fj[t, idx[b_name]] - fj[t, idx[a_name]])
            if np.linalg.norm(av_dir) < 1e-9 or np.linalg.norm(fit_dir) < 1e-9:
                continue
            swing.append(ang_between(av_dir, fit_dir))
            j = TWIST_JOINT.get(bone)
            if j in idx:
                A = quat_to_mat(np.array(fr["q"], float))
                F = FLIP @ Rw[t, idx[j]] @ FLIP.T
                # E lives in the FIT'S LOCAL frame (F^T maps world -> fit-local),
                # so the bone axis must be taken there too: F^T @ dir_world.
                E.append((F.T @ A, unit(F.T @ unit(fit_dir))))
                # avatar direction expressed in the fit's local frame: constant
                # under a pure bone-definition difference.
                locals_.append(unit(F.T @ unit(av_dir)))
        if len(swing) < 8:
            continue
        if len(E) >= 8:
            C = karcher_mean([e[0] for e in E])
            for Ei, axis_local in E:
                v = log_so3(C.T @ Ei)
                # Twist = component of the residual rotation about the BONE AXIS,
                # both expressed in the fit's local frame.
                twist.append(abs(float(np.degrees(np.dot(v, axis_local)))))
        swing = np.array(swing)
        swing_var = []
        if len(locals_) >= 8:
            L = np.array(locals_)
            mean_dir = unit(L.mean(axis=0))
            swing_var = [float(np.degrees(np.arccos(np.clip(float(np.dot(u, mean_dir)), -1, 1))))
                         for u in L]
        rows.append({
            "bone": bone,
            "n": len(swing),
            "swing_p50": round(float(np.percentile(swing, 50)), 1),
            "swing_p95": round(float(np.percentile(swing, 95)), 1),
            "swing_var_p50": round(float(np.percentile(swing_var, 50)), 1) if swing_var else None,
            "swing_var_p95": round(float(np.percentile(swing_var, 95)), 1) if swing_var else None,
            "twist_p50": round(float(np.percentile(twist, 50)), 1) if twist else None,
            "twist_p95": round(float(np.percentile(twist, 95)), 1) if twist else None,
        })

    rows.sort(key=lambda r: -((r["swing_var_p50"] or 0) + (r["twist_p50"] or 0)))
    print()
    print("=== PER-BONE FIDELITY vs the fit ===")
    print(f"{'bone':<14}{'swing_raw':>10}{'SWING_VAR':>11}{'p95':>7}{'TWIST':>8}{'p95':>7}")
    print(f"{'':<14}{'(defn+err)':>10}{'(real err)':>11}{'':>7}{'(roll)':>8}")
    for r in rows:
        sv = f"{r['swing_var_p50']:>11.1f}{r['swing_var_p95']:>7.1f}" if r["swing_var_p50"] is not None else f"{'-':>18}"
        tw = f"{r['twist_p50']:>8.1f}{r['twist_p95']:>7.1f}" if r["twist_p50"] is not None else f"{'-':>15}"
        print(f"{r['bone']:<14}{r['swing_p50']:>10.1f}{sv}{tw}")
    out = OUT_DIR / "body_fidelity.json"
    out.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print(f"\n[report] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
