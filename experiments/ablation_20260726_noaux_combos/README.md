# Ablation wave-2 — noaux combos (2026-07-26)

## Goal
Find promising **w_aux=0** variants beyond the wave-1 winner
`runs/20260726_015055_gru_noaux_v1`. Same primary metric as
`experiments/ablation_20260726/`.

## Primary ranking: hand proximity
`scripts/bench_extended_shoulder_level_hands.py` (test, source fps):
teacher frames with reach ≥ 0.70 + shoulder-level + not hanging.
Score: `hand_prox_mae_C` ↓ / `hand_prox_impr_vs_mp` ↑.

Also: elbow MAE (`bench_arm_angles`), `val_hard_impr_pct`,
**`test_hard_impr_pct`** (`scripts/eval.py --ckpt … --split test`), `easy_ok`.
Leaderboard columns: `test_hard_mm`, `test_mp_hard_mm`, `test_hard_impr_pct`.

## Constraint
All runs in this folder have **`w_aux=0`**. No aux re-enable, no
hand-sep loss, no reach-hinge geo as primary.

## Runs
| name | config | change vs noaux |
|------|--------|-----------------|
| noaux (baseline) | `configs/train_noaux.yaml` | reference |
| noaux_dropaccel | `configs/train_noaux_dropaccel.yaml` | zero accel features |
| noaux_angle | `configs/train_noaux_angle.yaml` | `w_angle=0.2` |
| noaux_wrist2 | `configs/train_noaux_wrist2.yaml` | `wrist_weight=2.0` |
| noaux_gru384 | `configs/train_noaux_gru384.yaml` | `hidden=384` |
| noaux_long | `configs/train_noaux_long.yaml` | epochs=120, patience=25 |

## Eval
```bat
python scripts/run_ablation_eval.py --exp-root experiments/ablation_20260726_noaux_combos --run-dir runs/<id> --name <label> --ckpt both
```

See `leaderboard.tsv` + `CONCLUSIONS.md`.
