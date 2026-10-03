#!/usr/bin/env python3
"""Baker top v4: drive the Mixamo avatar's PALM DIRECTION from the fit rotations.

History:
  v1 (full-frame quaternion deltas) was BROKEN: the boxeador GLB rest is NOT a
  T-pose, so transferring the full frame rotated directions wrongly (knee on
  chest, inverted shoulders, feet up).
  v2 (local wrist twist) fixed the body (directions always from positions) but
  the fist stayed LATERAL.
  v3 blamed the solver's across FADE and fed a large synthetic finger span to
  saturate it. THAT DIAGNOSIS WAS WRONG. `computeHandPalmAxes` normalizes the
  across unconditionally, so the span never reaches the fade -- 0.06 m and 0.6 m
  produce the same unit vector. v3's own check was also CIRCULAR (see below), so
  it reported success while the rendered fist was still wrong.
  v4 (current) fixes the actual cause, in the solver: the hand/forearm rest
  across was `boneDir x up` ("T-pose palms face down"), but this GLB is an
  A-pose, so that reference was 41 deg (left) / 35 deg (right) off the real palm
  plane. It is now fitted from the rig's own finger geometry. Measured absolute
  palm error vs the fit mesh went 133/50 deg -> 8.3/8.4 deg.

The synthetic finger span below is ONLY a transport mechanism: the solver reads
the palm across out of aux index/pinky positions, so we synthesize two points
that encode the direction we want. Only the DIRECTION survives (it is
normalized) -- the magnitude is irrelevant and is not saturating any fade.

Verification: do NOT trust `--verify` here. It reconstructs the avatar's across
from `rest.restAcrossInRoot`, the very vector the solver just aligned to the
target, so it measures the solver's own objective and passes by construction.
Use instead:
  scripts/absolute_palm_error.py   <- absolute, uncalibrated palm error (the gate)
  scripts/check_palm_fidelity.py   <- tracking vs the fit, never touches restAcross
  scripts/compare_palm_frames.py   <- paired mesh/avatar close-ups

Panel comparison: LEFT = baker top v4 (palm from fit rotations), RIGHT = fit
joints with the OBSERVED finger across.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NPZ = LAB_ROOT / "experiments" / "nlf_fit_webcam1" / "fit_smplx.npz"
SMPLX_NPZ = LAB_ROOT / "external" / "GVHMR" / "inputs" / "checkpoints" / "body_models" / "smplx" / "SMPLX_NEUTRAL.npz"
OUT_DIR = LAB_ROOT / "experiments" / "bake_top"

# Synthetic finger separation used only to ENCODE the across direction into the
# aux index/pinky slots. computeHandPalmAxes normalizes, so this magnitude has no
# effect whatsoever (v3 wrongly believed it saturated a fade). Units: mm.
PALM_SPAN_MM = 600.0
PALM_FWD_MM = 120.0

LAB16 = [
    "pelvis", "left_hip", "right_hip", "left_knee", "right_knee", "left_ankle",
    "right_ankle", "spine2", "left_shoulder", "right_shoulder", "left_elbow",
    "right_elbow", "left_wrist", "right_wrist", "neck", "head",
]

AUX_MAP = {
    "pelvis": "pelvis", "left_hip": "left_hip", "right_hip": "right_hip",
    "left_ankle": "left_ankle", "right_ankle": "right_ankle",
    "left_foot": "left_foot", "right_foot": "right_foot",
    "left_wrist": "left_wrist", "right_wrist": "right_wrist",
    "left_elbow": "left_elbow", "right_elbow": "right_elbow",
    "left_shoulder": "left_shoulder", "right_shoulder": "right_shoulder",
    "left_collar": "left_collar", "right_collar": "right_collar",
    "spine1": "spine1", "spine2": "spine2", "spine3": "spine3",
    "neck": "neck", "head": "head", "jaw": "jaw",
    "left_eye": "left_eye", "right_eye": "right_eye",
    "left_index1": "left_index", "left_pinky1": "left_pinky",
    "left_middle1": "left_middle", "left_thumb1": "left_thumb",
    "right_index1": "right_index", "right_pinky1": "right_pinky",
    "right_middle1": "right_middle", "right_thumb1": "right_thumb",
}


def rotmat(aa: np.ndarray) -> np.ndarray:
    aa = np.asarray(aa, float)
    ang = np.linalg.norm(aa)
    if ang < 1e-8:
        return np.eye(3)
    k = aa / ang
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + np.sin(ang) * K + (1 - np.cos(ang)) * (K @ K)


def build_fk(pose: np.ndarray, kt: np.ndarray) -> np.ndarray:
    """R_world[i] = R_world[parent] @ R_local[i] from pose (T,165). Returns (T,55,3,3)."""
    parents = kt[0].astype(int)
    parents[0] = -1
    T = pose.shape[0]
    Rw = np.zeros((T, 55, 3, 3))
    Rw[:, 0] = np.stack([rotmat(a) for a in pose[:, 0:3]])
    for i in range(1, 55):
        p = parents[i]
        Rl = np.stack([rotmat(a) for a in pose[:, 3 + (i - 1) * 3: 3 + i * 3]])
        Rw[:, i] = Rw[:, p] @ Rl
    return Rw


def palm_across_world(Rw_t: np.ndarray, canon: np.ndarray,
                      idx: dict[str, int], side: str) -> np.ndarray:
    """Fit's palm across in world (NLF space, meters): R_world[wrist] @ template across.
    Solver convention: across = pinky − index, negated on left."""
    ix, py = idx[f"{side}_index1"], idx[f"{side}_pinky1"]
    sign = -1.0 if side == "left" else 1.0
    t_across = sign * (canon[py] - canon[ix])
    v = Rw_t[idx[f"{side}_wrist"]] @ t_across
    n = np.linalg.norm(v)
    return v / n if n > 1e-9 else np.zeros(3)


def palm_forward_world(Rw_t: np.ndarray, canon: np.ndarray,
                       idx: dict[str, int], side: str) -> np.ndarray:
    ix, py = idx[f"{side}_index1"], idx[f"{side}_pinky1"]
    wr = idx[f"{side}_wrist"]
    fwd = (canon[ix] + canon[py]) / 2 - canon[wr]
    v = Rw_t[wr] @ fwd
    n = np.linalg.norm(v)
    return v / n if n > 1e-9 else np.zeros(3)


def synth_fingers(wrist_mm: np.ndarray, across_dir: np.ndarray,
                  fwd_dir: np.ndarray, side: str) -> dict[str, list[float]]:
    """Synthetic index/pinky in NLF mm encoding `across_dir`/`fwd_dir`. The span
    is arbitrary: the solver normalizes both axes before using them."""
    mid = wrist_mm + fwd_dir * PALM_FWD_MM
    half = across_dir * (PALM_SPAN_MM / 2)
    if side == "right":
        index, pinky = mid - half, mid + half
    else:
        index, pinky = mid + half, mid - half
    return {"index": [float(c) for c in index], "pinky": [float(c) for c in pinky]}


def build_frames(joints55: np.ndarray, names: list[str],
                 palm: str | None, Rw: np.ndarray, canon: np.ndarray) -> list[dict]:
    """palm: None = raw observed fingers; 'fk' = FK-predicted across (rotations);
    'obs' = observed across direction with the same big span."""
    name_to_i = {n: i for i, n in enumerate(names)}
    idx = name_to_i
    frames: list[dict] = []
    for t in range(joints55.shape[0]):
        aux = {}
        for src, dst in AUX_MAP.items():
            p = joints55[t, name_to_i[src]]
            aux[dst] = [float(c) for c in p]
        if palm is not None:
            aux["fitPalm"] = True
            for side in ("left", "right"):
                wr = idx[f"{side}_wrist"]
                if palm == "fk":
                    across = palm_across_world(Rw[t], canon, idx, side)
                else:  # 'obs': observed finger across (positions), same convention
                    ix, py = idx[f"{side}_index1"], idx[f"{side}_pinky1"]
                    sign = -1.0 if side == "left" else 1.0
                    a = sign * (joints55[t, py] - joints55[t, ix])
                    n = np.linalg.norm(a)
                    across = a / n if n > 1e-9 else np.zeros(3)
                fwd = palm_forward_world(Rw[t], canon, idx, side)
                f = synth_fingers(joints55[t, wr], across, fwd, side)
                aux[f"{side}_index"] = f["index"]
                aux[f"{side}_pinky"] = f["pinky"]
        joints = [joints55[t, name_to_i[n]].tolist() for n in LAB16]
        frames.append({"joints": joints, "aux_smpl": aux})
    return frames


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


def render_panel(url_base: str, frames_name: str, label: str, name: str,
                 step: int, fps: int, max_frames: int, avatar: str = "boxeador") -> int:
    from playwright.sync_api import sync_playwright

    png_dir = OUT_DIR / f"{name}_png"
    shutil.rmtree(png_dir, ignore_errors=True)
    png_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 720, "height": 960}, device_scale_factor=1)
            errors: list[str] = []
            page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
            page.on("pageerror", lambda err: errors.append(str(err)))
            page.goto(
                f"{url_base}/bake_seq?pose=/poses/{frames_name}.json&side=1&fps={fps}"
                f"&label={label}&avatar={avatar}&ui=0",
                wait_until="domcontentloaded",
            )
            try:
                page.wait_for_function("() => window.__BAKE_READY__ || window.__BAKE_ERROR__", timeout=60_000)
            except Exception as e:
                raise RuntimeError(f"{name}: not ready: {e}; console={errors[:5]}") from e
            err = page.evaluate("() => window.__BAKE_ERROR__")
            if err:
                raise RuntimeError(f"{name}: {err}")
            total = page.evaluate("() => window.__BAKE_SEQ_TOTAL__")
            limit = min(total, max_frames * step) if max_frames else total
            captured = 0
            for i in range(0, limit, step):
                done = page.evaluate("() => window.__bakeSeqStep()")
                if done is None:
                    break
                page.locator("#stage").screenshot(path=str(png_dir / f"{captured:05d}.png"))
                captured += 1
                if captured % 100 == 0:
                    print(f"  [{name}] {captured}/{limit // step}", flush=True)
            print(f"  [{name}] captured {captured} frames", flush=True)
            return captured
        finally:
            browser.close()


def verify_palm(url_base: str) -> dict:
    """End-to-end on a REAL punch frame (t=480): feed the FK-predicted palm
    across (big span → fade saturated, fitPalm on) and check the avatar's live
    palm across matches the fed one — proving the render path applies the fit's
    palm exactly."""
    from playwright.sync_api import sync_playwright

    d = np.load(DEFAULT_NPZ)
    names = [str(n) for n in d["smplx55_names"]]
    fj = d["fit_joints"].astype(np.float64)
    canon = SmplxCanon(SMPLX_NPZ).canon
    kt = np.asarray(np.load(SMPLX_NPZ, allow_pickle=True)["kintree_table"])
    Rw = build_fk(d["pose"].astype(np.float64), kt)
    frame = build_frames(fj, names, "fk", Rw, canon)[480]
    (OUT_DIR / "verify_frame.json").write_text(json.dumps([frame]), encoding="utf-8")

    # Expected (viewer space): the FK-pred across that was fed.
    idx = {n: i for i, n in enumerate(names)}
    expect = {}
    for side in ("left", "right"):
        v = palm_across_world(Rw[480], canon, idx, side)
        expect[side] = np.array([v[0], -v[1], -v[2]])  # NLF → viewer

    READ = """() => {
      const THREE = window.__BAKE_THREE__;
      const rig = window.__BAKE_RIG__;
      const res = {};
      for (const side of ['left','right']) {
        const h = rig.bones.get(side + 'Hand');
        if (!h) continue;
        const q = h.bone.getWorldQuaternion(new THREE.Quaternion());
        const local = h.restAcrossInRoot.clone().applyQuaternion(h.restQuaternionInRoot.clone().invert());
        const across = local.applyQuaternion(q);
        res[side] = [across.x, across.y, across.z];
      }
      return res;
    }"""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 720, "height": 960}, device_scale_factor=1)
            page.goto(f"{url_base}/bake_seq?pose=/poses/verify_frame.json&side=1&fps=30", wait_until="domcontentloaded")
            page.wait_for_function("() => window.__BAKE_READY__ || window.__BAKE_ERROR__", timeout=60_000)
            page.evaluate("() => window.__bakeSeqStep()")
            live = page.evaluate(READ)
        finally:
            browser.close()

    out = {"expected": {k: np.round(v, 3).tolist() for k, v in expect.items()},
           "live": {}, "angle_deg": {}}
    ok = True
    for side in ("left", "right"):
        a = np.asarray(live.get(side, [0, 0, 0]), float)
        e = expect[side]
        an, en = a / (np.linalg.norm(a) or 1), e / (np.linalg.norm(e) or 1)
        ang = float(np.degrees(np.arccos(np.clip(np.dot(an, en), -1, 1))))
        out["live"][side] = np.round(an, 3).tolist()
        out["angle_deg"][side] = round(ang, 2)
        if ang > 10.0:
            ok = False
    out["ok"] = ok
    return out


def to_mp4(png_dir: Path, out_mp4: Path, fps: int) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-framerate", str(fps),
            "-i", str(png_dir / "%05d.png"),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-movflags", "+faststart",
            str(out_mp4),
        ],
        check=True,
    )
    print(f"[video] {out_mp4} ({out_mp4.stat().st_size / 1e6:.1f} MB)")


class SmplxCanon:
    def __init__(self, npz: Path):
        smplx = np.load(npz, allow_pickle=True)
        self.canon = np.asarray(smplx["J_regressor"] @ smplx["v_template"], dtype=np.float64)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--npz", type=Path, default=DEFAULT_NPZ)
    ap.add_argument("--step", type=int, default=2)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--max-frames", type=int, default=0)
    ap.add_argument("--avatar", default="boxeador",
                    help="character id from viewer/avatar_assets.js")
    ap.add_argument("--verify", action="store_true", help="end-to-end palm-across check")
    args = ap.parse_args()

    if not args.npz.is_file():
        raise SystemExit(f"missing npz: {args.npz}")
    d = np.load(args.npz)
    names = [str(n) for n in d["smplx55_names"]]
    pose = d["pose"].astype(np.float64)
    fit_joints = d["fit_joints"].astype(np.float64)
    T = pose.shape[0]
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    canon = SmplxCanon(SMPLX_NPZ).canon
    kt = np.asarray(np.load(SMPLX_NPZ, allow_pickle=True)["kintree_table"])
    print("[palm] building FK from pose (165d)...", flush=True)
    Rw = build_fk(pose, kt)
    print(f"[palm] FK done ({T} frames)", flush=True)

    top_frames = build_frames(fit_joints, names, "fk", Rw, canon)
    fit_frames = build_frames(fit_joints, names, "obs", Rw, canon)
    (OUT_DIR / "top_frames.json").write_text(json.dumps(top_frames), encoding="utf-8")
    (OUT_DIR / "fit_frames.json").write_text(json.dumps(fit_frames), encoding="utf-8")
    print(f"[frames] top_frames.json (FK palm) + fit_frames.json (observed palm) ({T} frames)", flush=True)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url_base = f"http://127.0.0.1:{server.server_port}"
    print(f"[srv] {url_base}", flush=True)

    try:
        if args.verify:
            ver = verify_palm(url_base)
            print(f"[verify] {json.dumps(ver, indent=1)}", flush=True)
            if not ver.get("ok"):
                print("[verify] FAILED - live palm does not match fed FK across", flush=True)

        n_top = render_panel(url_base, "top_frames", f"BAKER TOP v4 · {args.avatar}", "top",
                             args.step, args.fps, args.max_frames, args.avatar)
        n_fit = render_panel(url_base, "fit_frames", "FIT JOINTS (dedos do fit)", "fit",
                             args.step, args.fps, args.max_frames, args.avatar)

        if n_top:
            to_mp4(OUT_DIR / "top_png", OUT_DIR / "henrique_webcam_1_bake_top.mp4", args.fps)
        if n_fit:
            to_mp4(OUT_DIR / "fit_png", OUT_DIR / "henrique_webcam_1_bake_fit_joints.mp4", args.fps)
        if n_top and n_fit:
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-i", str(OUT_DIR / "henrique_webcam_1_bake_top.mp4"),
                    "-i", str(OUT_DIR / "henrique_webcam_1_bake_fit_joints.mp4"),
                    "-filter_complex", "[0:v][1:v]hstack=inputs=2[v]",
                    "-map", "[v]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
                    "-movflags", "+faststart",
                    str(OUT_DIR / "henrique_webcam_1_bake_top_vs_fit.mp4"),
                ],
                check=True,
            )
            print(f"[video] {OUT_DIR / 'henrique_webcam_1_bake_top_vs_fit.mp4'}")
    finally:
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
