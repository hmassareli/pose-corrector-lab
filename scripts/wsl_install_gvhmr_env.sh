#!/usr/bin/env bash
set -euo pipefail
export MAMBA_ROOT_PREFIX="${MAMBA_ROOT_PREFIX:-$HOME/micromamba}"
MICROMAMBA_BIN="${MICROMAMBA_BIN:-$HOME/bin/micromamba}"
eval "$("$MICROMAMBA_BIN" shell hook -s bash)"
micromamba create -y -n gvhmr python=3.10 pip -c conda-forge
micromamba activate gvhmr
python -V
# PyTorch + CUDA 12.1 (good for WSL + RTX 3060)
micromamba install -y -c pytorch -c nvidia -c conda-forge pytorch==2.3.0 torchvision==0.18.0 pytorch-cuda=12.1
# pytorch3d from conda-forge if available
micromamba install -y -c conda-forge -c pytorch3d pytorch3d || pip install --no-build-isolation "git+https://github.com/facebookresearch/pytorch3d.git@stable"
python -c "import torch; print(torch.__version__, torch.cuda.is_available()); import pytorch3d; print('pytorch3d ok')"
