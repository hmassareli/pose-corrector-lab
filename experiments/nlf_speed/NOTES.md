# NLF-S inference speed — engineering notes

## Pipeline (TorchScript `nlf_s_multi_0.2.2`)

```
RGB → YOLOv8x@640 → warp crop 256² → EffNetV2-S → NLF head (P queries)
    → [optional] smplfitter → joints/verts
```

Paper (RTX 3090): **79 FPS unbatched / 410 FPS batched** = crop-model only, not `detect_smpl_batched`.

## Lab baseline (wrong API for game)

`detect_smpl_batched` = YOLO-x + ~1048 canonical queries (1024 verts + 24 joints) + SMPL fit.

| path (RTX 3060, CUDA events) | mean | p95 |
|------------------------------|-----:|----:|
| full `detect_smpl_batched` | 142.0 | 145.2 |
| YOLO-x only | 26.5 | 26.9 |
| **fast `estimate` joints24 full-frame** | **22.3** | **23.1** |

Source: [`profile.json`](profile.json) / [`PROFILE.md`](PROFILE.md).

## Fast path (game)

`estimate_poses_batched` + **full-frame bbox** + **24 SMPL joint weights** + **`num_aug=1`** + **no fit**.

```bash
python scripts/profile_nlf_inference.py --device cuda
python scripts/compare_nlf_vs_mp_teacher_metrics.py --mode fast --clip-list short --device cuda
```

Helpers: [`scripts/nlf_fast_path.py`](../../scripts/nlf_fast_path.py), sticky bbox [`scripts/nlf_bbox_track.py`](../../scripts/nlf_bbox_track.py).

## Quality (same 3 short clips, in-domain)

| metric | MediaPipe | NLF full (prior) | **NLF fast** |
|--------|----------:|-----------------:|-------------:|
| overall mm | 417.4 | 260.7 | **261.9** |
| hard mm | 565.6 | 390.7 | **393.3** |
| hand_prox | 0.75 | 0.54 | **0.53** |
| elbow ° | 31.9 | 16.6 | **17.5** |
| lean ° | **9.0** | 9.9 | 10.6 |

Fast ≈ full quality; still >> InstantHMR (350/557).

## Go / no-go

| Criterion | Result |
|-----------|--------|
| CUDA p95 < 33.3 ms | **PASS** (23.1 ms) |
| overall/hard vs InstantHMR | **PASS** (261.9 / 393.3) |
| TensorRT | **SKIP** — see [`TRT_DECISION.md`](TRT_DECISION.md) |

Export wall-clock p95 (~35 ms) includes OpenCV decode + H2D/D2H; for the game loop use async decode and the CUDA path above.

## HD cleanup before next model

```
data/nlf_fast/
data/nlf/
data/models/nlf/
experiments/nlf_speed/
experiments/nlf_vs_mp_teacher/
```
