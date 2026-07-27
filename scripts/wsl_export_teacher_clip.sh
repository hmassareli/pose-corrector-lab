#!/usr/bin/env bash
set -e
export MAMBA_ROOT_PREFIX="${MAMBA_ROOT_PREFIX:-$HOME/micromamba}"
MICROMAMBA_BIN="${MICROMAMBA_BIN:-$HOME/bin/micromamba}"
eval "$("$MICROMAMBA_BIN" shell hook -s bash)"
micromamba activate gvhmr

LAB="${LAB:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
export LAB
cd "$LAB/external/GVHMR"

python - <<'PY'
"""Re-export teacher joints with correct SMPL-X indices + OpenCV→Three.js axes."""
import json, os, shutil
from pathlib import Path
import numpy as np
import torch
from hmr4d.model.gvhmr.utils.endecoder import EnDecoder

LAB = Path(os.environ["LAB"])
res_path = LAB / "external/GVHMR/outputs/demo/shadow_clip_45s/hmr4d_results.pt"
out = LAB / "data/teacher/shadow_clip_45s"
video_src = out / "source.mp4"
out.mkdir(parents=True, exist_ok=True)

# SMPL-H / SMPL-X body joint order (first 22) — see hmr4d/utils/body_model/utils.py
# 0 pelvis, 1 L_hip, 2 R_hip, 3 spine1, 4 L_knee, 5 R_knee, 6 spine2,
# 7 L_ankle, 8 R_ankle, 9 spine3, 10 L_foot, 11 R_foot, 12 neck,
# 13 L_collar, 14 R_collar, 15 head, 16 L_shoulder, 17 R_shoulder,
# 18 L_elbow, 19 R_elbow, 20 L_wrist, 21 R_wrist
LAB_FROM_SMPLX = {
    0: "pelvis",
    1: "left_hip",
    2: "right_hip",
    4: "left_knee",
    5: "right_knee",
    7: "left_ankle",
    8: "right_ankle",
    3: "spine",
    16: "left_shoulder",
    17: "right_shoulder",
    18: "left_elbow",
    19: "right_elbow",
    20: "left_wrist",
    21: "right_wrist",
    12: "neck",
    15: "head",
}

names = [
    "pelvis", "left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle",
    "spine", "left_shoulder", "right_shoulder", "left_elbow", "right_elbow", "left_wrist", "right_wrist",
    "neck", "head",
]
name_to_i = {n: i for i, n in enumerate(names)}

pred = torch.load(res_path, map_location="cpu")
params = pred["smpl_params_incam"]
batched = {k: v[None].cuda() for k, v in params.items()}
enc = EnDecoder().cuda().eval()
with torch.no_grad():
    joints = enc.fk_v2(**batched)[0].detach().cpu().numpy()  # (T, 22, 3)

# OpenCV camera (Y down, Z forward) → Three.js (Y up, camera looks -Z)
joints_view = joints.copy()
joints_view[..., 1] *= -1.0
joints_view[..., 2] *= -1.0

lab = np.zeros((joints_view.shape[0], 16, 3), dtype=np.float32)
for si, name in LAB_FROM_SMPLX.items():
    lab[:, name_to_i[name]] = joints_view[:, si]

la = name_to_i["left_ankle"]
ra = name_to_i["right_ankle"]

# Center on pelvis X; keep depth relative to first-frame pelvis Z (raw teacher path).
pelvis = lab[:, name_to_i["pelvis"], :].copy()
lab[..., 0] -= pelvis[:, 0:1]
lab[..., 2] -= pelvis[0, 2]

# Plant feet on Y=0 with a constant offset (median lower-ankle height).
foot_y = np.minimum(lab[:, la, 1], lab[:, ra, 1])
ground = float(np.median(foot_y))
lab[..., 1] -= ground

np.save(out / "joints3d.npy", lab)
np.save(out / "joints3d_smpl.npy", joints.astype(np.float32))  # raw camera, unflipped

t = 310
print("ground_offset", ground)
print("pelvis", lab[t, 0])
print("head  ", lab[t, name_to_i["head"]])
print("l_ank ", lab[t, la])
print("r_ank ", lab[t, ra])
assert lab[t, name_to_i["head"], 1] > lab[t, 0, 1], "head should be above pelvis"
assert abs(float(np.median(np.minimum(lab[:, la, 1], lab[:, ra, 1])))) < 1e-3

meta = {
    "clip_id": "shadow_clip_45s",
    "teacher": "GVHMR",
    "static_camera": True,
    "n_frames_teacher": int(lab.shape[0]),
    "video": {"fps": 30.0, "n_frames": int(lab.shape[0])},
    "coord": "threejs_y_up_feet_on_ground",
    "ground_y_offset": ground,
    "root": "pelvis_x_per_frame_z_from_frame0",
    "smplx_map": "SMPLH_JOINT_NAMES first-22",
    "qa": {"status": "unchecked"},
}
(out / "meta.json").write_text(json.dumps(meta, indent=2))

bones = [
    ("pelvis", "left_hip"), ("pelvis", "right_hip"),
    ("left_hip", "left_knee"), ("right_hip", "right_knee"),
    ("left_knee", "left_ankle"), ("right_knee", "right_ankle"),
    ("pelvis", "spine"), ("spine", "neck"), ("neck", "head"),
    ("spine", "left_shoulder"), ("spine", "right_shoulder"),
    ("left_shoulder", "left_elbow"), ("right_shoulder", "right_elbow"),
    ("left_elbow", "left_wrist"), ("right_elbow", "right_wrist"),
]
payload = {
    "title": "GVHMR — shadow_clip_45s",
    "video": "/media/shadow_clip_45s/source.mp4",
    "fps": 30.0,
    "joint_names": names,
    "bones": [{"a": a, "b": b} for a, b in bones],
    "frames": lab.astype(float).tolist(),
}
(out / "viewer_payload.json").write_text(json.dumps(payload))
print("OK wrote", out, "T=", lab.shape[0])
PY
