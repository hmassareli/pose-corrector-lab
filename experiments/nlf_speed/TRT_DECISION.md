# TensorRT decision (NLF-S fast path)

## Measurements (RTX 3060)

| Method | mean | p95 | Under 33.3 ms? |
|--------|-----:|----:|:---------------|
| CUDA events `estimate_joints24` ([profile.json](profile.json)) | 22.3 | **23.1** | **YES** |
| Export wall-clock (includes OpenCV decode + H2D + D2H) | 29.5 | 34.8 | borderline / no |

## Decision

**Skip TensorRT for now.**

Reasons:
1. Pure GPU pose path already meets the 30 FPS budget (CUDA p95 ≈ 23 ms).
2. `torch_tensorrt` / `tensorrt` are **not installed** in this env; pulling them is a large deps hit for a ~10 ms export-side gap dominated by CPU decode/sync.
3. Quality of fast path ≈ full `detect_smpl_batched` (overall 261.9 vs 260.7; hard 393.3 vs 390.7).

## If wall-clock p95 must be <33 ms in the game loop

1. Async pipeline: decode thread → pinned H2D → NLF → D2H / game thread.
2. Optional: install TensorRT + `torch-tensorrt`, export `crop_model` FP16 (see stub below).
3. Light detector/track already available: [`scripts/nlf_bbox_track.py`](../../scripts/nlf_bbox_track.py) (sticky IoU; avoid YOLO-x every frame).

## TensorRT stub (when packages exist)

```bash
pip install torch-tensorrt tensorrt
python scripts/try_nlf_tensorrt.py --model data/models/nlf/nlf_s_multi_0.2.2.torchscript
```
