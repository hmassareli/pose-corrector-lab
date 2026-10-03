#!/usr/bin/env bash
LAB="/mnt/c/Users/Henrique/studies/3d augmented games using mocap/pose_corrector_lab"
cd "$LAB"
for d in beginner_friendly_20_boxing_shot_000__person_000 beginner_friendly_20_boxing_shot_000__person_001 beginner_friendly_20_boxing_shot_000__person_002 intense_10_shadow__shot_008__person_000 max_calories_left_half__shot_000__person_000; do
  if [ -f "data/teacher/$d/joints3d.npy" ]; then
    echo "$d: has_output"
  else
    echo "$d: MISSING_OUTPUT"
  fi
done
