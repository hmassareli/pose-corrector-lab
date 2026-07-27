#!/usr/bin/env python3
"""Batch YOLO person-split for all Burn 500 user shots."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parents[1]
SHOTS_DIR = next(
    (LAB_ROOT / "data" / "input" / "shots").glob("Burn 500*"),
    None,
)
OUT_ROOT = LAB_ROOT / "data" / "input" / "people" / "burn_500_shots"
SCRIPT = LAB_ROOT / "scripts" / "split_people.py"


def main() -> None:
    if SHOTS_DIR is None or not SHOTS_DIR.is_dir():
        print("Burn 500 shots folder not found", file=sys.stderr)
        sys.exit(1)

    shots = sorted(SHOTS_DIR.glob("shot_*.mp4"))
    if not shots:
        print(f"No shot_*.mp4 in {SHOTS_DIR}", file=sys.stderr)
        sys.exit(1)

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    summary = {
        "source_shots_dir": str(SHOTS_DIR.as_posix()),
        "out_root": str(OUT_ROOT.as_posix()),
        "n_shots": len(shots),
        "shots": [],
    }

    print(f"Batch YOLO on {len(shots)} shots -> {OUT_ROOT}", flush=True)
    t0 = time.time()

    for i, shot in enumerate(shots):
        out = OUT_ROOT / shot.stem  # shot_000, shot_001, ...
        print(f"\n===== [{i + 1}/{len(shots)}] {shot.name} -> {out.name} =====", flush=True)
        cmd = [
            sys.executable,
            "-u",
            str(SCRIPT),
            "--video",
            str(shot),
            "--out",
            str(out),
            "--device",
            "0",
            "--model",
            "yolo11n.pt",
            "--min-sec",
            "3",
            "--min-area-frac",
            "0.02",
            "--conf",
            "0.35",
            "--crop-mode",
            "max_box",
            "--pad",
            "0",
        ]
        t1 = time.time()
        proc = subprocess.run(cmd)
        elapsed = time.time() - t1
        entry = {
            "shot": shot.name,
            "out": str(out.as_posix()),
            "exit_code": proc.returncode,
            "elapsed_sec": round(elapsed, 1),
        }
        manifest = out / "people_manifest.json"
        if manifest.exists():
            try:
                m = json.loads(manifest.read_text(encoding="utf-8"))
                entry["n_people"] = m.get("n_people", 0)
                entry["people"] = [
                    {
                        "person_id": p.get("person_id"),
                        "duration_sec": p.get("duration_sec"),
                    }
                    for p in m.get("people", [])
                ]
            except Exception as e:
                entry["manifest_error"] = str(e)
        else:
            entry["n_people"] = 0
        summary["shots"].append(entry)
        print(
            f"----- done {shot.name} exit={proc.returncode} "
            f"people={entry.get('n_people', '?')} ({elapsed:.0f}s) -----",
            flush=True,
        )
        if proc.returncode != 0:
            print(f"WARNING: {shot.name} failed", flush=True)

    summary["elapsed_sec"] = round(time.time() - t0, 1)
    summary["n_people_total"] = sum(s.get("n_people", 0) or 0 for s in summary["shots"])
    summary["n_failed"] = sum(1 for s in summary["shots"] if s.get("exit_code", 1) != 0)
    (OUT_ROOT / "batch_manifest.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(
        f"\nBatch done in {summary['elapsed_sec']}s - "
        f"{summary['n_people_total']} people across {len(shots)} shots "
        f"({summary['n_failed']} failed)",
        flush=True,
    )
    print(f"Manifest: {OUT_ROOT / 'batch_manifest.json'}", flush=True)


if __name__ == "__main__":
    main()
