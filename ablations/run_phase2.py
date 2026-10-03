#!/usr/bin/env python3
"""Run phase-2 ablations with one controlled question per entry.

Groups:
  replication  baseline vs multilag over seeds 42, 1337, 2026
  temporal     sequence supervision and calibrated velocity/direction losses
  architecture multilag representation plus GRU width/layers/context sweeps

The runner is resumable through run_*.txt pointers and leaderboard entries.
Context datasets are generated under data/datasets/ and never overwrite the
frozen T=15 dataset in data/dataset.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parents[1]
ABL_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ABL_ROOT))

from run_competition import (  # noqa: E402
    ensure_y_seq,
    eval_one,
    resolve_config,
    train_one,
    write_conclusions,
)

BASELINE_RUN = LAB_ROOT / "runs" / "20260726_092251_gru_noaux_dropaccel_v1"
MULTILAG_RUN = LAB_ROOT / "runs" / "20260728_002903_abl_gpt_multilag"
DEFAULT_EXP = ABL_ROOT / "phase2_20260728"


@dataclass(frozen=True)
class Entry:
    name: str
    config: str
    group: str
    notes: str
    frozen_run: Path | None = None
    dataset_key: str = "T15"


ENTRIES = [
    Entry("baseline_seed42", "", "replication", "frozen baseline seed=42", BASELINE_RUN),
    Entry(
        "multilag_seed42",
        "",
        "replication",
        "frozen multilag seed=42",
        MULTILAG_RUN,
    ),
    Entry(
        "baseline_seed1337",
        "phase2_baseline_seed1337.yaml",
        "replication",
        "baseline replication seed=1337",
    ),
    Entry(
        "baseline_seed2026",
        "phase2_baseline_seed2026.yaml",
        "replication",
        "baseline replication seed=2026",
    ),
    Entry(
        "multilag_seed1337",
        "phase2_multilag_seed1337.yaml",
        "replication",
        "multilag replication seed=1337",
    ),
    Entry(
        "multilag_seed2026",
        "phase2_multilag_seed2026.yaml",
        "replication",
        "multilag replication seed=2026",
    ),
    Entry("seq_only", "phase2_seq_only.yaml", "temporal", "all-frame position only"),
    Entry(
        "lastpos_vel003",
        "phase2_lastpos_vel003.yaml",
        "temporal",
        "last-frame position + velocity 0.003",
    ),
    Entry(
        "lastpos_vel003_tiera",
        "phase2_lastpos_vel003_tiera.yaml",
        "temporal",
        "lastpos_vel003 + Tier A drop (ipsi/bones/1-conf)",
    ),
    Entry(
        "lastpos_vel005",
        "phase2_lastpos_vel005.yaml",
        "temporal",
        "last-frame position + velocity 0.005",
    ),
    Entry(
        "lastpos_vel010",
        "phase2_lastpos_vel010.yaml",
        "temporal",
        "last-frame position + velocity 0.01",
    ),
    Entry(
        "lastpos_vel005_dir005",
        "phase2_lastpos_vel005_dir005.yaml",
        "temporal",
        "last-frame position + velocity/direction 0.005",
    ),
    Entry(
        "multilag_separate",
        "phase2_multilag_separate.yaml",
        "architecture",
        "separate lag channels F=149",
    ),
    Entry(
        "arch_hidden192",
        "phase2_arch_hidden192.yaml",
        "architecture",
        "GRU hidden=192 layers=2 T=15",
    ),
    Entry(
        "arch_layers1",
        "phase2_arch_layers1.yaml",
        "architecture",
        "GRU hidden=256 layers=1 T=15",
    ),
    Entry(
        "arch_T9",
        "phase2_arch_T9.yaml",
        "architecture",
        "GRU hidden=256 layers=2 T=9",
        dataset_key="T9",
    ),
    Entry(
        "arch_T24",
        "phase2_arch_T24.yaml",
        "architecture",
        "GRU hidden=256 layers=2 T=24",
        dataset_key="T24",
    ),
]


def dataset_dir(key: str) -> Path:
    if key == "T15":
        return LAB_ROOT / "data" / "dataset"
    return LAB_ROOT / "data" / "datasets" / key


def ensure_context_dataset(key: str) -> Path:
    out = dataset_dir(key)
    if key == "T15":
        return out
    expected_t = int(key[1:])
    meta_path = out / "meta.json"
    if meta_path.is_file():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if int(meta.get("T", -1)) == expected_t and all(
            (out / f"{split}.npz").is_file() for split in ("train", "val", "test")
        ):
            print(f"[phase2] reuse dataset {key}: {out}", flush=True)
            return out
    out.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(
        [
            sys.executable,
            "scripts/build_dataset.py",
            "--config",
            str(ABL_ROOT / f"dataset_{key}.yaml"),
            "--out",
            str(out),
        ],
        cwd=str(LAB_ROOT),
    )
    return out


def in_leaderboard(exp: Path, name: str) -> bool:
    path = exp / "leaderboard.tsv"
    return path.is_file() and name in path.read_text(encoding="utf-8")


def status(exp: Path, **values: object) -> None:
    payload = {"ts": time.time(), **values}
    (exp / "phase2_status.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2), flush=True)


def select_entries(groups: list[str] | None, only: list[str] | None) -> list[Entry]:
    selected = ENTRIES
    if groups:
        selected = [entry for entry in selected if entry.group in groups]
    if only:
        requested = set(only)
        selected = [entry for entry in selected if entry.name in requested]
        missing = requested - {entry.name for entry in selected}
        if missing:
            raise SystemExit(f"unknown or filtered entries: {sorted(missing)}")
    return selected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exp-root", type=Path, default=DEFAULT_EXP)
    parser.add_argument(
        "--group",
        action="append",
        choices=("replication", "temporal", "architecture"),
        help="Run one or more experiment groups",
    )
    parser.add_argument("--only", nargs="*", default=None)
    parser.add_argument("--plan", action="store_true", help="Print selected entries and exit")
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()

    exp = args.exp_root if args.exp_root.is_absolute() else LAB_ROOT / args.exp_root
    selected = select_entries(args.group, args.only)
    if args.plan:
        for entry in selected:
            print(f"{entry.group:12} {entry.name:28} dataset={entry.dataset_key} {entry.notes}")
        return

    exp.mkdir(parents=True, exist_ok=True)
    (exp / "logs").mkdir(exist_ok=True)
    if any(entry.group == "temporal" for entry in selected):
        ensure_y_seq()

    reset = not (exp / "leaderboard.tsv").is_file()
    for entry in selected:
        status(exp, phase="entry", name=entry.name, group=entry.group)
        if in_leaderboard(exp, entry.name):
            status(exp, phase="skip_done", name=entry.name)
            reset = False
            continue
        data = ensure_context_dataset(entry.dataset_key)
        pointer = exp / f"run_{entry.name}.txt"
        if entry.frozen_run is not None:
            run = entry.frozen_run
        elif pointer.is_file():
            run = Path(pointer.read_text(encoding="utf-8").strip())
        else:
            config = resolve_config(entry.config, exp)
            run = train_one(entry.name, config, exp, dataset_dir=data)
        eval_one(
            entry.name,
            run,
            entry.notes,
            exp,
            reset=reset,
            dataset_dir=data,
        )
        reset = False
        write_conclusions(exp)
        status(exp, phase="finished", name=entry.name, run_dir=str(run))

    subprocess.check_call(
        [
            sys.executable,
            str(ABL_ROOT / "finalize_report.py"),
            "--exp-root",
            str(exp),
            "--force-punch",
        ],
        cwd=str(LAB_ROOT),
    )
    write_conclusions(exp)
    status(exp, phase="done", results=str(exp / "RESULTS.md"))


if __name__ == "__main__":
    main()