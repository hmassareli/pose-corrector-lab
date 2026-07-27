#!/usr/bin/env bash
set -e
export MAMBA_ROOT_PREFIX="${MAMBA_ROOT_PREFIX:-$HOME/micromamba}"
MICROMAMBA_BIN="${MICROMAMBA_BIN:-$HOME/bin/micromamba}"
eval "$("$MICROMAMBA_BIN" shell hook -s bash)"
micromamba activate gvhmr
pip install -q yacs omegaconf transforms3d tqdm dill
# retry import chain
python - <<'PY'
from hmr4d.utils.preproc import Tracker, Extractor, VitPoseExtractor, SimpleVO
print('preproc imports ok')
PY
