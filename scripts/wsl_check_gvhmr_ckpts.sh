#!/usr/bin/env bash
set -e
LAB="/mnt/c/Users/Henrique/studies/3d augmented games using mocap/pose_corrector_lab"
GVHMR="$LAB/external/GVHMR"
cd "$GVHMR"
echo "=== inputs tree ==="
find inputs -maxdepth 3 2>&1 || echo "(inputs missing or empty)"
echo "=== activate gvhmr env ==="
export MAMBA_ROOT_PREFIX="${MAMBA_ROOT_PREFIX:-$HOME/micromamba}"
MICROMAMBA_BIN="${MICROMAMBA_BIN:-$HOME/bin/micromamba}"
eval "$("$MICROMAMBA_BIN" shell hook -s bash)"
micromamba activate gvhmr
echo "=== gdown check ==="
pip show gdown 2>&1 | head -5 || echo "(gdown not installed)"
echo "=== ultralytics check ==="
pip show ultralytics 2>&1 | head -5 || echo "(ultralytics not installed)"
