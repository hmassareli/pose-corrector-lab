# NLF-S vs MediaPipe — Teacher residual panel

NLF-S multi 0.2.2 · `joints3d_nonparam` · axis=`identity` · stride=2 · clips=3

| metric | MediaPipe | NLF-S | NLF better % | winner |
|--------|----------:|------:|-------------:|:-------|
| mpjpe_overall_mm | 417.446 | 260.729 | +37.5% | NLF |
| mpjpe_hard_mm | 565.618 | 390.706 | +30.9% | NLF |
| mpjpe_easy_mm | 379.867 | 227.768 | +40.0% | NLF |
| hand_prox_body | 0.746 | 0.536 | +28.1% | NLF |
| elbow_mae_deg | 31.857 | 16.557 | +48.0% | NLF |
| lean_legs_mean | 9.022 | 9.909 | -9.8% | MediaPipe |

## vs prior shortlist (same clips, from earlier runs)

| model | overall | hard |
|-------|--------:|-----:|
| MediaPipe | 417.4 | 565.6 |
| NLF-S | 260.7 | 390.7 |
| InstantHMR (prior) | 350.1 | 557.1 |
| HybrIK (prior) | 387.2 | 610.0 |

## Per-joint

| joint | MP | NLF | better% | winner |
|-------|---:|----:|-------:|:-------|
| left_shoulder | 0.2823 | 0.1904 | +32.6% | NLF |
| right_shoulder | 0.2310 | 0.1869 | +19.1% | NLF |
| left_elbow | 0.4903 | 0.2980 | +39.2% | NLF |
| right_elbow | 0.4963 | 0.2595 | +47.7% | NLF |
| left_wrist | 0.4774 | 0.3580 | +25.0% | NLF |
| right_wrist | 0.5275 | 0.2717 | +48.5% | NLF |

## CLEANUP (pouco HD) — apagar ANTES do proximo teste

```
data/nlf/
data/models/nlf/                 # ~298MB torchscript
experiments/nlf_vs_mp_teacher/
```

