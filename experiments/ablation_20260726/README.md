# Ablation campaign — 2026-07-26

## Goal
Corrector should put hands closer to the teacher than raw MediaPipe on
**extended, shoulder-level** arms — without stretch hacks — while keeping
val hard MPJPE (`easy_ok`) and idle not ruined.

## Primary ranking: hand proximity (game-relevant)
From `scripts/bench_extended_shoulder_level_hands.py` (test split, source fps).

**Teacher-only frame selection** (per arm; both sides can qualify):
1. Reach ≥ **0.70**: `||w−sh|| / (||sh−el|| + ||el−w||)`
2. Wrist near shoulder height (teacher body frame):  
   `|wrist_y − shoulder_y| / shoulder_width ≤ 0.55`
3. Not hanging: unit(wrist−shoulder) has `u_y ≥ −0.35` and `hypot(u_x,u_z) ≥ 0.55`

**Metric on those frames only:**
- Primary: `hand_prox_mae_C` = mean of `0.5*(||wL_C−wL_T|| + ||wR_C−wR_T||)`  
  vs same for MP → `hand_prox_impr_vs_mp = (mae_MP − mae_C) / mae_MP`
- Also: `% frames` with err_C < err_MP; separation MAE (secondary)

Leaderboard sorted by `hand_prox_impr_vs_mp` ↓, then `hand_prox_mae_C` ↑, then elbow MAE ↑.

Diagnostics: `elbow_mae_C_T`, `val_hard_impr_pct`. Extension bench is context only.

~~Removed~~ vague composite `game_score` / jab assumptions (`bench_game_boxing.py` is obsolete for ranking).

## Do / don't
- OK: residual + elbow angle L1, feature/arch ablations, `w_smooth=0`
- NOT: reach-ratio hinge as primary geo loss; hand-separation *loss*; delete old good runs

## Re-measure
```bat
python scripts/run_ablation_eval.py --run-dir runs/<id> --name <label> --ckpt both --reset-leaderboard
```
Also records **test** hard MPJPE via `scripts/eval.py --split test`
(`test_hard_mm`, `test_mp_hard_mm`, `test_hard_impr_pct`).

## Campaign status
See `leaderboard.tsv` + `CONCLUSIONS.md`. Wave-1 winner: **noaux** (`w_aux=0`).
Wave-2 noaux combos: `experiments/ablation_20260726_noaux_combos/`.

## Paths
- Bench: `scripts/bench_extended_shoulder_level_hands.py`
- Eval driver: `scripts/run_ablation_eval.py`
- Deprecated ranking: `scripts/bench_game_boxing.py` (not used for leaderboard)
