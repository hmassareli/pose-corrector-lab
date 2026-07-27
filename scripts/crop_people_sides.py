#!/usr/bin/env python3
"""Lateral-crop all YOLO person clips in-place (default 30% total = 15% each side)."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parents[1]
PEOPLE_ROOT = LAB_ROOT / "data" / "input" / "people"


def crop_one(clip: Path, total_pct: float, ff: str) -> tuple[Path, bool, str]:
    side = total_pct / 2.0 / 100.0  # each side fraction
    keep = 1.0 - 2.0 * side
    tmp = clip.with_suffix(".crop_tmp.mp4")
    # even dimensions for yuv420p
    vf = (
        f"crop=trunc(iw*{keep}/2)*2:ih:trunc(iw*{side}/2)*2:0,"
        f"setsar=1"
    )
    cmd = [
        ff,
        "-y",
        "-i",
        str(clip),
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-an",
        str(tmp),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0 or not tmp.exists() or tmp.stat().st_size < 1000:
            tmp.unlink(missing_ok=True)
            err = (r.stderr or "")[-400:]
            return clip, False, err
        tmp.replace(clip)

        meta_path = clip.parent / "meta.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta["side_crop_total_pct"] = total_pct
            meta["side_crop_each_pct"] = total_pct / 2.0
            meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return clip, True, "ok"
    except Exception as e:
        tmp.unlink(missing_ok=True)
        return clip, False, str(e)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--people-root", type=Path, default=PEOPLE_ROOT)
    ap.add_argument("--total-pct", type=float, default=30.0, help="total width to cut (split L/R)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--skip-cropped", action="store_true", help="skip clips already tagged in meta")
    args = ap.parse_args()

    ff = shutil.which("ffmpeg")
    if not ff:
        print("ffmpeg not found", file=sys.stderr)
        sys.exit(1)

    clips = sorted(args.people_root.rglob("clip.mp4"))
    # ignore temp leftovers
    clips = [c for c in clips if ".crop_tmp" not in c.name]

    if args.skip_cropped:
        kept = []
        for c in clips:
            meta_path = c.parent / "meta.json"
            if meta_path.exists():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                if meta.get("side_crop_total_pct") == args.total_pct:
                    continue
            kept.append(c)
        clips = kept

    print(
        f"[crop] clips={len(clips)} total_pct={args.total_pct} "
        f"each_side={args.total_pct/2:.1f}% workers={args.workers}",
        flush=True,
    )

    ok = fail = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(crop_one, c, args.total_pct, ff): c for c in clips}
        for i, fut in enumerate(as_completed(futs), 1):
            path, success, msg = fut.result()
            if success:
                ok += 1
            else:
                fail += 1
                print(f"[FAIL] {path.relative_to(args.people_root)}: {msg}", flush=True)
            if i % 20 == 0 or i == len(clips):
                print(f"[crop] {i}/{len(clips)} ok={ok} fail={fail}", flush=True)

    print(f"[crop] done ok={ok} fail={fail}", flush=True)
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
