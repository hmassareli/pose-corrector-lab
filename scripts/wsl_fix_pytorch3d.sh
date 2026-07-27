#!/usr/bin/env bash
set -e
export MAMBA_ROOT_PREFIX="${MAMBA_ROOT_PREFIX:-$HOME/micromamba}"
MICROMAMBA_BIN="${MICROMAMBA_BIN:-$HOME/bin/micromamba}"
eval "$("$MICROMAMBA_BIN" shell hook -s bash)"
micromamba activate gvhmr

# Remove conda torch/pytorch3d so pip owns the stack (exact match to FB wheel)
micromamba remove -y pytorch torchvision torchtriton pytorch3d pytorch-cuda || true
pip uninstall -y torch torchvision torchaudio pytorch3d || true

pip install --no-cache-dir \
  torch==2.3.0+cu121 torchvision==0.18.0+cu121 \
  --index-url https://download.pytorch.org/whl/cu121

pip install --no-cache-dir --force-reinstall \
  "https://dl.fbaipublicfiles.com/pytorch3d/packaging/wheels/py310_cu121_pyt230/pytorch3d-0.7.6-cp310-cp310-linux_x86_64.whl"

pip install -q "numpy==1.26.4" yacs

python - <<'PY'
import torch, pytorch3d
from pytorch3d import _C
print('torch', torch.__version__, 'cuda', torch.cuda.is_available())
print('pytorch3d', pytorch3d.__version__)
from hmr4d.utils.preproc import Tracker, Extractor, VitPoseExtractor, SimpleVO
print('preproc imports ok')
PY
