#!/usr/bin/env bash
set -e
export MAMBA_ROOT_PREFIX="${MAMBA_ROOT_PREFIX:-$HOME/micromamba}"
MICROMAMBA_BIN="${MICROMAMBA_BIN:-$HOME/bin/micromamba}"
eval "$("$MICROMAMBA_BIN" shell hook -s bash)"
micromamba activate gvhmr
python -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())"

# Prefer conda pytorch3d
if ! python -c "import pytorch3d" 2>/dev/null; then
  echo "Installing pytorch3d via conda..."
  micromamba install -y -c pytorch3d -c conda-forge pytorch3d || true
fi
if ! python -c "import pytorch3d" 2>/dev/null; then
  echo "Fallback: pip pytorch3d from source may be slow; trying fvcore+iopath+pip wheel"
  pip install fvcore iopath
  # try any available wheel matching torch 2.3 cu121 py310
  pip install --no-index --no-cache-dir pytorch3d -f https://dl.fbaipublicfiles.com/pytorch3d/packaging/wheels/py310_cu121_pyt230/download.html || \
  pip install "git+https://github.com/facebookresearch/pytorch3d.git@V0.7.6"
fi
python -c "import pytorch3d; print('pytorch3d OK', pytorch3d.__version__)"
