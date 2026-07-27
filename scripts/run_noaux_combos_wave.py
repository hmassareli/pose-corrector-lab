#!/usr/bin/env python3
"""Train + eval wave-2 noaux combo ablations (one GPU, sequential)."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parents[1]
EXP_ROOT = LAB_ROOT / "experiments" / "ablation_20260726_noaux_combos"

# (name, config, notes, optional existing run_dir for baseline-only seed)
RUNS: list[tuple[str, str, str]] = [
    ("noaux_dropaccel", "configs/train_noaux_dropaccel.yaml", "w_aux=0 zero_accel"),
    ("noaux_angle", "configs/train_noaux_angle.yaml", "w_aux=0 w_angle=0.2"),
    ("noaux_wrist2", "configs/train_noaux_wrist2.yaml", "w_aux=0 wrist_weight=2.0"),
    ("noaux_gru384", "configs/train_noaux_gru384.yaml", "w_aux=0 hidden=384"),
    ("noaux_long", "configs/train_noaux_long.yaml", "w_aux=0 epochs=120 patience=25"),
]

BASELINE_RUN = LAB_ROOT / "runs" / "20260726_015055_gru_noaux_v1"
DONE_RE = re.compile(r"\[train\] done .* -> (.+)$")


def _run(cmd: list[str], log_path: Path) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    print("+", " ".join(cmd), flush=True)
    print(f"[wave] log -> {log_path}", flush=True)
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    with log_path.open("w", encoding="utf-8") as logf:
        p = subprocess.Popen(
            cmd,
            cwd=str(LAB_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert p.stdout is not None
        for line in p.stdout:
            sys.stdout.write(line)
            logf.write(line)
            logf.flush()
        return p.wait()


def _parse_run_dir(log_path: Path) -> Path:
    text = log_path.read_text(encoding="utf-8", errors="replace")
    matches = DONE_RE.findall(text)
    if not matches:
        raise SystemExit(f"could not parse run_dir from {log_path}")
    p = Path(matches[-1].strip())
    if not p.is_absolute():
        p = LAB_ROOT / p
    return p


def seed_baseline(*, reset: bool) -> None:
    cmd = [
        sys.executable,
        "scripts/run_ablation_eval.py",
        "--exp-root",
        str(EXP_ROOT),
        "--run-dir",
        str(BASELINE_RUN),
        "--name",
        "noaux",
        "--ckpt",
        "both",
        "--notes",
        "wave1 winner w_aux=0 baseline",
        "--skip-export",
    ]
    if reset:
        cmd.append("--reset-leaderboard")
    rc = _run(cmd, LAB_ROOT / "runs" / "_eval_noaux_baseline_wave2.log")
    if rc != 0:
        raise SystemExit(f"baseline eval failed rc={rc}")


def eval_existing(name: str, run_dir: Path, notes: str) -> Path:
    run_dir = run_dir if run_dir.is_absolute() else LAB_ROOT / run_dir
    pointer = EXP_ROOT / f"run_{name}.txt"
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(str(run_dir.resolve()) + "\n", encoding="utf-8")
    eval_log = LAB_ROOT / "runs" / f"_eval_{name}.log"
    rc = _run(
        [
            sys.executable,
            "scripts/run_ablation_eval.py",
            "--exp-root",
            str(EXP_ROOT),
            "--run-dir",
            str(run_dir),
            "--name",
            name,
            "--ckpt",
            "both",
            "--notes",
            notes,
        ],
        eval_log,
    )
    if rc != 0:
        raise SystemExit(f"eval failed for {name} rc={rc}")
    _run(
        [sys.executable, str(Path(__file__).resolve()), "--conclusions-only"],
        LAB_ROOT / "runs" / f"_conclusions_{name}.log",
    )
    return run_dir


def train_and_eval(name: str, config: str, notes: str) -> Path:
    train_log = LAB_ROOT / "runs" / f"_train_{name}.log"
    rc = _run(
        [sys.executable, "scripts/train.py", "--config", config],
        train_log,
    )
    # Windows/CUDA teardown sometimes returns a nonzero STATUS_* after a clean
    # "[train] done" — accept the run if the done line is present.
    done_ok = bool(DONE_RE.search(train_log.read_text(encoding="utf-8", errors="replace")))
    if rc != 0 and not done_ok:
        raise SystemExit(f"train failed for {name} rc={rc}")
    if rc != 0 and done_ok:
        print(f"[wave] warn: train rc={rc} but found [train] done — continuing", flush=True)
    run_dir = _parse_run_dir(train_log)
    (EXP_ROOT / "entries").mkdir(parents=True, exist_ok=True)
    pointer = EXP_ROOT / f"run_{name}.txt"
    pointer.write_text(str(run_dir.resolve()) + "\n", encoding="utf-8")

    eval_log = LAB_ROOT / "runs" / f"_eval_{name}.log"
    rc = _run(
        [
            sys.executable,
            "scripts/run_ablation_eval.py",
            "--exp-root",
            str(EXP_ROOT),
            "--run-dir",
            str(run_dir),
            "--name",
            name,
            "--ckpt",
            "both",
            "--notes",
            notes,
        ],
        eval_log,
    )
    if rc != 0:
        raise SystemExit(f"eval failed for {name} rc={rc}")
    # Reload conclusions writer from disk so in-flight wave picks up script edits.
    _run(
        [sys.executable, str(Path(__file__).resolve()), "--conclusions-only"],
        LAB_ROOT / "runs" / f"_conclusions_{name}.log",
    )
    return run_dir


def write_conclusions() -> None:
    lb = EXP_ROOT / "leaderboard.tsv"
    if not lb.is_file():
        return
    lines = [l for l in lb.read_text(encoding="utf-8").splitlines() if l.strip()]
    if len(lines) < 2:
        return
    header = lines[0].split("\t")
    rows = [dict(zip(header, l.split("\t"))) for l in lines[1:]]

    def f(r: dict, k: str) -> float:
        try:
            return float(r.get(k) or "nan")
        except Exception:
            return float("nan")

    # Prefer best ckpt rows for ranking table; fall back to any.
    bestish = [r for r in rows if r.get("ckpt_used") == "best"] or rows
    bestish = sorted(
        bestish,
        key=lambda r: (-f(r, "hand_prox_impr_vs_mp"), f(r, "hand_prox_mae_C"), f(r, "elbow_mae_C_T")),
    )
    baseline = next((r for r in bestish if r.get("name", "").startswith("noaux_best") or r.get("name") == "noaux_best"), None)
    base_mae = f(baseline, "hand_prox_mae_C") if baseline else float("nan")

    table_lines = [
        "| rank | name | hand_prox_mae_C | val_hard | val_impr | test_hard | test_impr | elbow_mae | vs noaux |",
        "|-----:|------|----------------:|---------:|---------:|----------:|----------:|----------:|----------|",
    ]
    for i, r in enumerate(bestish, 1):
        mae = f(r, "hand_prox_mae_C")
        vs = ""
        if baseline and r is not baseline and mae == mae and base_mae == base_mae:
            delta = mae - base_mae
            vs = f"{delta:+.4f} mae"
            if mae < base_mae:
                vs += " BETTER"
            elif mae > base_mae:
                vs += " worse"
            else:
                vs += " tie"
        table_lines.append(
            f"| {i} | {r.get('name')} | {r.get('hand_prox_mae_C')} | {r.get('val_hard_mm')} | "
            f"{r.get('val_hard_impr_pct')} | {r.get('test_hard_mm')} | {r.get('test_hard_impr_pct')} | "
            f"{r.get('elbow_mae_C_T')} | {vs or 'baseline'} |"
        )

    bullets = []
    if baseline:
        bullets.append(
            f"- **Baseline noaux**: hand_prox_mae_C={baseline.get('hand_prox_mae_C')}, "
            f"val_hard_impr={baseline.get('val_hard_impr_pct')}%, "
            f"test_hard_impr={baseline.get('test_hard_impr_pct')}%, "
            f"elbow={baseline.get('elbow_mae_C_T')}."
        )
    for r in bestish:
        if r is baseline:
            continue
        mae = f(r, "hand_prox_mae_C")
        if baseline and mae == mae and base_mae == base_mae:
            if mae < base_mae:
                bullets.append(f"- **{r.get('name')}** improved hands vs noaux ({mae:.4f} < {base_mae:.4f}).")
            else:
                bullets.append(f"- **{r.get('name')}** did not beat noaux hands ({mae:.4f} vs {base_mae:.4f}).")

    winner = bestish[0] if bestish else None
    viewer = ""
    if winner:
        viewer = (
            f"`{winner.get('run_dir')}/checkpoints/best_hard.pt`\n"
            f"Export: `{winner.get('run_dir')}/corrected_best/`"
        )

    md = f"""# Conclusions — noaux combos (wave-2)

## Metric (primary)
Same as wave-1: `scripts/bench_extended_shoulder_level_hands.py`
→ `hand_prox_mae_C` / `hand_prox_impr_vs_mp`.
Diagnostics: elbow MAE, **val** hard, and **test** hard (`scripts/eval.py --split test`).

## Wave-2 results (best ckpts)
{chr(10).join(table_lines)}

## What worked / didn't
{chr(10).join(bullets) if bullets else "- (see leaderboard)"}

## Viewer ckpt
{viewer or "TBD"}

Folder: `experiments/ablation_20260726_noaux_combos/`
"""
    (EXP_ROOT / "CONCLUSIONS.md").write_text(md, encoding="utf-8")
    status = {
        "n_rows": len(rows),
        "top": [
            {
                "name": r.get("name"),
                "hand_prox_mae_C": r.get("hand_prox_mae_C"),
                "val_hard_impr_pct": r.get("val_hard_impr_pct"),
                "test_hard_impr_pct": r.get("test_hard_impr_pct"),
            }
            for r in bestish[:5]
        ],
        "leaderboard": str(lb),
    }
    (EXP_ROOT / "wave_status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
    print(json.dumps(status, indent=2), flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skip-baseline-seed", action="store_true")
    ap.add_argument("--only", nargs="*", default=None, help="Subset of run names")
    ap.add_argument("--from-name", default=None, help="Resume starting at this run name")
    ap.add_argument(
        "--conclusions-only",
        action="store_true",
        help="Only regenerate CONCLUSIONS.md / wave_status.json from leaderboard",
    )
    ap.add_argument(
        "--eval-only",
        nargs="+",
        default=None,
        help="Eval existing runs as name=run_dir (skip training)",
    )
    args = ap.parse_args()

    EXP_ROOT.mkdir(parents=True, exist_ok=True)
    if args.conclusions_only:
        write_conclusions()
        return

    if not args.skip_baseline_seed:
        seed_baseline(reset=True)

    if args.eval_only:
        notes_by_name = {n: note for n, _c, note in RUNS}
        for item in args.eval_only:
            if "=" not in item:
                raise SystemExit(f"--eval-only expects name=run_dir, got {item!r}")
            name, run_s = item.split("=", 1)
            print(f"\n======== WAVE EVAL {name} ========", flush=True)
            run_dir = eval_existing(name, Path(run_s), notes_by_name.get(name, name))
            print(f"[wave] evaluated {name} -> {run_dir}", flush=True)
        _run(
            [sys.executable, str(Path(__file__).resolve()), "--conclusions-only"],
            LAB_ROOT / "runs" / "_conclusions_final.log",
        )
        print("[wave] eval-only done", flush=True)
        return

    runs = RUNS
    if args.only:
        want = set(args.only)
        runs = [r for r in RUNS if r[0] in want]
    if args.from_name:
        idx = next(i for i, r in enumerate(RUNS) if r[0] == args.from_name)
        runs = [r for r in RUNS[idx:] if (not args.only or r[0] in set(args.only or []))]
        # If --from-name with full list, keep from that index
        if not args.only:
            runs = RUNS[idx:]

    for name, config, notes in runs:
        print(f"\n======== WAVE RUN {name} ========", flush=True)
        run_dir = train_and_eval(name, config, notes)
        print(f"[wave] finished {name} -> {run_dir}", flush=True)

    _run(
        [sys.executable, str(Path(__file__).resolve()), "--conclusions-only"],
        LAB_ROOT / "runs" / "_conclusions_final.log",
    )
    print("[wave] all done", flush=True)


if __name__ == "__main__":
    main()
