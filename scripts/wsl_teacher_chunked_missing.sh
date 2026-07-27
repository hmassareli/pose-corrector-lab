#!/usr/bin/env bash
# Run GVHMR on remaining long person clips in time chunks, then concat joints.
set -uo pipefail

export MAMBA_ROOT_PREFIX="${MAMBA_ROOT_PREFIX:-$HOME/micromamba}"
MICROMAMBA_BIN="${MICROMAMBA_BIN:-$HOME/bin/micromamba}"
eval "$("$MICROMAMBA_BIN" shell hook -s bash)"
micromamba activate gvhmr

LAB="${LAB:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PEOPLE="$LAB/data/input/people"
TEACHER="$LAB/data/teacher"
GVHMR="$LAB/external/GVHMR"
RAW="$TEACHER/_gvhmr_raw"
CHUNK_SEC="${CHUNK_SEC:-45}"
STATIC_CAM=1
export STATIC_CAM
export CHUNK_SEC

cd "$GVHMR"

MISSING=(
  "beginner_friendly_20_boxing_shot_000/person_000"
  "beginner_friendly_20_boxing_shot_000/person_001"
  "beginner_friendly_20_boxing_shot_000/person_002"
  "intense_10_shadow/shot_008/person_000"
  "max_calories_left_half/shot_000/person_000"
)

ok=0
fail=0
for rel in "${MISSING[@]}"; do
  clip_id="${rel//\//__}"
  src="$PEOPLE/$rel/clip.mp4"
  out_dir="$TEACHER/$clip_id"
  if [[ -f "$out_dir/joints3d.npy" ]]; then
    echo "[skip] $clip_id"
    ok=$((ok + 1))
    continue
  fi
  if [[ ! -f "$src" ]]; then
    echo "[FAIL] missing source $src"
    fail=$((fail + 1))
    continue
  fi

  work="$RAW/${clip_id}_chunks"
  mkdir -p "$work/parts" "$out_dir"
  echo ""
  echo "===== CHUNKED $clip_id (${CHUNK_SEC}s) ====="

  # split
  rm -f "$work/parts/"*.mp4
  ffmpeg -y -i "$src" -c:v libx264 -preset ultrafast -crf 20 -an \
    -f segment -segment_time "$CHUNK_SEC" -reset_timestamps 1 \
    "$work/parts/part_%03d.mp4" </dev/null

  mapfile -t PARTS < <(ls -1 "$work/parts"/part_*.mp4 | sort)
  echo "[chunks] ${#PARTS[@]} parts"

  joints_list=()
  part_i=0
  all_ok=1
  for part in "${PARTS[@]}"; do
    part_i=$((part_i + 1))
    pstem=$(basename "$part" .mp4)
    pout="$work/$pstem"
    mkdir -p "$pout"
    echo "--- part $part_i/${#PARTS[@]} $pstem ---"
    rpt=$(find "$pout" -name 'hmr4d_results.pt' 2>/dev/null | head -1)
    if [[ -n "$rpt" ]]; then
      echo "[resume] existing results $rpt"
    else
      set +e
      PYTHONUNBUFFERED=1 python tools/demo/demo.py --video "$part" --output_root "$pout" -s
      rc=$?
      set +e
      rpt=$(find "$pout" -name 'hmr4d_results.pt' 2>/dev/null | head -1)
      if [[ -z "$rpt" ]]; then
        echo "[FAIL] no results for $clip_id $pstem rc=$rc"
        all_ok=0
        break
      fi
    fi

    export RPT="$rpt"
    export PART_NPY="$work/${pstem}_lab.npy"
    python - <<'PY'
import os
from pathlib import Path
import numpy as np
import torch
from hmr4d.model.gvhmr.utils.endecoder import EnDecoder

LAB_FROM_SMPLX = {
    0: "pelvis", 1: "left_hip", 2: "right_hip", 4: "left_knee", 5: "right_knee",
    7: "left_ankle", 8: "right_ankle", 3: "spine", 16: "left_shoulder", 17: "right_shoulder",
    18: "left_elbow", 19: "right_elbow", 20: "left_wrist", 21: "right_wrist", 12: "neck", 15: "head",
}
names = [
    "pelvis", "left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle",
    "spine", "left_shoulder", "right_shoulder", "left_elbow", "right_elbow", "left_wrist", "right_wrist",
    "neck", "head",
]
name_to_i = {n: i for i, n in enumerate(names)}
pred = torch.load(os.environ["RPT"], map_location="cpu")
params = pred["smpl_params_incam"]
batched = {k: v[None].cuda() for k, v in params.items()}
enc = EnDecoder().cuda().eval()
with torch.no_grad():
    joints = enc.fk_v2(**batched)[0].detach().cpu().numpy()
lab = np.zeros((joints.shape[0], 16, 3), dtype=np.float32)
for si, name in LAB_FROM_SMPLX.items():
    lab[:, name_to_i[name]] = joints[:, si]
np.save(os.environ["PART_NPY"], lab)
print("part T", lab.shape[0])
PY
    if [[ $? -ne 0 ]]; then
      all_ok=0
      break
    fi
    joints_list+=("$PART_NPY")
  done

  if [[ $all_ok -ne 1 || ${#joints_list[@]} -eq 0 ]]; then
    fail=$((fail + 1))
    continue
  fi

  export OUT_DIR="$out_dir"
  export SRC="$src"
  export CLIP_ID="$clip_id"
  export PARTS_CSV=$(IFS=,; echo "${joints_list[*]}")
  python - <<'PY'
import json, os, shutil, time
from pathlib import Path
import numpy as np

parts = os.environ["PARTS_CSV"].split(",")
labs = [np.load(p) for p in parts]
lab = np.concatenate(labs, axis=0)
out = Path(os.environ["OUT_DIR"])
out.mkdir(parents=True, exist_ok=True)
np.save(out / "joints3d.npy", lab)
src = Path(os.environ["SRC"])
dst = out / "source.mp4"
if not dst.exists():
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)
meta = {
    "clip_id": os.environ["CLIP_ID"],
    "source_video": str(src),
    "teacher": "GVHMR",
    "static_camera": True,
    "n_frames_teacher": int(lab.shape[0]),
    "chunked": True,
    "chunk_sec": int(os.environ.get("CHUNK_SEC", "45")),
    "n_chunks": len(parts),
    "created_unix": time.time(),
    "qa": {"status": "unchecked"},
    "dry_run": False,
}
(out / "meta.json").write_text(json.dumps(meta, indent=2))
print(f"[ok] {os.environ['CLIP_ID']} T={lab.shape[0]} chunks={len(parts)}")
PY
  if [[ $? -eq 0 ]]; then
    ok=$((ok + 1))
  else
    fail=$((fail + 1))
  fi
done

echo "[chunked teacher] ok=$ok fail=$fail"
[[ $fail -eq 0 ]]
