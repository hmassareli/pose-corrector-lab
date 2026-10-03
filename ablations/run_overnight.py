#!/usr/bin/env python3
"""Overnight babysitter: wait for wave-1, then wave-2 hybrids + morning report.

Safe to re-run: skips finished entries via run_*.txt pointers when --resume.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parents[1]
ABL_ROOT = Path(__file__).resolve().parent

WAVE1 = [
    "baseline_dropaccel",
    "gpt_multilag",
    "gpt_seq_vel",
    "gpt_seq_vel_dir",
    "me_seq_vel_z",
    "me_seq_vel_z_bone",
]
WAVE2 = [
    "hybrid_multilag_seq_vel_z",
    "hybrid_full_stack",
]


def _run(cmd: list[str]) -> int:
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=str(LAB_ROOT)).returncode


def pointers_done(exp_root: Path, names: list[str]) -> list[str]:
    done = []
    for n in names:
        p = exp_root / f"run_{n}.txt"
        # baseline has no train pointer by design — check leaderboard entry
        if n == "baseline_dropaccel":
            lb = exp_root / "leaderboard.tsv"
            if lb.is_file() and "baseline_dropaccel" in lb.read_text(encoding="utf-8"):
                done.append(n)
            continue
        if p.is_file():
            done.append(n)
    return done


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--exp-root", type=Path, default=ABL_ROOT / "competition_20260728")
    ap.add_argument(
        "--poll-seconds",
        type=int,
        default=120,
        help="If wave1 runner still alive externally, just finalize+wave2 after pointers exist",
    )
    ap.add_argument("--skip-wave1-wait", action="store_true")
    ap.add_argument("--skip-wave2", action="store_true")
    args = ap.parse_args()
    exp_root = args.exp_root if args.exp_root.is_absolute() else LAB_ROOT / args.exp_root
    exp_root.mkdir(parents=True, exist_ok=True)

    status_path = exp_root / "overnight_status.json"

    def status(**kw):
        payload = {"ts": time.time(), **kw}
        status_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(json.dumps(payload, indent=2), flush=True)

    if not args.skip_wave1_wait:
        status(phase="wait_wave1", done=pointers_done(exp_root, WAVE1))
        # Wait until all wave1 trainables have run_*.txt (baseline counted via lb)
        need = [n for n in WAVE1 if n != "baseline_dropaccel"]
        while True:
            done = pointers_done(exp_root, WAVE1)
            missing = [n for n in need if n not in done]
            status(phase="wait_wave1", done=done, missing=missing)
            if not missing:
                break
            time.sleep(max(30, args.poll_seconds))

    # Morning-ish finalize for wave1
    status(phase="finalize_wave1")
    _run(
        [
            sys.executable,
            str(ABL_ROOT / "finalize_report.py"),
            "--exp-root",
            str(exp_root),
            "--force-punch",
        ]
    )

    if not args.skip_wave2:
        # Append wave2 entries into competition by calling run_competition with only=
        # Extend ENTRIES dynamically via a small inline runner
        status(phase="wave2")
        for name, yaml_name in (
            ("hybrid_multilag_seq_vel_z", "hybrid_multilag_seq_vel_z.yaml"),
            ("hybrid_full_stack", "hybrid_full_stack.yaml"),
        ):
            pointer = exp_root / f"run_{name}.txt"
            if pointer.is_file():
                status(phase="wave2_skip", name=name)
                continue
            # Use run_competition machinery: resolve+train+eval via a one-off python
            code = f"""
import sys
from pathlib import Path
sys.path.insert(0, r'{ABL_ROOT.as_posix()}')
from run_competition import resolve_config, train_one, eval_one, write_conclusions
exp = Path(r'{exp_root.as_posix()}')
cfg = resolve_config('{yaml_name}', exp)
run = train_one('{name}', cfg, exp)
eval_one('{name}', run, 'wave2 hybrid', exp, reset=False)
write_conclusions(exp)
print('WAVE2_DONE', '{name}', run)
"""
            rc = _run([sys.executable, "-c", code])
            if rc != 0:
                status(phase="wave2_failed", name=name, rc=rc)
                break

    status(phase="finalize_final")
    _run(
        [
            sys.executable,
            str(ABL_ROOT / "finalize_report.py"),
            "--exp-root",
            str(exp_root),
            "--force-punch",
        ]
    )
    # Refresh CONCLUSIONS too
    _run(
        [
            sys.executable,
            str(ABL_ROOT / "run_competition.py"),
            "--exp-root",
            str(exp_root),
            "--conclusions-only",
        ]
    )
    status(phase="done", results=str(exp_root / "RESULTS.md"))
    print(f"\n[overnight] DONE — open {exp_root / 'RESULTS.md'}", flush=True)


if __name__ == "__main__":
    main()
