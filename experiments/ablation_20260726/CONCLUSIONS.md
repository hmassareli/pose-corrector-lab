# Conclusions (2026-07-26)

## Metric (primary)
`scripts/bench_extended_shoulder_level_hands.py`

Teacher-only frames where an arm has:
1. reach ≥ 0.70
2. `|wrist_y−shoulder_y|/shoulder_width ≤ 0.55` (body frame)
3. not hanging: `u_y ≥ −0.35` and `hypot(u_x,u_z) ≥ 0.55`

Primary score: mean `0.5*(‖wL−T‖+‖wR−T‖)` → `hand_prox_mae_C` (↓) /
`hand_prox_impr_vs_mp` (↑). Leaderboard sorted by impr then mae.

## Top results
| rank | name | hand_prox_mae_C | hard_mm | hard_impr | elbow_mae |
|-----:|------|----------------:|--------:|----------:|----------:|
| 1 | **noaux** best/last | **0.085** | **239** | **56%** | **15.7** |
| 2 | dropaccel best | 0.112 | 311 | 43% | 19.0 |
| 3 | residual_reach 001626 best | 0.126 | 392 | 28% | 19.1 |
| 4 | clean best | 0.128 | 380 | 30% | 19.9 |
| … | angle best | 0.135 | 404 | 26% | 18.1 |

## What worked / didn't
- **`w_aux=0` (noaux)** — best hands + best hard + best elbow. Aux motion loss was hurting.
- **Zero accel** — strong #2; accel features look noisy/harmful.
- **CLEAN** beats angle on hands/hard; angle helps elbow a bit vs clean but not enough.
- **Angle L1** alone is not the win vs residual on this hand metric.
- **gru384 / wrist2 / drop2d** — marginal vs clean; none beat noaux/dropaccel.
- Fluffy jab `game_score` rejected; use hand proximity instead.

## Viewer ckpt
`runs/20260726_015055_gru_noaux_v1/checkpoints/best_hard.pt`  
Export: `runs/20260726_015055_gru_noaux_v1/corrected_best/`

Folder: `experiments/ablation_20260726/`
