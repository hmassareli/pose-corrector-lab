#!/usr/bin/env python3
"""Export corrected test + benches + append ablation leaderboard.

Primary game-relevant metric (higher better for ranking):
  hand_prox_impr_vs_mp from scripts/bench_extended_shoulder_level_hands.py
  (teacher extended + shoulder-level frames; lower hand_prox_mae_C is better).

Also records elbow MAE, val hard MPJPE, and test-split hard MPJPE
(via scripts/eval.py --split test).

Usage:
  python scripts/run_ablation_eval.py --run-dir runs/<id> --name angle_v1 --ckpt both
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

LAB_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXP_ROOT = LAB_ROOT / "experiments" / "ablation_20260726"
EXP_ROOT = DEFAULT_EXP_ROOT
LEADERBOARD = EXP_ROOT / "leaderboard.tsv"
RESULTS_JSONL = EXP_ROOT / "results.jsonl"


def _set_exp_root(path: Path) -> None:
    global EXP_ROOT, LEADERBOARD, RESULTS_JSONL
    EXP_ROOT = path if path.is_absolute() else LAB_ROOT / path
    LEADERBOARD = EXP_ROOT / "leaderboard.tsv"
    RESULTS_JSONL = EXP_ROOT / "results.jsonl"

TSV_COLS = [
    "name",
    "hand_prox_mae_C",
    "hand_prox_mae_MP",
    "hand_prox_impr_vs_mp",
    "pct_frames_C_closer_hands",
    "n_frames_selected_hands",
    "config_hash",
    "best_epoch",
    "val_hard_mm",
    "val_hard_impr_pct",
    "test_hard_mm",
    "test_mp_hard_mm",
    "test_hard_impr_pct",
    "elbow_mae_C_T",
    "elbow_mae_MP_T",
    "pct_closer_than_mp",
    "notes",
    "run_dir",
    "ckpt_used",
    "easy_ok",
    "ext_reach_gt_mp_pct",
    "measured_unix",
]
TSV_HEADER = "\t".join(TSV_COLS) + "\n"


def _run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    r = subprocess.run(cmd, cwd=str(LAB_ROOT), env=env)
    if r.returncode != 0:
        raise SystemExit(f"command failed ({r.returncode}): {' '.join(cmd)}")


def _config_hash(run_dir: Path) -> str:
    for name in ("config.json", "config.yaml"):
        p = run_dir / name
        if p.is_file():
            return hashlib.sha1(p.read_bytes()).hexdigest()[:10]
    return "unknown"


def _load_summary(run_dir: Path) -> dict[str, Any]:
    out: dict[str, Any] = {
        "best_epoch": None,
        "val_hard_mm": None,
        "val_hard_impr_pct": None,
        "easy_ok": None,
    }
    summary = run_dir / "summary.json"
    metrics = run_dir / "metrics.jsonl"
    best_ep = None
    if summary.is_file():
        s = json.loads(summary.read_text(encoding="utf-8"))
        best_ep = s.get("best_epoch")
        out["best_epoch"] = best_ep
        out["val_hard_mm"] = s.get("best_hard_mm")
    if not metrics.is_file():
        return out
    rows = [json.loads(l) for l in metrics.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not rows:
        return out
    if best_ep is not None:
        for r in rows:
            if int(r.get("epoch", -1)) == int(best_ep):
                out["val_hard_mm"] = r.get("val/mpjpe_hard_mm", out["val_hard_mm"])
                out["val_hard_impr_pct"] = r.get("val/hard_improvement_pct")
                out["easy_ok"] = r.get("easy_ok")
                break
    else:
        ok = [r for r in rows if r.get("easy_ok")]
        pool = ok or rows
        best = min(pool, key=lambda r: float(r.get("val/mpjpe_hard_mm", 1e18)))
        out["best_epoch"] = best.get("epoch")
        out["val_hard_mm"] = best.get("val/mpjpe_hard_mm")
        out["val_hard_impr_pct"] = best.get("val/hard_improvement_pct")
        out["easy_ok"] = best.get("easy_ok")
    return out


def _elbow_from_bench(bench_path: Path, label: str) -> dict[str, float | None]:
    d = json.loads(bench_path.read_text(encoding="utf-8"))
    block = (d.get("compare") or {}).get(label) or (d.get("checkpoints") or {}).get(label)
    if not block:
        raise SystemExit(f"label {label!r} missing in {bench_path}")
    e = block.get("elbow_both") or (block.get("elbow") or {}).get("both")
    if not e:
        raise SystemExit(f"elbow_both missing for {label} in {bench_path}")
    return {
        "elbow_mae_C_T": float(e["mean_abs_err_corrector"]),
        "elbow_mae_MP_T": float(e["mean_abs_err_mp"]),
        "pct_closer_than_mp": float(e["pct_corrector_closer_than_mp"]),
    }


def _ext_impr(bench_path: Path, label: str) -> float | None:
    if not bench_path.is_file():
        return None
    d = json.loads(bench_path.read_text(encoding="utf-8"))
    block = (d.get("compare") or {}).get(label) or (d.get("checkpoints") or {}).get(label)
    if not block:
        agg = d.get("aggregate") or {}
        v = agg.get("pct_corrector_reach_gt_mp")
        return float(v) if v is not None else None
    for key in ("pct_corrector_reach_gt_mp", "reach_improvement_pct_vs_mp"):
        if key in block and block[key] is not None:
            return float(block[key])
    both = block.get("both") or {}
    v = both.get("pct_corrector_reach_gt_mp")
    return float(v) if v is not None else None


def _hands_from_bench(bench_path: Path, label: str) -> dict[str, Any]:
    d = json.loads(bench_path.read_text(encoding="utf-8"))
    block = (d.get("compare") or {}).get(label)
    if not block:
        raise SystemExit(f"label {label!r} missing in {bench_path}")
    return {
        "hand_prox_mae_C": block.get("hand_prox_mae_C"),
        "hand_prox_mae_MP": block.get("hand_prox_mae_MP"),
        "hand_prox_impr_vs_mp": block.get("hand_prox_impr_vs_mp"),
        "pct_frames_C_closer_hands": block.get("pct_frames_C_closer"),
        "n_frames_selected_hands": block.get("n_frames_selected"),
    }


def _ensure_leaderboard_schema() -> None:
    """Create or migrate leaderboard.tsv to current TSV_COLS."""
    EXP_ROOT.mkdir(parents=True, exist_ok=True)
    if not LEADERBOARD.is_file():
        LEADERBOARD.write_text(TSV_HEADER, encoding="utf-8")
        return
    text = LEADERBOARD.read_text(encoding="utf-8")
    if not text.strip():
        LEADERBOARD.write_text(TSV_HEADER, encoding="utf-8")
        return
    lines = [l for l in text.splitlines() if l.strip()]
    old_header = lines[0].split("\t")
    if old_header == TSV_COLS:
        return
    body = lines[1:]
    migrated: list[str] = [TSV_HEADER.rstrip("\n")]
    for line in body:
        parts = line.split("\t")
        old = {old_header[i]: parts[i] if i < len(parts) else "" for i in range(len(old_header))}
        migrated.append("\t".join(str(old.get(c, "")) for c in TSV_COLS))
    LEADERBOARD.write_text("\n".join(migrated) + "\n", encoding="utf-8")
    print(f"[eval] migrated leaderboard schema -> {LEADERBOARD}", flush=True)


def _append_leaderboard(row: dict[str, Any]) -> None:
    _ensure_leaderboard_schema()
    line = "\t".join(str(row.get(c, "")) for c in TSV_COLS) + "\n"
    with LEADERBOARD.open("a", encoding="utf-8") as f:
        f.write(line)
    with RESULTS_JSONL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _run_test_hard(
    ckpt_path: Path,
    device: str,
    dataset_dir: Path,
) -> dict[str, float | None]:
    """Window-npz hard MPJPE on test split (same mask as train eval)."""
    out_json = ckpt_path.parent.parent / "eval" / f"test_{ckpt_path.stem}.json"
    _run(
        [
            sys.executable,
            "scripts/eval.py",
            "--ckpt",
            str(ckpt_path),
            "--split",
            "test",
            "--device",
            device,
            "--dataset-dir",
            str(dataset_dir),
        ]
    )
    if not out_json.is_file():
        # Fallback to legacy path written by older eval.py
        out_json = ckpt_path.parent.parent / "eval" / "test_final.json"
    if not out_json.is_file():
        raise SystemExit(f"missing test hard eval json for {ckpt_path}")
    d = json.loads(out_json.read_text(encoding="utf-8"))
    return {
        "test_hard_mm": d.get("mpjpe_hard_mm"),
        "test_mp_hard_mm": d.get("mpjpe_mp_hard_mm"),
        "test_hard_impr_pct": d.get("hard_improvement_pct"),
    }


def _sort_leaderboard() -> None:
    if not LEADERBOARD.is_file():
        return
    _ensure_leaderboard_schema()
    lines = LEADERBOARD.read_text(encoding="utf-8").splitlines()
    if len(lines) <= 1:
        return
    header, body = lines[0], [l for l in lines[1:] if l.strip()]
    cols = header.split("\t")

    def idx(name: str, default: int) -> int:
        try:
            return cols.index(name)
        except ValueError:
            return default

    i_impr = idx("hand_prox_impr_vs_mp", 3)
    i_mae = idx("hand_prox_mae_C", 1)
    i_elbow = idx("elbow_mae_C_T", 13 if "test_hard_mm" in cols else 10)

    def key(line: str):
        parts = line.split("\t")

        def f(i: int, empty: float) -> float:
            try:
                v = parts[i]
                return float(v) if v not in ("", "None") else empty
            except Exception:
                return empty

        # Higher hand_prox_impr better; then lower hand MAE; then lower elbow MAE
        return (-f(i_impr, -1e18), f(i_mae, 1e18), f(i_elbow, 1e18))

    LEADERBOARD.write_text(header + "\n" + "\n".join(sorted(body, key=key)) + "\n", encoding="utf-8")


def _write_entry_pointer(name: str, run_dir: Path, row: dict[str, Any]) -> None:
    ent = EXP_ROOT / "entries" / name
    ent.mkdir(parents=True, exist_ok=True)
    (ent / "run_dir.txt").write_text(str(run_dir.resolve()) + "\n", encoding="utf-8")
    (ent / "metrics_snippet.json").write_text(json.dumps(row, indent=2), encoding="utf-8")
    for src_name in ("config.json", "config.yaml", "summary.json"):
        src = run_dir / src_name
        if src.is_file():
            shutil.copy2(src, ent / src_name)


def export_ckpt(ckpt: Path, out: Path, device: str) -> None:
    if out.is_dir() and any(out.glob("*/joints3d.npy")):
        print(f"[eval] reuse existing export {out}", flush=True)
        return
    _run(
        [
            sys.executable,
            "scripts/export_corrected.py",
            "--ckpt",
            str(ckpt),
            "--split",
            "test",
            "--out",
            str(out),
            "--device",
            device,
        ]
    )


def measure_one(
    *,
    run_dir: Path,
    name: str,
    ckpt_tag: str,
    ckpt_path: Path,
    notes: str,
    skip_export: bool,
    skip_extension: bool,
    skip_hands: bool,
    skip_test_hard: bool,
    device: str,
    force_reexport: bool,
    dataset_dir: Path,
) -> dict[str, Any]:
    corr_dir = run_dir / f"corrected_{ckpt_tag}"
    if force_reexport and corr_dir.is_dir():
        shutil.rmtree(corr_dir)
    if not skip_export:
        export_ckpt(ckpt_path, corr_dir, device)
    if not corr_dir.is_dir():
        raise SystemExit(f"missing corrected dir {corr_dir}")

    arm_out = run_dir / "eval" / f"arm_angles_{name}_{ckpt_tag}.json"
    ext_out = run_dir / "eval" / f"extension_{name}_{ckpt_tag}.json"
    hands_out = run_dir / "eval" / f"hands_ext_shl_{name}_{ckpt_tag}.json"
    arm_out.parent.mkdir(parents=True, exist_ok=True)

    test_hard: dict[str, float | None]
    if skip_test_hard:
        test_hard = {
            "test_hard_mm": None,
            "test_mp_hard_mm": None,
            "test_hard_impr_pct": None,
        }
    else:
        test_hard = _run_test_hard(ckpt_path, device, dataset_dir)

    _run(
        [
            sys.executable,
            "scripts/bench_arm_angles.py",
            "--run",
            str(run_dir),
            "--corrected",
            f"{ckpt_tag}={corr_dir}",
            "--out",
            str(arm_out),
        ]
    )
    if not skip_hands:
        _run(
            [
                sys.executable,
                "scripts/bench_extended_shoulder_level_hands.py",
                "--run",
                str(run_dir),
                "--corrected",
                f"{ckpt_tag}={corr_dir}",
                "--out",
                str(hands_out),
            ]
        )
    if not skip_extension:
        _run(
            [
                sys.executable,
                "scripts/bench_extension.py",
                "--corrected-root",
                str(corr_dir),
                "--label",
                ckpt_tag,
                "--out",
                str(ext_out),
            ]
        )

    summary = _load_summary(run_dir)
    elbow = _elbow_from_bench(arm_out, ckpt_tag)
    hands = (
        _hands_from_bench(hands_out, ckpt_tag)
        if not skip_hands and hands_out.is_file()
        else {
            "hand_prox_mae_C": None,
            "hand_prox_mae_MP": None,
            "hand_prox_impr_vs_mp": None,
            "pct_frames_C_closer_hands": None,
            "n_frames_selected_hands": None,
        }
    )
    row: dict[str, Any] = {
        "name": f"{name}_{ckpt_tag}",
        **hands,
        "config_hash": _config_hash(run_dir),
        "best_epoch": summary.get("best_epoch"),
        "val_hard_mm": summary.get("val_hard_mm"),
        "val_hard_impr_pct": summary.get("val_hard_impr_pct"),
        **test_hard,
        "elbow_mae_C_T": elbow["elbow_mae_C_T"],
        "elbow_mae_MP_T": elbow["elbow_mae_MP_T"],
        "pct_closer_than_mp": elbow["pct_closer_than_mp"],
        "notes": notes,
        "run_dir": str(run_dir.resolve()),
        "ckpt_used": ckpt_tag,
        "easy_ok": summary.get("easy_ok"),
        "ext_reach_gt_mp_pct": _ext_impr(ext_out, ckpt_tag) if not skip_extension else None,
        "measured_unix": time.time(),
        "ckpt_path": str(ckpt_path.resolve()),
        "corrected_dir": str(corr_dir.resolve()),
        "arm_angles_json": str(arm_out.resolve()),
        "hands_json": str(hands_out.resolve()) if not skip_hands else None,
        "extension_json": str(ext_out.resolve()) if not skip_extension else None,
        "test_hard_json": str(
            (run_dir / "eval" / f"test_{ckpt_path.stem}.json").resolve()
        )
        if not skip_test_hard
        else None,
    }
    for k in (
        "hand_prox_mae_C",
        "hand_prox_mae_MP",
        "hand_prox_impr_vs_mp",
        "pct_frames_C_closer_hands",
        "val_hard_mm",
        "val_hard_impr_pct",
        "test_hard_mm",
        "test_mp_hard_mm",
        "test_hard_impr_pct",
        "elbow_mae_C_T",
        "elbow_mae_MP_T",
        "pct_closer_than_mp",
        "ext_reach_gt_mp_pct",
    ):
        v = row.get(k)
        if isinstance(v, float):
            row[k] = round(v, 4)
    _append_leaderboard(row)
    _write_entry_pointer(row["name"], run_dir, row)
    return row


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--ckpt", choices=("best", "last", "both"), default="both")
    ap.add_argument("--notes", default="")
    ap.add_argument("--skip-export", action="store_true")
    ap.add_argument("--skip-extension", action="store_true")
    ap.add_argument("--skip-hands", action="store_true")
    ap.add_argument("--skip-test-hard", action="store_true")
    ap.add_argument("--force-reexport", action="store_true")
    ap.add_argument("--device", default="cuda")
    ap.add_argument(
        "--dataset-dir",
        type=Path,
        default=LAB_ROOT / "data" / "dataset",
        help="Window dataset matching the checkpoint context length",
    )
    ap.add_argument("--no-sort", action="store_true")
    ap.add_argument("--reset-leaderboard", action="store_true")
    ap.add_argument(
        "--exp-root",
        type=Path,
        default=None,
        help=f"Experiment folder for leaderboard/entries (default: {DEFAULT_EXP_ROOT})",
    )
    args = ap.parse_args()

    if args.exp_root is not None:
        _set_exp_root(args.exp_root)

    if args.reset_leaderboard:
        EXP_ROOT.mkdir(parents=True, exist_ok=True)
        LEADERBOARD.write_text(TSV_HEADER, encoding="utf-8")
        print(f"[eval] reset {LEADERBOARD}")
    else:
        _ensure_leaderboard_schema()

    run_dir = args.run_dir if args.run_dir.is_absolute() else LAB_ROOT / args.run_dir
    if not run_dir.is_dir():
        raise SystemExit(f"run dir missing: {run_dir}")

    tags: list[tuple[str, Path]] = []
    if args.ckpt in ("best", "both"):
        p = run_dir / "checkpoints" / "best_hard.pt"
        if not p.is_file():
            raise SystemExit(f"missing {p}")
        tags.append(("best", p))
    if args.ckpt in ("last", "both"):
        p = run_dir / "checkpoints" / "last.pt"
        if not p.is_file():
            raise SystemExit(f"missing {p}")
        tags.append(("last", p))

    rows = []
    for tag, path in tags:
        rows.append(
            measure_one(
                run_dir=run_dir,
                name=args.name,
                ckpt_tag=tag,
                ckpt_path=path,
                notes=args.notes,
                skip_export=args.skip_export,
                skip_extension=args.skip_extension,
                skip_hands=args.skip_hands,
                skip_test_hard=args.skip_test_hard,
                device=args.device,
                force_reexport=args.force_reexport,
                dataset_dir=args.dataset_dir,
            )
        )
    if not args.no_sort:
        _sort_leaderboard()
    print(json.dumps({"wrote": [r["name"] for r in rows], "leaderboard": str(LEADERBOARD)}, indent=2))


if __name__ == "__main__":
    main()
