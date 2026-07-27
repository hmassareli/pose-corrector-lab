#!/usr/bin/env bash
set -e
export MAMBA_ROOT_PREFIX="${MAMBA_ROOT_PREFIX:-$HOME/micromamba}"
MICROMAMBA_BIN="${MICROMAMBA_BIN:-$HOME/bin/micromamba}"
eval "$("$MICROMAMBA_BIN" shell hook -s bash)"
micromamba activate gvhmr

LAB="${LAB:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
GVHMR="$LAB/external/GVHMR"
cd "$GVHMR"

pip install -U pip setuptools wheel
# chumpy is ancient; install from a maintained fork / without build isolation issues
pip install --no-build-isolation "git+https://github.com/mattloper/chumpy.git" || pip install --no-build-isolation chumpy==0.70

pip install lightning==2.3.0 "hydra-core==1.3" hydra-zen hydra_colorlog rich \
  matplotlib termcolor einops "imageio==2.34.1" "av==13.0.0" joblib \
  trimesh smplx "ultralytics==8.2.42" lapx \
  ffmpeg-python scikit-image "timm==0.9.12" tensorboardX \
  opencv-python-headless "numpy==1.26.4" pyyaml einops

# optional / may fail
pip install cython_bbox || true
pip install wis3d || true
pip install pycolmap || true

pip install -e .

python - <<'PY'
import torch
print('torch', torch.__version__, 'cuda', torch.cuda.is_available())
import pytorch3d
print('pytorch3d', pytorch3d.__version__)
import hmr4d
print('hmr4d import ok')
PY
