#!/usr/bin/env python3
"""Write a rich morning RESULTS.md for the competition folder.

Re-runs punch benches if missing/stale, merges leaderboard + punch scores,
declares GPT vs me winner, and lists recommended next steps.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

LAB_ROOT = Path(__file__).resolve().parents[1]
ABL_ROOT = Path(__file__).resolve().parent


def _run(cmd: list[str]) -> int:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=str(LAB_ROOT), env=env).returncode


def _f(row: dict, key: str) -> float:
    try:
        return float(row.get(key) or "nan")
    except Exception:
        return float("nan")


def _team(name: str) -> str:
    bare = name.replace("_best", "").replace("_last", "")
    if bare.startswith("gpt_"):
        return "gpt"
    if bare.startswith("me_"):
        return "me"
    if bare.startswith("hybrid_"):
        return "hybrid"
    return "baseline"


def load_leaderboard(exp_root: Path) -> list[dict[str, str]]:
    lb = exp_root / "leaderboard.tsv"
    if not lb.is_file():
        return []
    lines = [l for l in lb.read_text(encoding="utf-8").splitlines() if l.strip()]
    if len(lines) < 2:
        return []
    header = lines[0].split("\t")
    return [dict(zip(header, l.split("\t"))) for l in lines[1:]]


def ensure_punch(exp_root: Path, rows: list[dict[str, str]], *, force: bool) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for r in rows:
        name = str(r.get("name", ""))
        bare = name.replace("_best", "").replace("_last", "")
        run_dir = Path(r.get("run_dir") or "")
        if not run_dir.is_dir():
            continue
        corr = run_dir / "corrected_best"
        punch_path = run_dir / "eval" / f"punch_{bare}_best.json"
        if force or not punch_path.is_file():
            if not corr.is_dir():
                continue
            rc = _run(
                [
                    sys.executable,
                    "scripts/bench_punch_trajectory.py",
                    "--corrected",
                    str(corr),
                    "--label",
                    "best",
                    "--out",
                    str(punch_path),
                ]
            )
            if rc != 0:
                print(f"[finalize] punch failed {bare} rc={rc}", flush=True)
                continue
        if punch_path.is_file():
            out[bare] = json.loads(punch_path.read_text(encoding="utf-8"))
    return out


def write_report(exp_root: Path, punches: dict[str, Any]) -> Path:
    rows = load_leaderboard(exp_root)
    best = [r for r in rows if r.get("ckpt_used") == "best"] or rows
    best = sorted(
        best,
        key=lambda r: (
            -_f(r, "hand_prox_impr_vs_mp"),
            _f(r, "hand_prox_mae_C"),
            _f(r, "test_hard_mm"),
        ),
    )

    baseline = next((r for r in best if _team(str(r.get("name"))) == "baseline"), None)
    base_hard = _f(baseline, "test_hard_mm") if baseline else float("nan")
    base_hands = _f(baseline, "hand_prox_mae_C") if baseline else float("nan")
    base_punch = (
        punches.get(str(baseline.get("name", "")).replace("_best", ""), {}).get("punch_score")
        if baseline
        else None
    )

    # Team scores: best member by hand_prox_impr
    team_best: dict[str, dict] = {}
    for r in best:
        t = _team(str(r.get("name")))
        if t == "baseline":
            continue
        cur = team_best.get(t)
        if cur is None or _f(r, "hand_prox_impr_vs_mp") > _f(cur, "hand_prox_impr_vs_mp"):
            team_best[t] = r

    def vs_base_hard(r: dict) -> str:
        h = _f(r, "test_hard_mm")
        if not (h == h and base_hard == base_hard and base_hard > 0):
            return ""
        pct = 100.0 * (base_hard - h) / base_hard
        return f"{pct:+.2f}%"

    table = [
        "| rank | name | team | hands↓ | vs base hard | test_hard↓ | test_impr% | elbow↓ | punch↑ |",
        "|-----:|------|------|-------:|-------------:|-----------:|-----------:|-------:|-------:|",
    ]
    for i, r in enumerate(best, 1):
        bare = str(r.get("name", "")).replace("_best", "")
        ps = punches.get(bare, {}).get("punch_score")
        ps_s = f"{ps:.4f}" if isinstance(ps, (int, float)) else ""
        table.append(
            f"| {i} | {r.get('name')} | {_team(str(r.get('name')))} | {r.get('hand_prox_mae_C')} | "
            f"{vs_base_hard(r)} | {r.get('test_hard_mm')} | {r.get('test_hard_impr_pct')} | "
            f"{r.get('elbow_mae_C_T')} | {ps_s} |"
        )

    punch_lines = []
    for bare, p in punches.items():
        punch_lines.append(
            f"| {bare} | {p.get('punch_score')} | {p.get('peak_wrist_err_mm_C')} | "
            f"{p.get('timing_err_frames_C')} | {p.get('direction_cos_err_C')} | "
            f"{p.get('return_guard_err_mm_C')} | {p.get('idle_delta_mm')} |"
        )

    # Declare winners
    overall = best[0] if best else None
    gpt_r = team_best.get("gpt")
    me_r = team_best.get("me")
    hybrid_r = team_best.get("hybrid")

    duel = "empate / sem dados"
    if gpt_r and me_r:
        g = _f(gpt_r, "hand_prox_impr_vs_mp")
        m = _f(me_r, "hand_prox_impr_vs_mp")
        if m > g + 1e-6:
            duel = f"**Time me** vence ({me_r.get('name')} impr={me_r.get('hand_prox_impr_vs_mp')} vs GPT {gpt_r.get('hand_prox_impr_vs_mp')})"
        elif g > m + 1e-6:
            duel = f"**Time GPT** vence ({gpt_r.get('name')} impr={gpt_r.get('hand_prox_impr_vs_mp')} vs me {me_r.get('hand_prox_impr_vs_mp')})"
        else:
            duel = "Empate técnico GPT vs me na hand proximity"

    # Punch duel
    punch_duel = ""
    if gpt_r and me_r:
        gp = punches.get(str(gpt_r.get("name", "")).replace("_best", ""), {}).get("punch_score")
        mp = punches.get(str(me_r.get("name", "")).replace("_best", ""), {}).get("punch_score")
        if isinstance(gp, (int, float)) and isinstance(mp, (int, float)):
            if mp > gp:
                punch_duel = f"Punch score: **me** {mp:.4f} > GPT {gp:.4f}"
            elif gp > mp:
                punch_duel = f"Punch score: **GPT** {gp:.4f} > me {mp:.4f}"
            else:
                punch_duel = f"Punch score empatado ({gp:.4f})"

    beats_base = []
    for r in best:
        if _team(str(r.get("name"))) == "baseline":
            continue
        h = _f(r, "test_hard_mm")
        hands = _f(r, "hand_prox_mae_C")
        ok_hard = h == h and base_hard == base_hard and h < base_hard * 0.97
        ok_hands = hands == hands and base_hands == base_hands and hands <= base_hands
        if ok_hard or ok_hands:
            beats_base.append(
                f"- `{r.get('name')}`: hard {vs_base_hard(r)}, hands {hands} (base {base_hands})"
            )

    ckpt = ""
    if overall:
        ckpt = f"`{overall.get('run_dir')}/checkpoints/best_hard.pt`"

    md = f"""# RESULTADOS — competição noturna

Gerado por `ablations/finalize_report.py`  
Pasta: `{exp_root.as_posix()}`

## Veredito rápido

{duel}

{punch_duel}

**Melhor overall (hand proximity / test):** `{overall.get('name') if overall else 'TBD'}`  
Checkpoint: {ckpt or 'TBD'}

Baseline punch_score: {base_punch}

## Ranking completo
{chr(10).join(table)}

## Punch trajectory (jogo)
| name | punch↑ | peak_wrist_mm↓ | timing_frames↓ | dir_err↓ | return_mm↓ | idle_mm↓ |
|------|-------:|---------------:|---------------:|---------:|-----------:|---------:|
{chr(10).join(punch_lines) if punch_lines else "| (vazio) | | | | | | |"}

## Quem bateu o baseline?
{chr(10).join(beats_base) if beats_base else "- Ninguém bateu o baseline com folga (≥3% hard ou hands melhor)."}

## Melhor de cada time
- GPT: `{gpt_r.get('name') if gpt_r else '—'}` hard={gpt_r.get('test_hard_mm') if gpt_r else '—'}
- me: `{me_r.get('name') if me_r else '—'}` hard={me_r.get('test_hard_mm') if me_r else '—'}
- hybrid: `{hybrid_r.get('name') if hybrid_r else '—'}` hard={hybrid_r.get('test_hard_mm') if hybrid_r else '—'}

## Critério go (jogo)
- hard ↓ ≥ 3% vs baseline **e** easy sem regressão > 3% (já gated no treino)
- punch_score ↑ (pico / timing / direção / idle)
- ombros continuam corrigidos

## Próximo passo sugerido
1. Abrir o vencedor no Live viewer
2. Se hybrid ganhou, usar como candidato provisório ao jogo
3. Coletar dados da webcam real antes de crownear modelo final
"""
    out = exp_root / "RESULTS.md"
    out.write_text(md, encoding="utf-8")
    summary = {
        "overall": overall.get("name") if overall else None,
        "duel": duel,
        "punch_duel": punch_duel,
        "n": len(best),
        "results_md": str(out),
    }
    (exp_root / "MORNING_SUMMARY.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--exp-root",
        type=Path,
        default=ABL_ROOT / "competition_20260728",
    )
    ap.add_argument("--force-punch", action="store_true")
    args = ap.parse_args()
    exp_root = args.exp_root if args.exp_root.is_absolute() else LAB_ROOT / args.exp_root
    rows = load_leaderboard(exp_root)
    punches = ensure_punch(exp_root, rows, force=args.force_punch)
    path = write_report(exp_root, punches)
    print(f"[finalize] wrote {path}", flush=True)


if __name__ == "__main__":
    main()
