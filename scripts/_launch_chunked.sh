#!/usr/bin/env bash
set -euo pipefail
LAB="${LAB:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$LAB"
mkdir -p data/teacher
# kill any stale launcher of the same script
pkill -f 'scripts/wsl_teacher_chunked_missing.sh' 2>/dev/null || true
sleep 1
nohup bash scripts/wsl_teacher_chunked_missing.sh >> data/teacher/_chunked_missing.log 2>&1 &
echo "STARTED_PID=$!"
sleep 2
pgrep -af 'wsl_teacher_chunked_missing' || true
