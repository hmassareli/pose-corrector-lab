#!/usr/bin/env bash
set -e
export MAMBA_ROOT_PREFIX="${MAMBA_ROOT_PREFIX:-$HOME/micromamba}"
MICROMAMBA_BIN="${MICROMAMBA_BIN:-$HOME/bin/micromamba}"
eval "$("$MICROMAMBA_BIN" shell hook -s bash)"
micromamba activate gvhmr
pip install -q "numpy==1.26.4" requests certifi idna charset-normalizer urllib3 pillow tqdm
python - <<'PY'
from hmr4d.utils.preproc import Tracker, Extractor, VitPoseExtractor, SimpleVO
print('preproc imports ok')
PY
