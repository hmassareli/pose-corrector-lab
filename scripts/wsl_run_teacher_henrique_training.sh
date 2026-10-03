#!/usr/bin/env bash
# Run the real GVHMR teacher pipeline on every video under data/input/henrique_training.
#
# This mirrors the *working* production path used by scripts/wsl_batch_teacher_people.sh
# (which has already processed 500+ clips successfully), adapted for a flat folder of
# .mp4 files instead of data/input/people/<name>/person_*/clip.mp4.
#
# scripts/run_teacher.py is NOT used here — it calls GVHMR's demo.py with an outdated
# `-f <video>` flag (current demo.py only accepts --video/--output_root/-s) and its
# joint-parsing logic doesn't understand GVHMR's real output format
# (smpl_params_incam inside hmr4d_results.pt, requiring forward-kinematics via
# hmr4d.model.gvhmr.utils.endecoder.EnDecoder). That mismatch makes every clip fail
# instantly with an argparse error.
#
# Why this script exists as a file (not an inline one-liner): invoking the micromamba
# activation as one giant `wsl.exe -d Ubuntu -- bash -lc "..."` one-liner from
# PowerShell is fragile — nested unescaped double quotes make PowerShell's parser hang
# on a `>>` continuation prompt with ZERO output, which looks exactly like a frozen
# GVHMR run but never even reaches WSL/bash. Calling a script file sidesteps that.
#
# Usage (from Windows PowerShell — note the safe quoting: outer double quotes with no
# `$`, spaces in the repo path protected via single quotes instead of nested doubles):
#   wsl.exe -d Ubuntu -- bash -lc "cd /mnt/c/Users/Henrique/studies/'3d augmented games using mocap'/pose_corrector_lab; bash scripts/wsl_run_teacher_henrique_training.sh"
set -uo pipefail

export MAMBA_ROOT_PREFIX="${MAMBA_ROOT_PREFIX:-$HOME/micromamba}"
MICROMAMBA_BIN="${MICROMAMBA_BIN:-$HOME/bin/micromamba}"
eval "$("$MICROMAMBA_BIN" shell hook -s bash)"
micromamba activate gvhmr

LAB="${LAB:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
INPUT="$LAB/data/input/henrique_training"
TEACHER="$LAB/data/teacher"
GVHMR="$LAB/external/GVHMR"
# Heavy raw work (re-encoded video copy, bbx/vitpose/vit_features tensors, rendered
# preview videos) lives on the WSL2 VM's own ext4 disk instead of the Windows C: drive
# (/mnt/c). C: kept crashing the WSL VM when it got low on free space (see
# /memories/repo/wsl_gvhmr_notes.md); the WSL-native disk has 900+GB free and native
# ext4 I/O is also faster than 9p/virtiofs access to /mnt/c. Only the small final
# exports (joints3d.npy, meta.json, a source.mp4 link) land back under data/teacher on
# C: — everything under RAW is disposable per-clip scratch space.
RAW="${GVHMR_SCRATCH:-$HOME/gvhmr_scratch}"
mkdir -p "$TEACHER" "$RAW"
STATIC_CAM="${STATIC_CAM:-1}"
export STATIC_CAM

cd "$GVHMR"

mapfile -t CLIPS < <(find "$INPUT" -maxdepth 1 -type f \( -iname '*.mp4' -o -iname '*.mov' -o -iname '*.mkv' -o -iname '*.webm' \) | sort)
echo "[teacher] found ${#CLIPS[@]} clips under $INPUT static_cam=$STATIC_CAM"
if [[ ${#CLIPS[@]} -eq 0 ]]; then
  echo "No videos under $INPUT"
  exit 1
fi

ok=0
fail=0
skip=0
i=0
for clip in "${CLIPS[@]}"; do
  i=$((i + 1))
  clip_id="$(basename "$clip")"
  clip_id="${clip_id%.*}"
  out_dir="$TEACHER/$clip_id"
  if [[ -f "$out_dir/joints3d.npy" && -f "$out_dir/meta.json" ]]; then
    if grep -q '"dry_run": true' "$out_dir/meta.json" 2>/dev/null; then
      :
    else
      echo "[skip] $i/${#CLIPS[@]} $clip_id"
      skip=$((skip + 1))
      continue
    fi
  fi

  work="$RAW/$clip_id"
  mkdir -p "$work"
  local_vid="$work/${clip_id}.mp4"
  if [[ ! -f "$local_vid" ]]; then
    cp -f "$clip" "$local_vid"
  fi

  echo ""
  echo "===== [$i/${#CLIPS[@]}] $clip_id ====="
  echo "video=$local_vid"

  demo_args=(tools/demo/demo.py --video "$local_vid" --output_root "$work")
  if [[ "$STATIC_CAM" == "1" ]]; then
    demo_args+=(-s)
  fi

  set +e
  python "${demo_args[@]}"
  demo_rc=$?
  results_pt=$(find "$work" -name 'hmr4d_results.pt' 2>/dev/null | head -1)
  if [[ $demo_rc -ne 0 && -z "$results_pt" ]]; then
    echo "[FAIL] demo exit=$demo_rc $clip_id"
    fail=$((fail + 1))
    continue
  fi
  if [[ $demo_rc -ne 0 && -n "$results_pt" ]]; then
    echo "[warn] demo exit=$demo_rc but found results — continuing export"
  fi

  # Export lab joints from hmr4d_results.pt
  export CLIP_PATH="$clip"
  export CLIP_ID="$clip_id"
  export WORK_DIR="$work"
  export OUT_DIR="$out_dir"
  set +e
  python - <<'PY'
import json, os, shutil, time
from pathlib import Path
import numpy as np
import torch
from hmr4d.model.gvhmr.utils.endecoder import EnDecoder

clip = Path(os.environ["CLIP_PATH"])
clip_id = os.environ["CLIP_ID"]
work = Path(os.environ["WORK_DIR"])
out = Path(os.environ["OUT_DIR"])
out.mkdir(parents=True, exist_ok=True)

hits = list(work.rglob("hmr4d_results.pt"))
if not hits:
    raise SystemExit(f"no hmr4d_results.pt under {work}")
res_path = hits[0]

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

pred = torch.load(res_path, map_location="cpu")
params = pred["smpl_params_incam"]
batched = {k: v[None].cuda() for k, v in params.items()}
enc = EnDecoder().cuda().eval()
with torch.no_grad():
    joints = enc.fk_v2(**batched)[0].detach().cpu().numpy()

lab = np.zeros((joints.shape[0], 16, 3), dtype=np.float32)
for si, name in LAB_FROM_SMPLX.items():
    lab[:, name_to_i[name]] = joints[:, si]

np.save(out / "joints3d.npy", lab)
np.save(out / "joints3d_smpl.npy", joints.astype(np.float32))

src = out / "source.mp4"
if not src.exists():
    try:
        os.link(clip, src)
    except OSError:
        shutil.copy2(clip, src)

meta = {
    "clip_id": clip_id,
    "source_video": str(clip),
    "teacher": "GVHMR",
    "static_camera": os.environ.get("STATIC_CAM", "1") == "1",
    "n_frames_teacher": int(lab.shape[0]),
    "created_unix": time.time(),
    "raw_results": str(res_path),
    "qa": {"status": "unchecked"},
    "dry_run": False,
    "note": "camera-space joints; no ground planting — normalize in body frame later",
}
(out / "meta.json").write_text(json.dumps(meta, indent=2))
print(f"[ok] {clip_id} T={lab.shape[0]} -> {out}")
PY
  exp_rc=$?
  set -e
  if [[ $exp_rc -ne 0 ]]; then
    echo "[FAIL] export $clip_id"
    fail=$((fail + 1))
  else
    ok=$((ok + 1))
  fi
done

echo ""
echo "[teacher] done ok=$ok skip=$skip fail=$fail"
[[ $ok -gt 0 || $skip -gt 0 ]]
