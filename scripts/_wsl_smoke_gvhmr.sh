#!/usr/bin/env bash
set -e
export MAMBA_ROOT_PREFIX="${MAMBA_ROOT_PREFIX:-$HOME/micromamba}"
MICROMAMBA_BIN="${MICROMAMBA_BIN:-$HOME/bin/micromamba}"
eval "$("$MICROMAMBA_BIN" shell hook -s bash)"
micromamba activate gvhmr
python -c "import torch; print('cuda', torch.cuda.is_available(), torch.__version__)"
