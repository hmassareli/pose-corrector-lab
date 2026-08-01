# NLF-S speed profile

Clip: `burn_500_shots__shot_000__person_009` · frame `646x304` · device `cuda` · `NVIDIA GeForce RTX 3060`

## Latency (CUDA events, ms)

| path | mean | p50 | p95 |
|------|-----:|----:|----:|
| detect_smpl_batched (full) | 142.0 | 141.8 | 145.2 |
| YOLO-x detector only | 26.5 | 26.5 | 26.9 |
| **fast: estimate joints24 full-frame** | **22.3** | **22.3** | **23.1** |
| estimate lab13 full-frame | 23.8 | 23.8 | 25.1 |

30 FPS budget = 33.3 ms · fast_path_p95_ok = **True**

Paper (RTX 3090): NLF-S crop-only 79 FPS unbatched / 410 FPS batched — not full multi+fit.

See `profile.json` for raw numbers.
