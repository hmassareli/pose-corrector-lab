#!/usr/bin/env bash
set -euo pipefail
LAB="${LAB:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
LOG="$LAB/data/teacher/_chunked_missing.log"
cd "$LAB"
exec bash "$LAB/scripts/wsl_teacher_chunked_missing.sh" >"$LOG" 2>&1
