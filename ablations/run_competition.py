#!/usr/bin/env python3
"""Run the GPT-vs-me ablation competition sequentially.

Reuses scripts/train.py + scripts/run_ablation_eval.py + punch trajectory bench.
Configs live in ablations/*.yaml and merge over ablations/base_dropaccel.yaml.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

LAB_ROOT = Path(__file__).resolve().parents[1]
ABL_ROOT = Path(__file__).resolve().parent
BASELINE_CKPT_RUN = LAB_ROOT / "runs" / "20260726_092251_gru_noaux_dropaccel_v1"
DONE_RE = re.compile(r"\[train\] done .* -> (.+)$")

# (name, override_yaml, train?, notes)
ENTRIES: list[tuple[str, str, bool, str]] = [
    ("baseline_dropaccel", "", False, "frozen noaux_dropaccel best_hard"),
    ("gpt_multilag", "gpt_multilag.yaml", True, "GPT multilag features"),
    ("gpt_seq_vel", "gpt_seq_vel.yaml", True, "GPT full-window + L_vel"),
    ("gpt_seq_vel_dir", "gpt_seq_vel_dir.yaml", True, "GPT seq + vel + dir"),
    ("me_seq_vel_z", "me_seq_vel_z.yaml", True, "me seq + vel + Z weight"),
    ("me_seq_vel_z_bone", "me_seq_vel_z_bone.yaml", True, "me seq + vel + Z + bone"),
]


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if k in ("team", "notes"):
            continue
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def resolve_config(override_name: str, exp_root: Path) -> Path:
    base = load_yaml(ABL_ROOT / "base_dropaccel.yaml")
    if override_name:
        ov = load_yaml(ABL_ROOT / override_name)
        cfg = deep_merge(base, ov)
        team = ov.get("team", "unknown")
        notes = ov.get("notes", "")
    else:
        cfg = base
        team = "baseline"
        notes = "baseline"
    cfg["_competition"] = {"team": team, "notes": notes, "override": override_name}
    out = exp_root / "resolved_configs" / f"{Path(override_name).stem or 'baseline'}.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return out


def _safe_out(text: str) -> None:
    try:
        sys.stdout.write(text)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        sys.stdout.write(text.encode(enc, errors="replace").decode(enc, errors="replace"))


def _run(cmd: list[str], log_path: Path) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    print("+", " ".join(cmd), flush=True)
    print(f"[comp] log -> {log_path}", flush=True)
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
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
            _safe_out(line)
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


def ensure_y_seq() -> None:
    meta = LAB_ROOT / "data" / "dataset" / "meta.json"
    if meta.is_file():
        m = json.loads(meta.read_text(encoding="utf-8"))
        if m.get("y_seq"):
            print("[comp] y_seq already present in dataset meta", flush=True)
            return
    # Also check train.npz keys
    train = LAB_ROOT / "data" / "dataset" / "train.npz"
    if train.is_file():
        import numpy as np

        keys = set(np.load(train, allow_pickle=True).files)
        if "y_seq" in keys:
            print("[comp] y_seq present in train.npz", flush=True)
            return
    print("[comp] augmenting NPZs with y_seq…", flush=True)
    rc = _run(
        [sys.executable, "scripts/augment_npz_yseq.py", "--splits", "train", "val"],
        LAB_ROOT / "runs" / "_augment_yseq.log",
    )
    if rc != 0:
        raise SystemExit(f"augment_npz_yseq failed rc={rc}")


def train_one(
    name: str,
    config: Path,
    exp_root: Path,
    *,
    dataset_dir: Path | None = None,
) -> Path:
    log = exp_root / "logs" / f"train_{name}.log"
    cmd = [sys.executable, "scripts/train.py", "--config", str(config)]
    if dataset_dir is not None:
        cmd.extend(["--dataset-dir", str(dataset_dir)])
    rc = _run(cmd, log)
    text = log.read_text(encoding="utf-8", errors="replace")
    done_ok = bool(DONE_RE.search(text))
    if rc != 0 and not done_ok:
        # Try salvage: train crashed but may have best_hard.pt
        # Look for newest run matching logging.run_name from config
        cfg = load_yaml(config)
        run_name = str((cfg.get("logging") or {}).get("run_name") or name)
        runs = sorted(
            (LAB_ROOT / "runs").glob(f"*_{run_name}"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        salvaged = None
        for cand in runs[:3]:
            if (cand / "checkpoints" / "best_hard.pt").is_file():
                _run(
                    [
                        sys.executable,
                        "scripts/salvage_run.py",
                        "--run-dir",
                        str(cand),
                        "--exp-root",
                        str(exp_root),
                        "--name",
                        name,
                    ],
                    exp_root / "logs" / f"salvage_{name}.log",
                )
                salvaged = cand
                break
        if salvaged is None:
            raise SystemExit(f"train failed for {name} rc={rc}")
        print(f"[comp] salvaged interrupted run {salvaged}", flush=True)
        return salvaged.resolve()
    if rc != 0 and done_ok:
        print(f"[comp] warn: train rc={rc} but found [train] done — continuing", flush=True)
    run_dir = _parse_run_dir(log)
    (exp_root / f"run_{name}.txt").write_text(str(run_dir.resolve()) + "\n", encoding="utf-8")
    return run_dir


def eval_one(
    name: str,
    run_dir: Path,
    notes: str,
    exp_root: Path,
    *,
    reset: bool = False,
    dataset_dir: Path | None = None,
) -> None:
    cmd = [
        sys.executable,
        "scripts/run_ablation_eval.py",
        "--exp-root",
        str(exp_root),
        "--run-dir",
        str(run_dir),
        "--name",
        name,
        "--ckpt",
        "best",
        "--notes",
        notes,
    ]
    if dataset_dir is not None:
        cmd.extend(["--dataset-dir", str(dataset_dir)])
    if reset:
        cmd.append("--reset-leaderboard")
    rc = _run(cmd, exp_root / "logs" / f"eval_{name}.log")
    if rc != 0:
        raise SystemExit(f"eval failed for {name} rc={rc}")

    # Punch trajectory bench on corrected_best
    corr = run_dir / "corrected_best"
    if not corr.is_dir():
        # run_ablation_eval names export corrected_best for ckpt tag "best"
        alt = run_dir / "corrected_best"
        corr = alt
    punch_out = run_dir / "eval" / f"punch_{name}_best.json"
    if corr.is_dir():
        rc = _run(
            [
                sys.executable,
                "scripts/bench_punch_trajectory.py",
                "--corrected",
                str(corr),
                "--label",
                "best",
                "--out",
                str(punch_out),
            ],
            exp_root / "logs" / f"punch_{name}.log",
        )
        if rc != 0:
            print(f"[comp] warn: punch bench failed for {name} rc={rc}", flush=True)
    else:
        print(f"[comp] warn: missing corrected export {corr}", flush=True)


def write_conclusions(exp_root: Path) -> None:
    lb = exp_root / "leaderboard.tsv"
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

    bestish = [r for r in rows if r.get("ckpt_used") == "best"] or rows
    bestish = sorted(
        bestish,
        key=lambda r: (-f(r, "hand_prox_impr_vs_mp"), f(r, "hand_prox_mae_C"), f(r, "test_hard_mm")),
    )

    punch_by_name: dict[str, Any] = {}
    for r in bestish:
        name = str(r.get("name", "")).replace("_best", "")
        run_dir = Path(r.get("run_dir") or "")
        punch_path = run_dir / "eval" / f"punch_{name}_best.json"
        if punch_path.is_file():
            punch_by_name[name] = json.loads(punch_path.read_text(encoding="utf-8"))

    table = [
        "| rank | name | team | hand_prox_mae | test_hard | test_impr% | elbow | punch_score |",
        "|-----:|------|------|--------------:|----------:|-----------:|------:|------------:|",
    ]
    for i, r in enumerate(bestish, 1):
        name = str(r.get("name", ""))
        bare = name.replace("_best", "")
        team = "baseline"
        if bare.startswith("gpt_"):
            team = "gpt"
        elif bare.startswith("me_"):
            team = "me"
        ps = punch_by_name.get(bare, {}).get("punch_score")
        ps_s = f"{ps:.4f}" if isinstance(ps, (int, float)) else ""
        table.append(
            f"| {i} | {name} | {team} | {r.get('hand_prox_mae_C')} | {r.get('test_hard_mm')} | "
            f"{r.get('test_hard_impr_pct')} | {r.get('elbow_mae_C_T')} | {ps_s} |"
        )

    punch_rows = []
    for name, p in punch_by_name.items():
        punch_rows.append(
            f"- **{name}**: punch_score={p.get('punch_score')}, "
            f"peak_wrist_C={p.get('peak_wrist_err_mm_C')}, "
            f"timing_C={p.get('timing_err_frames_C')}, "
            f"dir_C={p.get('direction_cos_err_C')}, "
            f"idle_mm={p.get('idle_delta_mm')}"
        )

    winner = bestish[0] if bestish else None
    md = f"""# Competition conclusions

Folder: `{exp_root.as_posix()}`

## Ranking (best ckpts)
{chr(10).join(table)}

## Punch trajectory (game-oriented)
{chr(10).join(punch_rows) if punch_rows else "- (no punch benches yet)"}

## Winner (by hand proximity / test hard)
{f"`{winner.get('run_dir')}/checkpoints/best_hard.pt`" if winner else "TBD"}

## Go criteria reminder
- Prefer ≥3% hard improvement vs baseline without easy regression >3%
- Prefer higher punch_score (peak / timing / direction / idle)
- Shoulders remain corrected in all candidates
"""
    (exp_root / "CONCLUSIONS.md").write_text(md, encoding="utf-8")
    status = {
        "n_rows": len(rows),
        "top": [
            {
                "name": r.get("name"),
                "hand_prox_mae_C": r.get("hand_prox_mae_C"),
                "test_hard_mm": r.get("test_hard_mm"),
                "test_hard_impr_pct": r.get("test_hard_impr_pct"),
                "punch_score": punch_by_name.get(str(r.get("name", "")).replace("_best", ""), {}).get(
                    "punch_score"
                ),
            }
            for r in bestish[:5]
        ],
        "leaderboard": str(lb),
    }
    (exp_root / "wave_status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
    print(json.dumps(status, indent=2), flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--exp-root",
        type=Path,
        default=None,
        help="Default: ablations/competition_YYYYMMDD",
    )
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--from-name", default=None)
    ap.add_argument("--skip-augment", action="store_true")
    ap.add_argument("--conclusions-only", action="store_true")
    ap.add_argument(
        "--eval-only",
        action="store_true",
        help="Only eval runs already pointed by run_*.txt",
    )
    ap.add_argument(
        "--baseline-run",
        type=Path,
        default=BASELINE_CKPT_RUN,
        help="Existing dropaccel run dir for baseline eval",
    )
    ap.add_argument(
        "--reset-leaderboard",
        action="store_true",
        help="Force reset leaderboard on first eval",
    )
    args = ap.parse_args()

    exp_root = args.exp_root
    if exp_root is None:
        stamp = datetime.now().strftime("%Y%m%d")
        exp_root = ABL_ROOT / f"competition_{stamp}"
    if not exp_root.is_absolute():
        exp_root = LAB_ROOT / exp_root
    exp_root.mkdir(parents=True, exist_ok=True)
    (exp_root / "logs").mkdir(parents=True, exist_ok=True)

    if args.conclusions_only:
        write_conclusions(exp_root)
        return

    if not args.skip_augment:
        ensure_y_seq()

    entries = ENTRIES
    if args.only:
        want = set(args.only)
        entries = [e for e in ENTRIES if e[0] in want]
    if args.from_name:
        idx = next(i for i, e in enumerate(ENTRIES) if e[0] == args.from_name)
        entries = ENTRIES[idx:]
        if args.only:
            want = set(args.only)
            entries = [e for e in entries if e[0] in want]

    lb = exp_root / "leaderboard.tsv"
    lb_empty = (not lb.is_file()) or (
        len([l for l in lb.read_text(encoding="utf-8").splitlines() if l.strip()]) < 2
    )
    first = bool(args.reset_leaderboard or lb_empty)
    for name, override, do_train, notes in entries:
        print(f"\n======== COMPETITION {name} ========", flush=True)
        if args.eval_only or not do_train:
            pointer = exp_root / f"run_{name}.txt"
            if name == "baseline_dropaccel":
                run_dir = args.baseline_run if args.baseline_run.is_absolute() else LAB_ROOT / args.baseline_run
            elif pointer.is_file():
                run_dir = Path(pointer.read_text(encoding="utf-8").strip())
            else:
                raise SystemExit(f"missing run pointer for {name}: {pointer}")
            eval_one(name, run_dir, notes, exp_root, reset=first)
            first = False
            write_conclusions(exp_root)
            continue

        cfg_path = resolve_config(override, exp_root)
        run_dir = train_one(name, cfg_path, exp_root)
        eval_one(name, run_dir, notes, exp_root, reset=first)
        first = False
        write_conclusions(exp_root)
        print(f"[comp] finished {name} -> {run_dir}", flush=True)

    write_conclusions(exp_root)
    print(f"[comp] all done -> {exp_root}", flush=True)


if __name__ == "__main__":
    main()
