#!/usr/bin/env bash
set -e
export MAMBA_ROOT_PREFIX="${MAMBA_ROOT_PREFIX:-$HOME/micromamba}"
MICROMAMBA_BIN="${MICROMAMBA_BIN:-$HOME/bin/micromamba}"
eval "$("$MICROMAMBA_BIN" shell hook -s bash)"
micromamba activate gvhmr
if command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg already: $(which ffmpeg)"
  exit 0
fi
micromamba install -y -c conda-forge ffmpeg
which ffmpeg
ffmpeg -version | head -1
