#!/usr/bin/env python3
"""From-scratch YOLO person split for all shot folders (max_box, all people).

Usage:
  python scripts/batch_split_all_people.py
  python scripts/batch_split_all_people.py --wipe
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parents[1]
SHOTS_ROOT = LAB_ROOT / "data" / "input" / "shots"
PEOPLE_ROOT = LAB_ROOT / "data" / "input" / "people"
SCRIPT = LAB_ROOT / "scripts" / "split_people.py"


def slug_source(name: str) -> str:
    n = name.lower()
    if "beginner" in n:
        return "beginner_friendly_20_boxing"
    if "burn 500" in n or "burn_500" in n:
        return "burn_500_shots"
    if "max calories" in n or "left_half" in n or "burn max" in n:
        return "max_calories_left_half"
    if "intense" in n and "shadow" in n:
        return "intense_10_shadow"
    out = []
    prev = False
    for ch in n:
        if ch.isalnum():
            out.append(ch)
            prev = False
        elif not prev:
            out.append("_")
            prev = True
    return "".join(out).strip("_")[:50]


def discover_jobs() -> list[dict]:
    jobs = []
    if not SHOTS_ROOT.is_dir():
        return jobs
    for folder in sorted(SHOTS_ROOT.iterdir()):
        if not folder.is_dir():
            continue
        shots = sorted(folder.glob("shot_*.mp4"))
        if not shots:
            continue
        src = slug_source(folder.name)
        for shot in shots:
            if src == "burn_500_shots":
                out = PEOPLE_ROOT / "burn_500_shots" / shot.stem
                min_sec = "3"
                min_area = "0.02"
            elif src == "beginner_friendly_20_boxing":
                out = PEOPLE_ROOT / f"beginner_friendly_20_boxing_{shot.stem}"
                min_sec = "15"
                min_area = "0.015"
            elif src == "max_calories_left_half":
                # solo boxing / left half — keep longer tracks
                out = PEOPLE_ROOT / "max_calories_left_half" / shot.stem
                min_sec = "10"
                min_area = "0.02"
            else:
                out = PEOPLE_ROOT / src / shot.stem
                min_sec = "5"
                min_area = "0.015"
            jobs.append(
                {
                    "video": shot,
                    "out": out,
                    "min_sec": min_sec,
                    "min_area_frac": min_area,
                    "source": src,
                }
            )
    return jobs


def wipe_people() -> None:
    if not PEOPLE_ROOT.exists():
        return
    print(f"[wipe] clearing {PEOPLE_ROOT}", flush=True)
    for child in PEOPLE_ROOT.iterdir():
        if child.name == ".gitkeep":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            # keep reports optional — wipe everything except gitkeep
            child.unlink()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wipe", action="store_true", help="delete data/input/people/* first")
    ap.add_argument("--device", default="0")
    ap.add_argument("--crop-mode", default="max_box")
    ap.add_argument("--pad", default="0")
    ap.add_argument("--dedup-iou", default="0.55")
    ap.add_argument("--only", default="", help="substring filter on source/out path")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    if args.wipe:
        wipe_people()

    jobs = discover_jobs()
    if args.only:
        key = args.only.lower()
        jobs = [j for j in jobs if key in str(j["out"]).lower() or key in str(j["video"]).lower()]
    if args.limit > 0:
        jobs = jobs[: args.limit]

    if not jobs:
        print("No shot_*.mp4 jobs found", file=sys.stderr)
        sys.exit(1)

    PEOPLE_ROOT.mkdir(parents=True, exist_ok=True)
    summary = {
        "crop_mode": args.crop_mode,
        "pad": args.pad,
        "dedup_iou": args.dedup_iou,
        "n_jobs": len(jobs),
        "jobs": [],
    }
    print(
        f"Batch from-scratch: {len(jobs)} shots | crop={args.crop_mode} pad={args.pad} "
        f"dedup_iou={args.dedup_iou}",
        flush=True,
    )
    t0 = time.time()

    for i, job in enumerate(jobs, 1):
        video: Path = job["video"]
        out: Path = job["out"]
        out.parent.mkdir(parents=True, exist_ok=True)
        print(f"\n===== [{i}/{len(jobs)}] {video.parent.name}/{video.name} =====", flush=True)
        print(f"      -> {out}", flush=True)
        cmd = [
            sys.executable,
            "-u",
            str(SCRIPT),
            "--video",
            str(video),
            "--out",
            str(out),
            "--device",
            args.device,
            "--model",
            "yolo11n.pt",
            "--min-sec",
            job["min_sec"],
            "--min-area-frac",
            job["min_area_frac"],
            "--conf",
            "0.35",
            "--crop-mode",
            args.crop_mode,
            "--pad",
            args.pad,
            "--dedup-iou",
            args.dedup_iou,
            "--clean-out",
        ]
        t1 = time.time()
        proc = subprocess.run(cmd)
        elapsed = time.time() - t1
        entry = {
            "video": str(video.as_posix()),
            "out": str(out.as_posix()),
            "source": job["source"],
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
                        "crop_w": p.get("crop_w"),
                        "crop_h": p.get("crop_h"),
                    }
                    for p in m.get("people", [])
                ]
            except Exception as e:
                entry["manifest_error"] = str(e)
        else:
            entry["n_people"] = 0
        summary["jobs"].append(entry)
        print(
            f"----- exit={proc.returncode} people={entry.get('n_people', '?')} "
            f"({elapsed:.0f}s) -----",
            flush=True,
        )

    summary["elapsed_sec"] = round(time.time() - t0, 1)
    summary["n_people_total"] = sum(j.get("n_people", 0) or 0 for j in summary["jobs"])
    summary["n_failed"] = sum(1 for j in summary["jobs"] if j.get("exit_code", 1) != 0)
    out_manifest = PEOPLE_ROOT / "batch_from_scratch_manifest.json"
    out_manifest.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(
        f"\nDone in {summary['elapsed_sec']}s — {summary['n_people_total']} people, "
        f"{summary['n_failed']} failed\nManifest: {out_manifest}",
        flush=True,
    )
    if summary["n_failed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
