#!/usr/bin/env python3
"""Salvage an interrupted train run that has best_hard.pt but no summary/done line."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parents[1]


def salvage(run_dir: Path) -> dict:
    run_dir = run_dir if run_dir.is_absolute() else LAB_ROOT / run_dir
    best = run_dir / "checkpoints" / "best_hard.pt"
    last = run_dir / "checkpoints" / "last.pt"
    if not best.is_file():
        raise SystemExit(f"missing {best}")
    metrics = run_dir / "metrics.jsonl"
    best_epoch = -1
    best_hard = float("inf")
    elapsed = None
    if metrics.is_file():
        for line in metrics.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if not r.get("easy_ok", True):
                continue
            h = r.get("val/mpjpe_hard_mm")
            if h is None or (isinstance(h, float) and math.isnan(h)):
                continue
            if float(h) < best_hard:
                best_hard = float(h)
                best_epoch = int(r.get("epoch", -1))
            elapsed = r.get("elapsed_s", elapsed)
    summary = {
        "best_epoch": best_epoch,
        "best_hard_mm": None if best_hard == float("inf") else best_hard,
        "run_dir": str(run_dir.resolve()),
        "elapsed_s": elapsed,
        "salvaged": True,
        "had_last": last.is_file(),
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--exp-root", type=Path, default=None)
    ap.add_argument("--name", type=str, default="")
    args = ap.parse_args()
    summary = salvage(args.run_dir)
    if args.exp_root and args.name:
        exp = args.exp_root if args.exp_root.is_absolute() else LAB_ROOT / args.exp_root
        exp.mkdir(parents=True, exist_ok=True)
        (exp / f"run_{args.name}.txt").write_text(
            str(Path(summary["run_dir"]).resolve()) + "\n", encoding="utf-8"
        )
        print(f"wrote pointer run_{args.name}.txt", flush=True)


if __name__ == "__main__":
    main()
