# Conclusions — noaux combos (wave-2)

## Metric (primary)
Same as wave-1: `scripts/bench_extended_shoulder_level_hands.py`
→ `hand_prox_mae_C` / `hand_prox_impr_vs_mp`.
Diagnostics: elbow MAE, **val** hard, and **test** hard (`scripts/eval.py --split test`).

## Wave-2 results (best ckpts)
| rank | name | hand_prox_mae_C | val_hard | val_impr | test_hard | test_impr | elbow_mae | vs noaux |
|-----:|------|----------------:|---------:|---------:|----------:|----------:|----------:|----------|
| 1 | noaux_dropaccel_best | 0.0772 | 217.5085 | 59.8766 | 194.7699 | 62.5352 | 13.8561 | -0.0080 mae BETTER |
| 2 | noaux_gru384_best | 0.0827 | 239.0326 | 55.9061 | 220.11 | 57.661 | 14.8524 | -0.0025 mae BETTER |
| 3 | noaux_long_best | 0.0827 | 235.3039 | 56.594 | 211.8386 | 59.252 | 15.2901 | -0.0025 mae BETTER |
| 4 | noaux_wrist2_best | 0.0842 | 240.8035 | 55.5794 | 218.5179 | 57.9672 | 14.8672 | -0.0010 mae BETTER |
| 5 | noaux_best | 0.0852 | 238.6056 | 55.9849 | 218.8927 | 57.8951 | 15.7114 | baseline |
| 6 | noaux_angle_best | 0.11 | 309.3387 | 42.9369 | 268.7333 | 48.3081 | 14.516 | +0.0248 mae worse |

## What worked / didn't
- **Baseline noaux**: hand_prox_mae_C=0.0852, val_hard_impr=55.9849%, test_hard_impr=57.8951%, elbow=15.7114.
- **noaux_dropaccel_best** improved hands vs noaux (0.0772 < 0.0852).
- **noaux_gru384_best** improved hands vs noaux (0.0827 < 0.0852).
- **noaux_long_best** improved hands vs noaux (0.0827 < 0.0852).
- **noaux_wrist2_best** improved hands vs noaux (0.0842 < 0.0852).
- **noaux_angle_best** did not beat noaux hands (0.1100 vs 0.0852).

## Viewer ckpt
`C:\Users\Henrique\studies\3d augmented games using mocap\pose_corrector_lab\runs\20260726_092251_gru_noaux_dropaccel_v1/checkpoints/best_hard.pt`
Export: `C:\Users\Henrique\studies\3d augmented games using mocap\pose_corrector_lab\runs\20260726_092251_gru_noaux_dropaccel_v1/corrected_best/`

Folder: `experiments/ablation_20260726_noaux_combos/`
