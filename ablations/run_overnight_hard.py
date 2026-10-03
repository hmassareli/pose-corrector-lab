#!/usr/bin/env python3
"""Hardened overnight driver: salvage → resume wave1 → wave2 → morning report.

Designed to survive Cursor/shell interruptions better by doing one model at a
time in this process (not relying on a long-lived parent tee).
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parents[1]
ABL_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ABL_ROOT))

from run_competition import (  # noqa: E402
    ENTRIES,
    ensure_y_seq,
    eval_one,
    resolve_config,
    train_one,
    write_conclusions,
)

EXP = ABL_ROOT / "competition_20260728"
BASELINE = LAB_ROOT / "runs" / "20260726_092251_gru_noaux_dropaccel_v1"
WAVE2 = [
    ("hybrid_multilag_seq_vel_z", "hybrid_multilag_seq_vel_z.yaml", "wave2 hybrid multilag+z"),
    ("hybrid_full_stack", "hybrid_full_stack.yaml", "wave2 full stack"),
]


def status(**kw):
    payload = {"ts": time.time(), **kw}
    (EXP / "overnight_status.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2), flush=True)


def has_pointer(name: str) -> bool:
    return (EXP / f"run_{name}.txt").is_file()


def in_leaderboard(name: str) -> bool:
    lb = EXP / "leaderboard.tsv"
    if not lb.is_file():
        return False
    return name in lb.read_text(encoding="utf-8")


def salvage_multilag() -> None:
    run = LAB_ROOT / "runs" / "20260728_002903_abl_gpt_multilag"
    if not (run / "checkpoints" / "best_hard.pt").is_file():
        return
    if has_pointer("gpt_multilag"):
        return
    import subprocess

    subprocess.check_call(
        [
            sys.executable,
            "scripts/salvage_run.py",
            "--run-dir",
            str(run),
            "--exp-root",
            str(EXP),
            "--name",
            "gpt_multilag",
        ],
        cwd=str(LAB_ROOT),
    )


def run_entry(name: str, override: str, do_train: bool, notes: str, *, reset: bool) -> None:
    status(phase="entry", name=name)
    if name == "baseline_dropaccel":
        run_dir = BASELINE
    elif has_pointer(name):
        run_dir = Path((EXP / f"run_{name}.txt").read_text(encoding="utf-8").strip())
        if do_train and in_leaderboard(name):
            status(phase="skip_done", name=name)
            return
        if do_train and not in_leaderboard(name):
            # trained/salvaged but not evaluated yet
            eval_one(name, run_dir, notes, EXP, reset=reset)
            write_conclusions(EXP)
            return
        if not do_train:
            eval_one(name, run_dir, notes, EXP, reset=reset)
            write_conclusions(EXP)
            return
    if not do_train:
        eval_one(name, BASELINE if name.startswith("baseline") else run_dir, notes, EXP, reset=reset)
        write_conclusions(EXP)
        return
    cfg = resolve_config(override, EXP)
    run_dir = train_one(name, cfg, EXP)
    eval_one(name, run_dir, notes, EXP, reset=reset)
    write_conclusions(EXP)
    status(phase="finished", name=name, run_dir=str(run_dir))


def main() -> None:
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "logs").mkdir(parents=True, exist_ok=True)
    status(phase="start")
    try:
        ensure_y_seq()
    except SystemExit:
        pass
    salvage_multilag()

    lb = EXP / "leaderboard.tsv"
    lb_empty = (not lb.is_file()) or len([l for l in lb.read_text(encoding="utf-8").splitlines() if l.strip()]) < 2
    reset_next = lb_empty

    for name, override, do_train, notes in ENTRIES:
        try:
            # Skip fully done (pointer + leaderboard)
            if has_pointer(name) and in_leaderboard(name) and name != "baseline_dropaccel":
                status(phase="already_done", name=name)
                reset_next = False
                continue
            if name == "baseline_dropaccel" and in_leaderboard("baseline_dropaccel"):
                status(phase="already_done", name=name)
                reset_next = False
                continue
            run_entry(name, override, do_train, notes, reset=reset_next)
            reset_next = False
        except Exception as e:
            status(phase="error", name=name, error=str(e), tb=traceback.format_exc())
            # continue to next? better stop to avoid cascading GPU mess
            raise

    for name, yaml_name, notes in WAVE2:
        try:
            if has_pointer(name) and in_leaderboard(name):
                status(phase="already_done", name=name)
                continue
            if has_pointer(name) and not in_leaderboard(name):
                run_dir = Path((EXP / f"run_{name}.txt").read_text(encoding="utf-8").strip())
                eval_one(name, run_dir, notes, EXP, reset=False)
                write_conclusions(EXP)
                continue
            cfg = resolve_config(yaml_name, EXP)
            run_dir = train_one(name, cfg, EXP)
            eval_one(name, run_dir, notes, EXP, reset=False)
            write_conclusions(EXP)
        except Exception as e:
            status(phase="error", name=name, error=str(e), tb=traceback.format_exc())
            raise

    status(phase="finalize")
    import subprocess

    subprocess.check_call(
        [
            sys.executable,
            str(ABL_ROOT / "finalize_report.py"),
            "--exp-root",
            str(EXP),
            "--force-punch",
        ],
        cwd=str(LAB_ROOT),
    )
    write_conclusions(EXP)
    status(phase="done", results=str(EXP / "RESULTS.md"))
    print(f"\n[overnight_hard] DONE -> {EXP / 'RESULTS.md'}", flush=True)


if __name__ == "__main__":
    main()
