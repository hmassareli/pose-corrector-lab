# Pose Corrector Lab — Overview

## Objetivo

Treinar uma rede **bone → bone** que corrige MediaPipe em boxe (punhos/cotovelos), usando **GVHMR** como teacher offline.

```
Webcam / Vídeo
      ↓
  MediaPipe          ← runtime (leve)
      ↓
 Rede corretora      ← o que treinamos (1–2M params, causal, 30 Hz)
      ↓
 Pose corrigida → jogo
```

Teacher (só offline):

```
data/input/*.mp4
      ↓
    GVHMR
      ↓
data/teacher/<clip>/  (SMPL joints + metadados)
```

## Princípios científicos

1. **Split por vídeo/shot**, nunca por frame aleatório. O manifesto atual ainda não garante separação por identidade humana global.
2. **FPS canônico = 30 Hz** (resample no dataset e no buffer de inferência).
3. **Frame do corpo** (ombros) + escala ombro–ombro antes de features.
4. **Residual Δxyz** nos 6 targets atuais: L/R shoulder, elbow e wrist (18 valores). O frame corporal continua sendo calculado a partir dos ombros MediaPipe não corrigidos.
5. **Gate por confiança**: corrigir falhas; não embelezar poses boas.
6. Eval **hard vs easy**; se easy piora, o modelo não está pronto.

## Roadmap do lab

| Fase | Entrega | Pasta / script |
|------|---------|----------------|
| 0 | Estrutura + viewer + docs | (este repo) |
| 1 | GVHMR rodando em `data/input` | `scripts/setup_gvhmr.py`, `run_teacher.py` |
| 2 | MediaPipe batch + alinhamento teacher↔MP | `scripts/run_mediapipe.py`, `pair_poses.py` |
| 3 | Features + janelas 30 Hz | `src/pose_lab/features.py`, `build_dataset.py` |
| 4 | Baseline GRU/TCN + logging | `scripts/train.py`, `runs/` |
| 5 | Eval hard/easy + ablations | `scripts/eval.py`, `docs/04_evaluation.md` |

## Convenções de nomes

- Clip ID = stem do vídeo (`shadow_01.mp4` → `shadow_01`)
- `person_XXX` = ID local do rastreador YOLO dentro de um shot; não deve ser tratado como identidade global da pessoa
- Timestamps sempre em **segundos**; índices de frame sempre relativos ao FPS canônico (30)

## O que NÃO entra neste lab

- Inferência real-time do GVHMR (é teacher offline)
- Código do jogo / retarget VRM (fica no repo pai)
