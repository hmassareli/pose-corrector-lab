#!/usr/bin/env python3
"""Curate main person clips from split_people output (de-overlap fragments)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "data" / "input" / "people" / "burn_500_calories"


def overlap(a: dict, b: dict) -> float:
    s = max(a["start_sec"], b["start_sec"])
    e = min(a["end_sec"], b["end_sec"])
    inter = max(0.0, e - s)
    if inter <= 0:
        return 0.0
    shorter = min(a["duration_sec"], b["duration_sec"])
    return inter / max(shorter, 1e-6)


def main() -> None:
    manifest = json.loads((ROOT / "people_manifest.json").read_text(encoding="utf-8"))
    people = manifest["people"]
    ranked = sorted(people, key=lambda p: (p["duration_sec"], p["mean_area_frac"]), reverse=True)
    selected: list[dict] = []
    for p in ranked:
        conflicts = [s for s in selected if overlap(p, s) >= 0.45]
        if conflicts:
            best_conf = max(conflicts, key=lambda s: s["mean_area_frac"])
            if (
                p["mean_area_frac"] >= best_conf["mean_area_frac"] * 1.25
                and p["duration_sec"] >= best_conf["duration_sec"] * 0.7
            ):
                for c in conflicts:
                    if c in selected:
                        selected.remove(c)
                selected.append(p)
            continue
        selected.append(p)
        if len(selected) >= 12:
            break

    selected = sorted(selected, key=lambda p: p["start_sec"])
    selected_ids = {p["person_id"] for p in selected}

    frag = ROOT / "fragments"
    frag.mkdir(exist_ok=True)
    moved = 0
    kept = 0
    for d in sorted(ROOT.iterdir()):
        if not d.is_dir() or not d.name.startswith("person_"):
            continue
        if d.name in selected_ids:
            kept += 1
            continue
        dest = frag / d.name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.move(str(d), str(dest))
        moved += 1

    curated = {
        "note": "Primary person clips for training (longest tracks, de-overlapped). Rest in fragments/.",
        "n_main": len(selected),
        "n_fragments": moved,
        "people": selected,
    }
    (ROOT / "main_manifest.json").write_text(json.dumps(curated, indent=2), encoding="utf-8")
    print(f"kept_main={kept} moved_fragments={moved}")
    for i, p in enumerate(selected):
        print(
            f"  main[{i}] {p['person_id']}: {p['start_sec']:.0f}-{p['end_sec']:.0f}s "
            f"({p['duration_sec']:.0f}s) area={p['mean_area_frac']:.3f}"
        )


if __name__ == "__main__":
    main()
