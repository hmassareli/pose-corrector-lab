#!/usr/bin/env bash
set -e
export MAMBA_ROOT_PREFIX="${MAMBA_ROOT_PREFIX:-$HOME/micromamba}"
MICROMAMBA_BIN="${MICROMAMBA_BIN:-$HOME/bin/micromamba}"
eval "$("$MICROMAMBA_BIN" shell hook -s bash)"
micromamba activate gvhmr

LAB="${LAB:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
GVHMR="$LAB/external/GVHMR"
VIDEO="$LAB/data/input/shadow_clip_45s.mp4"
OUT_ROOT="$GVHMR/outputs/demo"

cd "$GVHMR"
echo "Running GVHMR on $VIDEO"
python tools/demo/demo.py --video "$VIDEO" --output_root "$OUT_ROOT" -s

echo "GVHMR demo finished"
ls -la "$OUT_ROOT" || true
find "$OUT_ROOT" -maxdepth 3 -type f | head -50
