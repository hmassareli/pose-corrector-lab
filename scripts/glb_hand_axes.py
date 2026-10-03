#!/usr/bin/env python3
"""Derive a rig's true rest palm axes from the SKINNED MESH, not from a pose assumption.

Why
---
mikapo_mixamo_solver.js derives the hand/forearm rest across as `boneDir x up`,
commented "T-pose palms face down". The boxeador GLB is NOT a T-pose (arms hang
down at ~66 deg below horizontal), so that axis is wrong, and every hand solve
inherits the error. Bone positions alone can't fix it: this rig only has an index
finger chain, and that chain is nearly collinear (S2/S1 ~ 0.10), so a
cross-product flexion axis off it is numerically unstable.

The idea was that a hand is a flattened volume, so PCA over the vertices skinned
to it would recover forward / across / palm-normal as the three principal axes.

RESULT: THAT DOES NOT WORK FOR THIS ASSET, and this script is what proved it. The
boxing glove is a rounded mitt, not a flat hand -- measured bbox ~10x12x10 cm with
principal values 6.57 / 6.12 / 4.22. The two in-plane axes are nearly degenerate,
so the "widest axis" is noise; a fix built on it flipped the LEFT hand ~180deg.

The solver therefore derives the palm across from FINGER-CHAIN geometry instead
(deriveRestPalmAcross in mikapo_mixamo_solver.js), computed at runtime -- nothing
consumes this script's output. It is kept as a DIAGNOSTIC: run it to check whether
a new character's hand mesh is anisotropic enough for mesh-based methods, and to
inspect the rig's rest hand geometry.

Usage: python scripts/glb_hand_axes.py [--glb assets/boxeador_mixamo_trellis.glb]
"""
from __future__ import annotations

import argparse
import base64
import json
import struct
from pathlib import Path

import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GLB = LAB_ROOT / "assets" / "boxeador_mixamo_trellis.glb"
OUT_JSON = LAB_ROOT / "experiments" / "rig_hand_axes_diagnostic.json"

COMP_DTYPE = {5120: "i1", 5121: "u1", 5122: "i2", 5123: "u2", 5125: "u4", 5126: "f4"}
NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def load_glb(path: Path):
    data = path.read_bytes()
    assert data[:4] == b"glTF", "not a binary glTF"
    off, js, bin_chunk = 12, None, b""
    while off < len(data):
        ln, ty = struct.unpack_from("<II", data, off)
        off += 8
        chunk = data[off:off + ln]
        off += ln
        if ty == 0x4E4F534A:
            js = json.loads(chunk.decode("utf-8"))
        elif ty == 0x004E4942:
            bin_chunk = chunk
    return js, bin_chunk


def buffer_bytes(g, bin_chunk, i):
    buf = g["buffers"][i]
    uri = buf.get("uri")
    if uri is None:
        return bin_chunk
    if uri.startswith("data:"):
        return base64.b64decode(uri.split(",", 1)[1])
    return (DEFAULT_GLB.parent / uri).read_bytes()


def read_accessor(g, bin_chunk, idx):
    acc = g["accessors"][idx]
    n, ncomp = acc["count"], NCOMP[acc["type"]]
    dt = np.dtype(COMP_DTYPE[acc["componentType"]]).newbyteorder("<")
    if "bufferView" not in acc:
        return np.zeros((n, ncomp), dtype=dt)
    bv = g["bufferViews"][acc["bufferView"]]
    raw = buffer_bytes(g, bin_chunk, bv.get("buffer", 0))
    base = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    packed = dt.itemsize * ncomp
    stride = bv.get("byteStride") or packed
    if stride == packed:
        return np.frombuffer(raw, dtype=dt, count=n * ncomp, offset=base).reshape(n, ncomp)
    # Interleaved: stride over the raw bytes without a Python loop (730k verts).
    view = np.frombuffer(raw, dtype=np.uint8, offset=base, count=(n - 1) * stride + packed)
    strided = np.lib.stride_tricks.as_strided(view, shape=(n, packed), strides=(stride, 1))
    return np.ascontiguousarray(strided).view(dt).reshape(n, ncomp)


def node_matrix(node):
    if "matrix" in node:
        return np.array(node["matrix"], float).reshape(4, 4).T
    M = np.eye(4)
    x, y, z, w = node.get("rotation", [0, 0, 0, 1])
    s = node.get("scale", [1, 1, 1])
    t = node.get("translation", [0, 0, 0])
    R = np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])
    M[:3, :3] = R @ np.diag(s)
    M[:3, 3] = t
    return M


def norm_name(s: str) -> str:
    return "".join(c for c in s.lower() if c.isalnum())


def unit(v):
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v * 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--glb", type=Path, default=DEFAULT_GLB)
    ap.add_argument("--out", type=Path, default=OUT_JSON)
    args = ap.parse_args()

    g, bin_chunk = load_glb(args.glb)
    nodes = g["nodes"]
    parent = {}
    for i, n in enumerate(nodes):
        for c in n.get("children", []):
            parent[c] = i

    cache = {}

    def world(i):
        if i in cache:
            return cache[i]
        M = node_matrix(nodes[i])
        if i in parent:
            M = world(parent[i]) @ M
        cache[i] = M
        return M

    # Root = the node the solver treats as the model root (the scene root three.js
    # hands to buildAvatarRig). Axes are reported in ROOT space so they line up
    # with restDirectionInRoot / restAcrossInRoot. Only the ROTATION matters for
    # a direction, so use the rotation part and drop translation/scale.
    scene_nodes = g["scenes"][g.get("scene", 0)]["nodes"]
    root_world = world(scene_nodes[0])
    root_rot = root_world[:3, :3]
    # Remove scale so the inverse is a pure rotation.
    root_rot = root_rot / np.linalg.norm(root_rot, axis=0, keepdims=True)
    root_rot_inv = root_rot.T

    result = {"source": args.glb.name, "space": "root", "hands": {}}

    for mesh_i, node in enumerate(nodes):
        if "skin" not in node or "mesh" not in node:
            continue
        skin = g["skins"][node["skin"]]
        joints = skin["joints"]
        jnames = [nodes[j].get("name", f"node{j}") for j in joints]

        for prim in g["meshes"][node["mesh"]]["primitives"]:
            attrs = prim["attributes"]
            if "JOINTS_0" not in attrs or "WEIGHTS_0" not in attrs:
                continue
            pos = read_accessor(g, bin_chunk, attrs["POSITION"]).astype(np.float64)
            jid = read_accessor(g, bin_chunk, attrs["JOINTS_0"]).astype(int)
            wgt = read_accessor(g, bin_chunk, attrs["WEIGHTS_0"]).astype(np.float64)
            if wgt.max() > 1.5:  # normalized integer weights
                wgt = wgt / wgt.max()

            # glTF: a skinned mesh IGNORES its node transform. Vertices must be
            # posed by the joints: v' = sum_c w_c * (world(joint_c) @ IBM_c) @ v.
            # At the loaded rest pose this yields exactly what three.js renders,
            # so the axes we derive match what buildAvatarRig sees.
            ibm = read_accessor(g, bin_chunk, skin["inverseBindMatrices"]).astype(np.float64)
            ibm = ibm.reshape(-1, 4, 4).transpose(0, 2, 1)  # glTF stores column-major
            skin_mats = np.stack([world(joints[k]) @ ibm[k] for k in range(len(joints))])

            for side in ("left", "right"):
                # Whole glove: the hand bone plus everything below it (fingers).
                want = [k for k, nm in enumerate(jnames)
                        if norm_name(nm).find(side + "hand") >= 0]
                if not want:
                    continue
                w_total = np.zeros(len(pos))
                for col in range(jid.shape[1]):
                    m = np.isin(jid[:, col], want)
                    w_total[m] += wgt[m, col]
                sel = w_total > 0.5
                if sel.sum() < 50:
                    continue
                # Skin only the selected vertices (the mesh has ~730k).
                v = pos[sel]
                acc_p = np.zeros((int(sel.sum()), 3))
                for col in range(jid.shape[1]):
                    w = wgt[sel, col]
                    if not np.any(w):
                        continue
                    M = skin_mats[jid[sel, col]]
                    acc_p += w[:, None] * (np.einsum("nij,nj->ni", M[:, :3, :3], v) + M[:, :3, 3])
                P = (root_rot_inv @ acc_p.T).T
                c = P.mean(axis=0)
                U, S, Vt = np.linalg.svd(P - c, full_matrices=False)
                fwd, across, normal = unit(Vt[0]), unit(Vt[1]), unit(Vt[2])

                # Right-handed frame: normal = fwd x across (sign fixed later
                # against the solver's existing convention).
                if np.dot(np.cross(fwd, across), normal) < 0:
                    normal = -normal

                hand_node = joints[want[0]]
                # Orient `fwd` from the wrist toward the fingertips.
                wrist = root_rot_inv @ world(hand_node)[:3, 3]
                if np.dot(fwd, c - wrist) < 0:
                    fwd, normal = -fwd, -normal

                result["hands"][side] = {
                    "vertices": int(sel.sum()),
                    "centroid": [round(float(v), 6) for v in c],
                    "wrist": [round(float(v), 6) for v in wrist],
                    "forward": [round(float(v), 6) for v in fwd],
                    "across": [round(float(v), 6) for v in across],
                    "normal": [round(float(v), 6) for v in normal],
                    "singular_values": [round(float(v), 6) for v in S[:3]],
                    "flatness_s3_s2": round(float(S[2] / S[1]), 4) if S[1] > 0 else None,
                    "width_s2_s1": round(float(S[1] / S[0]), 4) if S[0] > 0 else None,
                }

    print(json.dumps(result, indent=1))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(f"\n[out] {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
