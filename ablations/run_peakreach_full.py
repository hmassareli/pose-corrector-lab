#!/usr/bin/env python3
"""Train peak-reach ablation, run official benches, then process Henrique videos."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_competition import eval_one, resolve_config, train_one, write_conclusions


def main() -> None:
    exp = LAB_ROOT / "ablations" / "peakreach_20260728"
    name = "lastpos_vel003_peakreach"
    config = resolve_config("phase2_lastpos_vel003_peakreach.yaml", exp)
    run = train_one(name, config, exp, dataset_dir=LAB_ROOT / "data" / "dataset")
    eval_one(
        name,
        run,
        "lastpos_vel003 + teacher-gated one-sided peak arm reach",
        exp,
        reset=not (exp / "leaderboard.tsv").is_file(),
        dataset_dir=LAB_ROOT / "data" / "dataset",
    )
    write_conclusions(exp)
    cmd = [
        sys.executable,
        "scripts/process_personal_videos.py",
        "--ckpt",
        str(run / "checkpoints" / "best_hard.pt"),
        "--video",
        "data/input/Henrique Webcam 1.mp4",
        "--clip-id",
        "henrique_webcam_1",
        "--video",
        "data/input/Henrique webcam 2.mp4",
        "--clip-id",
        "henrique_webcam_2",
        "--out",
        str(exp / "henrique_videos"),
    ]
    subprocess.check_call(cmd, cwd=str(LAB_ROOT))


if __name__ == "__main__":
    main()