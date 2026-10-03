#!/usr/bin/env bash
# GVHMR on one video; exports camera-space and gravity-aligned (global) body joints.
# Usage (PowerShell):
#   wsl.exe -d Ubuntu -- bash -lc "cd /mnt/c/Users/Henrique/studies/'3d augmented games using mocap'/pose_corrector_lab; bash scripts/wsl_teacher_one_video.sh data/input/lobby/clip.mp4 experiments/lobby_teacher"
set -euo pipefail
export MAMBA_ROOT_PREFIX="${MAMBA_ROOT_PREFIX:-$HOME/micromamba}"
eval "$("${MICROMAMBA_BIN:-$HOME/bin/micromamba}" shell hook -s bash)"
micromamba activate gvhmr

LAB="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VIDEO="$(realpath "$1")"
OUT="$(realpath -m "$2")"
WORK="${GVHMR_SCRATCH:-$HOME/gvhmr_scratch}/$(basename "${VIDEO%.*}")"
mkdir -p "$WORK" "$OUT"
cp -f "$VIDEO" "$WORK/clip.mp4"
cd "$LAB/external/GVHMR"
python tools/demo/demo.py --video "$WORK/clip.mp4" --output_root "$WORK" -s || true
export WORK OUT
python - <<'PY'
import os
from pathlib import Path
import numpy as np, torch
from hmr4d.model.gvhmr.utils.endecoder import EnDecoder
res = torch.load(next(Path(os.environ["WORK"]).rglob("hmr4d_results.pt")), map_location="cpu")
enc = EnDecoder().cuda().eval()
out = {}
with torch.no_grad():
    for key in ("smpl_params_incam", "smpl_params_global"):
        p = {k: v[None].cuda() for k, v in res[key].items()}
        out[key.split("_")[-1]] = enc.fk_v2(**p)[0].cpu().numpy()
        out[key.split("_")[-1] + "_orient"] = res[key]["global_orient"].cpu().numpy()
np.savez(Path(os.environ["OUT"]) / "gvhmr.npz", **out)
print("[ok]", {k: v.shape for k, v in out.items()})
PY
