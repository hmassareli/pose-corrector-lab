#!/usr/bin/env python3
"""Does the avatar's palm follow the HAND SIGNAL, or just the rest-pose geometry?

Motivating observation: in the LIVE viewer the punch ends up palm-down and looks
plausible, but it clearly is not tracking the user's actual palm. Hypothesis: the
palm-down look comes from the shortest-arc alignment out of the A-pose rest (which
does not preserve roll), not from the palm across at all — and two mechanisms pin
the real signal near that default in live:
  * acute-flip is ON (live never passes fitPalm), so any across more than 90 deg
    from the rest reference is NEGATED instead of applied;
  * the hand blends at strength 0.85, so 15% of the rest orientation always stays.

Three configurations, same body motion, measured with absolute_palm_error's frame:

  fk      palm across from the fit's FK      + fitPalm  (what the bake renders)
  obs     palm across from observed fingers  + fitPalm  (fit-quality positions)
  live    palm across from observed fingers, NO fitPalm  (what live actually does)
  aimonly no across at all                                (pure rest geometry)

If `aimonly` still trends palm-down through the punch, the palm-down is geometric
and the hand signal is decoration. The gap between `live` and `fk` is how much the
live path throws away.

Usage: python scripts/ablate_palm_signal.py
"""
from __future__ import annotations

import json
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB_ROOT / "scripts"))

from check_palm_fidelity import Handler, quat_to_mat  # noqa: E402
from absolute_palm_error import frame, unit  # noqa: E402
from render_bake_top import (  # noqa: E402
    DEFAULT_NPZ, OUT_DIR, SMPLX_NPZ, SmplxCanon, build_fk, build_frames,
)

PUNCH = (440, 510)
STEP = 4

READ = """() => {
  const THREE = window.__BAKE_THREE__;
  const av = window.__BAKE_AVATAR__;
  const rig = window.__BAKE_RIG__;
  const inv = av.getWorldQuaternion(new THREE.Quaternion()).invert();
  const out = {};
  for (const side of ['left', 'right']) {
    const rest = rig.bones.get(side === 'left' ? 'leftHand' : 'rightHand');
    if (!rest) continue;
    const q = inv.clone().multiply(rest.bone.getWorldQuaternion(new THREE.Quaternion()));
    out[side] = [q.x, q.y, q.z, q.w];
  }
  return out;
}"""


def make_variant(frames: list[dict], mode: str) -> list[dict]:
    """Derive a config from the 'obs' frames without re-running FK."""
    out = []
    for f in frames:
        aux = dict(f["aux_smpl"])
        if mode == "live":
            aux.pop("fitPalm", None)          # acute-flip back ON, strength 0.85
        elif mode == "aimonly":
            aux.pop("fitPalm", None)
            for s in ("left", "right"):        # no across at all -> aim only
                aux.pop(f"{s}_index", None)
                aux.pop(f"{s}_pinky", None)
        out.append({"joints": f["joints"], "aux_smpl": aux})
    return out


def measure(url: str, browser, name: str, T: int) -> dict:
    page = browser.new_page(viewport={"width": 720, "height": 960})
    page.goto(f"{url}/bake_seq?pose=/poses/{name}.json&side=1&fps=30&ui=0",
              wait_until="domcontentloaded")
    page.wait_for_function("() => window.__BAKE_READY__ || window.__BAKE_ERROR__", timeout=120_000)
    err = page.evaluate("() => window.__BAKE_ERROR__")
    if err:
        raise RuntimeError(f"{name}: {err}")
    got: dict[str, dict[int, np.ndarray]] = {"left": {}, "right": {}}
    want = set(range(0, T, STEP))
    for t in range(T):
        if page.evaluate("() => window.__bakeSeqStep()") is None:
            break
        if t not in want:
            continue
        h = page.evaluate(READ)
        for s in ("left", "right"):
            if h.get(s):
                got[s][t] = quat_to_mat(np.array(h[s], float))
    page.close()
    return got


def main() -> int:
    d = np.load(DEFAULT_NPZ)
    names = [str(n) for n in d["smplx55_names"]]
    idx = {n: i for i, n in enumerate(names)}
    fj = d["fit_joints"].astype(np.float64)
    T = fj.shape[0]
    canon = SmplxCanon(SMPLX_NPZ).canon
    kt = np.asarray(np.load(SMPLX_NPZ, allow_pickle=True)["kintree_table"])
    print(f"[fit] FK ({T} frames)...", flush=True)
    Rw = build_fk(d["pose"].astype(np.float64), kt)

    variants = {
        "abl_fk": build_frames(fj, names, "fk", Rw, canon),
        "abl_obs": build_frames(fj, names, "obs", Rw, canon),
    }
    variants["abl_live"] = make_variant(variants["abl_obs"], "live")
    variants["abl_aimonly"] = make_variant(variants["abl_obs"], "aimonly")
    for k, v in variants.items():
        (OUT_DIR / f"{k}.json").write_text(json.dumps(v), encoding="utf-8")

    probe = json.loads((OUT_DIR / "rig_rest_probe.json").read_text(encoding="utf-8"))
    rest = {}
    for side in ("left", "right"):
        pr = probe[side]
        chain = np.array([p for p in pr["chain"] if p], float)
        _, _, Vt = np.linalg.svd(chain - chain.mean(axis=0))
        n_plane = unit(Vt[2])
        ref = unit(np.cross(unit(np.array(pr["restDir"], float)), np.array([0, 1.0, 0])))
        if np.dot(n_plane, ref) < 0:
            n_plane = -n_plane
        A_rest = quat_to_mat(np.array(pr["restQuat"], float))
        rest[side] = {"n": A_rest.T @ n_plane,
                      "d": A_rest.T @ unit(np.array(pr["restDir"], float))}

    flip = np.diag([1.0, -1.0, -1.0])
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}"
    from playwright.sync_api import sync_playwright

    results = {}
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch(headless=True)
            try:
                for name in variants:
                    print(f"[render] {name}", flush=True)
                    results[name] = measure(url, b, name, T)
            finally:
                b.close()
    finally:
        server.shutdown()
        server.server_close()

    print()
    print("=== O AVATAR SEGUE O SINAL DA PALMA, OU A GEOMETRIA DO REST? ===")
    print(f"{'config':<12}{'lado':<7}{'erro abs':>10}{'palma-Y soco':>15}{'(fit)':>9}")
    for name in ["abl_fk", "abl_obs", "abl_live", "abl_aimonly"]:
        for side in ("left", "right"):
            A = results[name][side]
            ts = sorted(A)
            errs, avy, fity = [], [], []
            sign = -1.0 if side == "left" else 1.0
            w, i_, p_ = idx[f"{side}_wrist"], idx[f"{side}_index1"], idx[f"{side}_pinky1"]
            for t in ts:
                wr, ix, pk = flip @ fj[t, w], flip @ fj[t, i_], flip @ fj[t, p_]
                Ff = frame((ix + pk) / 2 - wr, sign * (pk - ix))
                Fa = frame(A[t] @ rest[side]["d"], A[t] @ rest[side]["n"])
                if Ff is None or Fa is None:
                    continue
                errs.append(float(np.degrees(np.arccos(
                    np.clip((np.trace(Fa.T @ Ff) - 1) / 2, -1, 1)))))
                if PUNCH[0] <= t <= PUNCH[1]:
                    avy.append(Fa[1, 2])
                    fity.append(Ff[1, 2])
            print(f"{name:<12}{side:<7}{np.percentile(errs,50):>9.1f}°"
                  f"{np.mean(avy):>14.2f}{np.mean(fity):>9.2f}")
    print()
    print("Leitura: se abl_aimonly (sem across nenhum) já der palma-Y negativa no")
    print("soco, a palma pra baixo vem do rest, nao do sinal da mao.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
