#!/usr/bin/env python3
"""Measure retarget angle fidelity: NLF skeleton vs solved Mixamo avatar.

Uses the 13 benchmark photos already inferred in:
  experiments/nlf_dense_surface/report.json   (smpl24 + surface regions)
  experiments/nlf_smplx55_probe/report.json   (eyes/jaw/fingers for head+palm truth)

Bakes each pose via viewer/avatar_bake.html (same solver as live) and reads
solved bone world transforms (window.__BAKE_MEASURE__) to compare:

  Body: trunk flexion, shoulder elevation, foot pitch, head yaw
  Wrist (signed, no screenshots):
    - pronation_deg: palm-across vs palm-down, around the forearm
    - fist_inward_deg: knuckles vs chest-from-wrist, around the forearm
    - knuckles_inward_deg: knuckles vs torso forward
    - Mixamo ForeArm twist vs X55 fingers; SMPL-24 hand×forearm proxy is
      reported only as a negative control (must stay unused)

Writes experiments/avatar_angle_fidelity/report.json and prints a table.
"""

from __future__ import annotations

import json
import math
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB_ROOT / "scripts"))

from render_benchmark_avatar_dev import Handler  # noqa: E402


def V(p):
    """NLF camera space (y down, z fwd) -> viewer space (y up)."""
    return np.array([p[0], -p[1], -p[2]], dtype=np.float64)


def angle_deg(a, b):
    a = np.asarray(a, float); b = np.asarray(b, float)
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na < 1e-9 or nb < 1e-9:
        return float("nan")
    return math.degrees(math.acos(np.clip(a.dot(b) / (na * nb), -1, 1)))


def elev_deg(d):
    """Angle above horizontal plane (positive = up)."""
    d = np.asarray(d, float)
    h = math.hypot(d[0], d[2])
    return math.degrees(math.atan2(d[1], h))


def yaw_deg(d):
    """Heading in XZ plane (deg, atan2(x, z))."""
    return math.degrees(math.atan2(d[0], d[2]))


def wrap180(a):
    return (a + 180.0) % 360.0 - 180.0


def quat_conj(q):
    x, y, z, w = q
    return np.array([-x, -y, -z, w], float)


def quat_mul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return np.array([
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    ], float)


def quat_rotate(q, v):
    qv = np.array([v[0], v[1], v[2], 0.0])
    return quat_mul(quat_mul(q, qv), quat_conj(q))[:3]


# smplx55 probe joint -> aux key expected by the solver (MP_AUX naming)
SMPLX_EXTRA = {
    "jaw": "jaw", "left_eye": "left_eye", "right_eye": "right_eye",
    "left_index1": "left_index", "right_index1": "right_index",
    "left_pinky1": "left_pinky", "right_pinky1": "right_pinky",
    "left_middle1": "left_middle", "right_middle1": "right_middle",
    "left_thumb1": "left_thumb", "right_thumb1": "right_thumb",
}

LAB16_FROM_SMPL24 = [
    "pelvis", "left_hip", "right_hip", "left_knee", "right_knee", "left_ankle",
    "right_ankle", "spine2", "left_shoulder", "right_shoulder", "left_elbow",
    "right_elbow", "left_wrist", "right_wrist", "neck", "head",
]


def write_pose_json(pose_dir, stem, item, sx55):
    aux = dict(item["smpl24"])
    if sx55:
        for src, dst in SMPLX_EXTRA.items():
            if src in sx55:
                aux[dst] = sx55[src]
    data = {
        "name": stem,
        "joints": [item["smpl24"][n] for n in LAB16_FROM_SMPL24],
        "aux_smpl": aux,
        "surface_smpl": item["surface_regions"],
    }
    (pose_dir / f"{stem}.json").write_text(json.dumps(data), encoding="utf-8")


# Standing-neutral collar elevation (world / torso-up). Matches mikapo_mixamo_solver
# SMPL_SHOULDER_NEUTRAL.elev = 0. SMPL-X T-pose cano (~+40°) is NOT a relaxed zero.
SMPL_SHOULDER_NEUTRAL_ELEV_DEG = 0.0


def skeleton_metrics(sm24, sx55):
    pelvis = V(sm24["pelvis"]); neck = V(sm24["neck"])
    up = np.array([0.0, 1.0, 0.0])
    out = {"trunk_flexion_deg": angle_deg(neck - pelvis, up)}
    for side in ("left", "right"):
        live = V(sm24[f"{side}_shoulder"]) - V(sm24[f"{side}_collar"])
        elev = elev_deg(live)
        out[f"{side}_shoulder_elev_deg"] = elev
        # Delta vs standing neutral (0°), same convention the Mixamo solver applies on rest.
        out[f"{side}_shoulder_delta_elev_deg"] = elev - SMPL_SHOULDER_NEUTRAL_ELEV_DEG
        out[f"{side}_foot_pitch_deg"] = elev_deg(V(sm24[f"{side}_foot"]) - V(sm24[f"{side}_ankle"]))
    # Head yaw rel. shoulders (needs eyes from SMPL-X55)
    if sx55 is not None:
        le, re_ = V(sx55["left_eye"]), V(sx55["right_eye"])
        head, neck5 = V(sx55["head"]), V(sx55["neck"])
        across = re_ - le
        hup = head - neck5
        fwd = np.cross(across, hup)
        sh_across = V(sm24["right_shoulder"]) - V(sm24["left_shoulder"])
        sh_fwd = np.cross(sh_across, up)
        out["head_yaw_rel_deg"] = wrap180(yaw_deg(fwd) - yaw_deg(sh_fwd))
    return out


def _unit(v):
    v = np.asarray(v, float)
    n = np.linalg.norm(v)
    if n < 1e-9:
        return None
    return v / n


def signed_angle_around(axis, a, b):
    """Degrees from a to b around axis, after projecting both onto the plane ⊥ axis."""
    axis_u = _unit(axis)
    if axis_u is None:
        return float("nan")
    ap = np.asarray(a, float) - axis_u * np.dot(a, axis_u)
    bp = np.asarray(b, float) - axis_u * np.dot(b, axis_u)
    au, bu = _unit(ap), _unit(bp)
    if au is None or bu is None:
        return float("nan")
    return math.degrees(math.atan2(np.dot(axis_u, np.cross(au, bu)), np.clip(np.dot(au, bu), -1, 1)))


def torso_frame(sm24):
    """Viewer-space torso: across = R−L shoulders, up = world Y, fwd = across × up."""
    up = np.array([0.0, 1.0, 0.0])
    across = V(sm24["right_shoulder"]) - V(sm24["left_shoulder"])
    across_u = _unit(across - up * np.dot(across, up))
    if across_u is None:
        across_u = _unit(across)
    fwd = None if across_u is None else _unit(np.cross(across_u, up))
    mid = 0.5 * (V(sm24["left_shoulder"]) + V(sm24["right_shoulder"]))
    return {"up": up, "across": across_u, "fwd": fwd, "mid": mid}


def x55_palm_axes(sx55, side):
    """Finger-truth palm in viewer space. Left across is negated to match the solver."""
    wrist = V(sx55[f"{side}_wrist"])
    elbow = V(sx55[f"{side}_elbow"])
    idx1 = V(sx55[f"{side}_index1"])
    pky1 = V(sx55[f"{side}_pinky1"])
    forearm = wrist - elbow
    fwd = 0.5 * (idx1 + pky1) - wrist
    across = pky1 - idx1
    if side == "left":
        across = -across
    return {
        "wrist": wrist,
        "elbow": elbow,
        "forearm": forearm,
        "fwd": fwd,
        "across": across,
        "normal": np.cross(fwd, across),
    }


def wrist_signed_metrics(axes, torso):
    """Pronation (palm-down=0) and knuckles-toward-chest, plus flexion."""
    forearm, across, fwd = axes["forearm"], axes["across"], axes["fwd"]
    palm_down_across = np.cross(forearm, torso["up"])
    out = {
        "pronation_deg": signed_angle_around(forearm, palm_down_across, across),
        "wrist_flexion_deg": angle_deg(fwd, forearm),
        "fist_inward_deg": float("nan"),
        "knuckles_inward_deg": float("nan"),
    }
    if torso["fwd"] is not None:
        out["knuckles_inward_deg"] = signed_angle_around(forearm, torso["fwd"], across)
        if torso["mid"] is not None:
            inward = torso["mid"] - axes["wrist"]
            out["fist_inward_deg"] = signed_angle_around(forearm, inward, across)
    return out


def palm_axis_diag(sx55, sm24):
    """X55 truth vs SMPL-24 aim-only (no hand×forearm across — that proxy inverts)."""
    torso = torso_frame(sm24)
    rows = {}
    for side in ("left", "right"):
        axes = x55_palm_axes(sx55, side)
        signed = wrist_signed_metrics(axes, torso)
        elbow = axes["elbow"]
        signed["elbow_angle_deg"] = angle_deg(
            V(sx55[f"{side}_shoulder"]) - elbow, axes["wrist"] - elbow
        )
        for k, v in signed.items():
            rows[f"{side}_{k}"] = v
        hand = V(sm24[f"{side}_hand"])
        fwd24 = hand - axes["wrist"]
        rows[f"{side}_palm_fwd_err_deg"] = angle_deg(fwd24, axes["fwd"])
        # Legacy inverted proxy, kept as a diagnostic that it must stay unused.
        proxy_across = np.cross(fwd24, axes["forearm"])
        if side == "left":
            proxy_across = -proxy_across
        f = _unit(axes["fwd"])
        if f is not None:
            pn = proxy_across - f * np.dot(proxy_across, f)
            pt = axes["across"] - f * np.dot(axes["across"], f)
            rows[f"{side}_palm_across_proxy_err_deg"] = angle_deg(pn, pt)
        else:
            rows[f"{side}_palm_across_proxy_err_deg"] = float("nan")
        rows[f"{side}_has_finger_across"] = True
    return rows


def bone_live_across(measure, name):
    m = measure.get(name)
    if not m or not m.get("restQuat") or not m.get("restAcross"):
        return None
    delta = quat_mul(m["quat"], quat_conj(m["restQuat"]))
    return quat_rotate(delta, np.array(m["restAcross"], float))


def bone_dir(measure, name):
    m = measure.get(name)
    if not m:
        return None
    p = np.array(m["pos"], float)
    c = m.get("child")
    if not c:
        return None
    return np.array(c, float) - p


def avatar_metrics(measure, sx55=None):
    up = np.array([0.0, 1.0, 0.0])
    out = {}

    def pos(name):
        return np.array(measure[name]["pos"], float) if name in measure else None

    def child(name):
        c = measure.get(name, {}).get("child")
        return np.array(c, float) if c else None

    hips, neck = pos("hips"), pos("neck")
    if hips is not None and neck is not None:
        out["trunk_flexion_deg"] = angle_deg(neck - hips, up)
    for side, shName, armName, footName in (
        ("left", "leftShoulder", "leftArm", "leftFoot"),
        ("right", "rightShoulder", "rightArm", "rightFoot"),
    ):
        sh, arm = pos(shName), pos(armName)
        if sh is not None and arm is not None:
            out[f"{side}_shoulder_elev_deg"] = elev_deg(arm - sh)
            rd = measure.get(shName, {}).get("restDir")
            if rd:
                out[f"{side}_shoulder_delta_elev_deg"] = elev_deg(arm - sh) - elev_deg(np.array(rd, float))
        fp, ft = pos(footName), child(footName)
        if fp is not None and ft is not None:
            out[f"{side}_foot_pitch_deg"] = elev_deg(ft - fp)
    if "head" in measure and measure["head"].get("restQuat"):
        # Backward-facing convention to match skeleton_metrics (cross(across, up)):
        # avatar rest forward is +Z, so use -Z for the same convention.
        delta = quat_mul(measure["head"]["quat"], quat_conj(measure["head"]["restQuat"]))
        fwd = quat_rotate(delta, np.array([0.0, 0.0, -1.0]))
        la, ra = pos("leftArm"), pos("rightArm")
        if la is not None and ra is not None:
            sh_fwd = np.cross(ra - la, up)
            out["head_yaw_rel_deg"] = wrap180(yaw_deg(fwd) - yaw_deg(sh_fwd))
    if sx55:
        torso = torso_frame({
            "left_shoulder": sx55["left_shoulder"],
            "right_shoulder": sx55["right_shoulder"],
        })
        for side, handName, foreName in (
            ("left", "leftHand", "leftForeArm"),
            ("right", "rightHand", "rightForeArm"),
        ):
            truth = x55_palm_axes(sx55, side)
            signed_t = wrist_signed_metrics(truth, torso)
            out[f"{side}_elbow_angle_deg"] = angle_deg(
                V(sx55[f"{side}_shoulder"]) - truth["elbow"],
                truth["wrist"] - truth["elbow"],
            )
            for bone_name, tag in ((foreName, "forearm"), (handName, "hand")):
                live_across = bone_live_across(measure, bone_name)
                if live_across is None:
                    continue
                out[f"{side}_palm_across_{tag}_err_deg"] = angle_deg(live_across, truth["across"])
                bone_axis = bone_dir(measure, bone_name)
                if bone_axis is None:
                    bone_axis = truth["forearm"]
                avatar_axes = {
                    **truth,
                    "across": live_across,
                    "forearm": bone_axis,
                }
                signed_a = wrist_signed_metrics(avatar_axes, torso)
                out[f"{side}_pronation_{tag}_deg"] = signed_a["pronation_deg"]
                out[f"{side}_fist_inward_{tag}_deg"] = signed_a["fist_inward_deg"]
                out[f"{side}_knuckles_inward_{tag}_deg"] = signed_a["knuckles_inward_deg"]
                out[f"{side}_pronation_{tag}_err_deg"] = abs(
                    wrap180(signed_a["pronation_deg"] - signed_t["pronation_deg"])
                )
                out[f"{side}_fist_inward_{tag}_err_deg"] = abs(
                    wrap180(signed_a["fist_inward_deg"] - signed_t["fist_inward_deg"])
                )
            # Prefer ForeArm as the pronation carrier; keep legacy hand key.
            if f"{side}_palm_across_hand_err_deg" in out:
                out[f"{side}_palm_across_avatar_err_deg"] = out[f"{side}_palm_across_hand_err_deg"]
            if f"{side}_pronation_forearm_err_deg" in out:
                out[f"{side}_pronation_err_deg"] = out[f"{side}_pronation_forearm_err_deg"]
                out[f"{side}_fist_inward_err_deg"] = out[f"{side}_fist_inward_forearm_err_deg"]
    return out


def main() -> int:
    from playwright.sync_api import sync_playwright

    dense = json.loads((LAB_ROOT / "experiments" / "nlf_dense_surface" / "report.json").read_text())
    probe = json.loads((LAB_ROOT / "experiments" / "nlf_smplx55_probe" / "report.json").read_text())
    probe_by_img = {i["image"]: i for i in probe["items"] if i.get("ok")}
    pose_dir = LAB_ROOT / "src" / "benchmark_images" / "avatar_dev" / "poses"
    Handler.out_dir = pose_dir

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"

    results = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                for item in dense["items"]:
                    if not item.get("ok"):
                        continue
                    stem = Path(item["image"]).stem
                    sx = probe_by_img.get(item["image"], {}).get("smplx55")
                    write_pose_json(pose_dir, stem, item, sx)
                    skel = skeleton_metrics(item["smpl24"], sx)
                    palm = palm_axis_diag(sx, item["smpl24"]) if sx else {}
                    row = {
                        "image": item["image"],
                        "skeleton": skel,
                        "palm_diag": palm,
                        "avatar": {},
                    }
                    for surface in (0, 1):
                        page = browser.new_page(viewport={"width": 720, "height": 960})
                        page.goto(f"{base}/bake?pose=/poses/{stem}.json&surface={surface}",
                                  wait_until="domcontentloaded")
                        page.wait_for_function("() => window.__BAKE_READY__ || window.__BAKE_ERROR__",
                                               timeout=30_000)
                        err = page.evaluate("() => window.__BAKE_ERROR__")
                        if err:
                            raise RuntimeError(f"{stem} surface={surface}: {err}")
                        measure = page.evaluate("() => window.__BAKE_MEASURE__")
                        bake_palm = page.evaluate("() => window.__BAKE_PALM__")
                        page.close()
                        metrics = avatar_metrics(measure, sx)
                        metrics["bake_palm"] = bake_palm
                        row["avatar"][f"surface{surface}"] = metrics
                    results.append(row)
                    print(f"[ok] {stem}")
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()

    keys = ["trunk_flexion_deg", "left_shoulder_delta_elev_deg", "right_shoulder_delta_elev_deg",
            "left_shoulder_elev_deg", "right_shoulder_elev_deg",
            "left_foot_pitch_deg", "right_foot_pitch_deg", "head_yaw_rel_deg"]
    print(f"\n{'metric':<26}{'skeleton':>10}{'avatar(s0)':>12}{'avatar(s1)':>12}{'err(s1)':>10}")
    summary = {}
    for k in keys:
        sk = np.array([r["skeleton"].get(k, np.nan) for r in results], float)
        a0 = np.array([r["avatar"]["surface0"].get(k, np.nan) for r in results], float)
        a1 = np.array([r["avatar"]["surface1"].get(k, np.nan) for r in results], float)
        err = np.abs(a1 - sk)
        summary[k] = {
            "skeleton_mean": float(np.nanmean(sk)),
            "avatar_s0_mean": float(np.nanmean(a0)),
            "avatar_s1_mean": float(np.nanmean(a1)),
            "abs_err_s1_mean": float(np.nanmean(err)),
            "abs_err_s1_max": float(np.nanmax(err)),
        }
        print(f"{k:<26}{np.nanmean(sk):>10.1f}{np.nanmean(a0):>12.1f}{np.nanmean(a1):>12.1f}{np.nanmean(err):>10.1f}")

    print("\n=== Wrist / pronation (X55 truth vs Mixamo ForeArm, surface=1) ===")
    print(f"{'image':<28}{'elbL':>6}{'elbR':>6}{'proL':>7}{'proR':>7}{'inL':>7}{'inR':>7}"
          f"{'dProL':>7}{'dProR':>7}{'dInL':>6}{'dInR':>6}{'acL':>6}{'acR':>6}")
    wrist_rows = []
    for r in results:
        p = r["palm_diag"]
        a = r["avatar"]["surface1"]
        stem = Path(r["image"]).stem.replace("WIN_20260801_", "")
        wrist_rows.append({
            "image": r["image"],
            "left_elbow_angle_deg": p.get("left_elbow_angle_deg"),
            "right_elbow_angle_deg": p.get("right_elbow_angle_deg"),
            "left_pronation_x55_deg": p.get("left_pronation_deg"),
            "right_pronation_x55_deg": p.get("right_pronation_deg"),
            "left_fist_inward_x55_deg": p.get("left_fist_inward_deg"),
            "right_fist_inward_x55_deg": p.get("right_fist_inward_deg"),
            "left_knuckles_inward_x55_deg": p.get("left_knuckles_inward_deg"),
            "right_knuckles_inward_x55_deg": p.get("right_knuckles_inward_deg"),
            "left_pronation_err_deg": a.get("left_pronation_err_deg"),
            "right_pronation_err_deg": a.get("right_pronation_err_deg"),
            "left_fist_inward_err_deg": a.get("left_fist_inward_err_deg"),
            "right_fist_inward_err_deg": a.get("right_fist_inward_err_deg"),
            "left_palm_across_forearm_err_deg": a.get("left_palm_across_forearm_err_deg"),
            "right_palm_across_forearm_err_deg": a.get("right_palm_across_forearm_err_deg"),
            "left_palm_across_hand_err_deg": a.get("left_palm_across_hand_err_deg"),
            "right_palm_across_hand_err_deg": a.get("right_palm_across_hand_err_deg"),
            "left_palm_fwd_err_deg": p.get("left_palm_fwd_err_deg"),
            "right_palm_fwd_err_deg": p.get("right_palm_fwd_err_deg"),
            "left_palm_across_proxy_err_deg": p.get("left_palm_across_proxy_err_deg"),
            "right_palm_across_proxy_err_deg": p.get("right_palm_across_proxy_err_deg"),
        })
        print(
            f"{stem:<28}"
            f"{p.get('left_elbow_angle_deg', float('nan')):6.0f}"
            f"{p.get('right_elbow_angle_deg', float('nan')):6.0f}"
            f"{p.get('left_pronation_deg', float('nan')):7.1f}"
            f"{p.get('right_pronation_deg', float('nan')):7.1f}"
            f"{p.get('left_fist_inward_deg', float('nan')):7.1f}"
            f"{p.get('right_fist_inward_deg', float('nan')):7.1f}"
            f"{a.get('left_pronation_err_deg', float('nan')):7.1f}"
            f"{a.get('right_pronation_err_deg', float('nan')):7.1f}"
            f"{a.get('left_fist_inward_err_deg', float('nan')):6.1f}"
            f"{a.get('right_fist_inward_err_deg', float('nan')):6.1f}"
            f"{a.get('left_palm_across_forearm_err_deg', float('nan')):6.1f}"
            f"{a.get('right_palm_across_forearm_err_deg', float('nan')):6.1f}"
        )

    def meanmax(key, rows=wrist_rows):
        v = np.array([r[key] for r in rows], float)
        return {"mean": float(np.nanmean(v)), "max": float(np.nanmax(v))}

    for k in (
        "left_pronation_x55_deg", "right_pronation_x55_deg",
        "left_fist_inward_x55_deg", "right_fist_inward_x55_deg",
        "left_knuckles_inward_x55_deg", "right_knuckles_inward_x55_deg",
        "left_pronation_err_deg", "right_pronation_err_deg",
        "left_fist_inward_err_deg", "right_fist_inward_err_deg",
        "left_palm_across_forearm_err_deg", "right_palm_across_forearm_err_deg",
        "left_palm_across_hand_err_deg", "right_palm_across_hand_err_deg",
        "left_palm_fwd_err_deg", "right_palm_fwd_err_deg",
        "left_palm_across_proxy_err_deg", "right_palm_across_proxy_err_deg",
    ):
        summary[k] = meanmax(k)

    # Elbow bend vs pronation error (hypothesis: error explodes when bent).
    elbow_corr = {}
    for side in ("left", "right"):
        elb = np.array([r[f"{side}_elbow_angle_deg"] for r in wrist_rows], float)
        err = np.array([r[f"{side}_pronation_err_deg"] for r in wrist_rows], float)
        bent = err[elb < 70]
        ext = err[elb > 120]
        mask = np.isfinite(elb) & np.isfinite(err)
        pearson = float("nan")
        if mask.sum() >= 3:
            pearson = float(np.corrcoef(elb[mask], err[mask])[0, 1])
        elbow_corr[side] = {
            "pearson_elbow_vs_pronation_err": pearson,
            "bent_lt70_err_mean": float(np.nanmean(bent)) if bent.size else float("nan"),
            "extended_gt120_err_mean": float(np.nanmean(ext)) if ext.size else float("nan"),
            "n_bent": int(np.isfinite(bent).sum()) if bent.size else 0,
            "n_extended": int(np.isfinite(ext).sum()) if ext.size else 0,
        }
    summary["elbow_vs_pronation_err"] = elbow_corr
    print("\n=== Elbow vs pronation error ===")
    for side, c in elbow_corr.items():
        print(
            f"  {side}: pearson={c['pearson_elbow_vs_pronation_err']:.2f}  "
            f"bent<70° err={c['bent_lt70_err_mean']:.1f} (n={c['n_bent']})  "
            f"ext>120° err={c['extended_gt120_err_mean']:.1f} (n={c['n_extended']})"
        )

    # Can we infer these angles? Evidence-based verdict from this panel.
    pro_err = np.nanmean([
        summary["left_pronation_err_deg"]["mean"],
        summary["right_pronation_err_deg"]["mean"],
    ])
    proxy_err = np.nanmean([
        summary["left_palm_across_proxy_err_deg"]["mean"],
        summary["right_palm_across_proxy_err_deg"]["mean"],
    ])
    fwd_err = np.nanmean([
        summary["left_palm_fwd_err_deg"]["mean"],
        summary["right_palm_fwd_err_deg"]["mean"],
    ])
    x55_spread = np.nanmax(np.abs(np.concatenate([
        np.array([r["left_pronation_x55_deg"] for r in wrist_rows], float),
        np.array([r["right_pronation_x55_deg"] for r in wrist_rows], float),
    ])))
    verdict = {
        "x55_pronation_has_signal": bool(x55_spread > 20),
        "x55_pronation_range_abs_max_deg": float(x55_spread),
        "smpl24_proxy_across_mean_err_deg": float(proxy_err),
        "smpl24_palm_fwd_mean_err_deg": float(fwd_err),
        "mixamo_forearm_pronation_mean_err_deg": float(pro_err),
        "can_infer_from_16_joints_or_smpl24": False,
        "can_infer_from_nlf_smplx55_fingers": bool(x55_spread > 20),
        "can_retarget_if_fingers_present": bool(pro_err < 35),
        "notes": (
            "Pronation is the missing DOF of shoulder-elbow-wrist. "
            "SMPL-24 hand×forearm across is the inverted proxy (see proxy err ~180°). "
            "NLF live already queries SMPL-X55 knuckles; that is the usable signal. "
            "Mixamo can carry it only as ForeArm twist, not Hand-only roll."
        ),
    }
    summary["inferability"] = verdict
    print("\n=== Inferability ===")
    print(json.dumps(verdict, indent=2))

    out = LAB_ROOT / "experiments" / "avatar_angle_fidelity" / "report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"per_image": results, "wrist_rows": wrist_rows, "summary": summary}, indent=2),
        encoding="utf-8",
    )
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
