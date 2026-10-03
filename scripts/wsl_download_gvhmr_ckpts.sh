#!/usr/bin/env bash
set -e
LAB="/mnt/c/Users/Henrique/studies/3d augmented games using mocap/pose_corrector_lab"
GVHMR="$LAB/external/GVHMR"
cd "$GVHMR"

export MAMBA_ROOT_PREFIX="${MAMBA_ROOT_PREFIX:-$HOME/micromamba}"
MICROMAMBA_BIN="${MICROMAMBA_BIN:-$HOME/bin/micromamba}"
eval "$("$MICROMAMBA_BIN" shell hook -s bash)"
micromamba activate gvhmr

pip install -q gdown

mkdir -p inputs/checkpoints
cd inputs/checkpoints

echo "=== downloading GVHMR pretrained checkpoints folder (dpvo/gvhmr/hmr2/vitpose/yolo) ==="
gdown --folder "https://drive.google.com/drive/folders/1eebJ13FUEXrKBawHpJroW0sNSxLjh9xD" -O . || true

echo "=== resulting tree ==="
find . -maxdepth 3
