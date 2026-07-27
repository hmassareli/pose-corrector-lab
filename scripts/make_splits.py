#!/usr/bin/env python3
"""Build data/splits/manifest.json — split by source video / burn holdout shots.

Policy (v1):
  test  = full held-out videos: intense_10_shadow, max_calories_left_half
  val   = last ~15% of burn_500 shots (by shot id)
  train = remaining burn shots + beginner / shadow_clip / shot_008 / win_*
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parents[1]

TEST_PREFIXES = (
    "intense_10_shadow__",
    "max_calories_left_half__",
)

SHOT_RE = re.compile(r"^burn_500_shots__(shot_\d+)__")


def source_group(clip_id: str) -> str:
    if clip_id.startswith("burn_500_shots__"):
        return "burn_500_shots"
    if clip_id.startswith("beginner_friendly"):
        return "beginner_friendly_20_boxing"
    if clip_id.startswith("intense_10_shadow"):
        return "intense_10_shadow"
    if clip_id.startswith("max_calories"):
        return "max_calories_left_half"
    if clip_id.startswith("shadow_clip"):
        return "shadow_clip_45s"
    if clip_id.startswith("shot_008"):
        return "shot_008"
    if clip_id.startswith("win_"):
        # User / phone recordings (e.g. win_20260727_...); keep as train extras.
        return clip_id.split("__shot_")[0] if "__shot_" in clip_id else "win"
    if "__shot_" in clip_id:
        return clip_id.split("__shot_")[0]
    return clip_id.split("__person_")[0]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--paired", type=Path, default=LAB_ROOT / "data" / "paired")
    ap.add_argument("--out", type=Path, default=LAB_ROOT / "data" / "splits" / "manifest.json")
    ap.add_argument("--val-shot-frac", type=float, default=0.15)
    args = ap.parse_args()

    clip_ids = sorted(
        p.name for p in args.paired.iterdir() if (p / "residual_30.npy").is_file()
    )
    burn_by_shot: dict[str, list[str]] = defaultdict(list)
    other: list[str] = []
    test: list[str] = []

    for cid in clip_ids:
        if cid.startswith(TEST_PREFIXES):
            test.append(cid)
            continue
        m = SHOT_RE.match(cid)
        if m:
            burn_by_shot[m.group(1)].append(cid)
        else:
            other.append(cid)

    burn_shots = sorted(burn_by_shot.keys())
    n_val = max(1, int(round(len(burn_shots) * args.val_shot_frac)))
    val_shots = set(burn_shots[-n_val:])
    val: list[str] = []
    train: list[str] = []
    for shot, clips in burn_by_shot.items():
        (val if shot in val_shots else train).extend(sorted(clips))
    train.extend(sorted(other))

    groups: dict[str, dict] = {}
    for split, clips in (("train", train), ("val", val), ("test", test)):
        by_src: dict[str, list[str]] = defaultdict(list)
        for c in clips:
            by_src[source_group(c)].append(c)
        for src, src_clips in sorted(by_src.items()):
            groups[f"{split}::{src}"] = {
                "split": split,
                "source": src,
                "clips": sorted(src_clips),
            }

    manifest = {
        "fps_canonical": 30,
        "window_T": 15,
        "policy": {
            "test": "full videos intense_10_shadow + max_calories_left_half",
            "val": f"burn_500 last {n_val}/{len(burn_shots)} shots ({sorted(val_shots)})",
            "train": "remaining burn shots + beginner/shadow_clip/shot_008/win_*",
            "identity_note": "IDs are YOLO tracks per shot, not global persons; split is by video/shot group.",
        },
        "counts": {
            "train_clips": len(train),
            "val_clips": len(val),
            "test_clips": len(test),
            "total_clips": len(clip_ids),
            "val_burn_shots": sorted(val_shots),
        },
        "splits": {
            "train": sorted(train),
            "val": sorted(val),
            "test": sorted(test),
        },
        "groups": groups,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"wrote {args.out}")
    print(
        f"train={len(train)} val={len(val)} test={len(test)} "
        f"val_shots={sorted(val_shots)}"
    )


if __name__ == "__main__":
    main()
