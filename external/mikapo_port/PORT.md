# MiKaPo → Pose Corrector Lab: portabilidade do solver

Clone completo: `external/MiKaPo/` (raiz do workspace).  
Cópia focada (landmarks → ossos 3D): este diretório.

## Status — PORT FEITO (2026-07-31)

| Entrega | Onde |
|---------|------|
| Solver Mixamo FK + witness + One-Euro | `viewer/mikapo_mixamo_solver.js` (servido em `/static/`) |
| Offline viewer | `viewer/index.html` importa o módulo |
| Live viewer | `viewer/live.html` importa o módulo; pe live = ankle→toe |
| Pes Teacher (SMPL foot) | `scripts/export_teacher_feet.py` → `teacher_aligned/<clip>/foot_landmarks.json` |
| Docs | `docs/06_avatar_3d_retargeting.md` |

## Arquivos copiados (referência upstream)

| Arquivo | Papel |
|---------|--------|
| `src/lib/landmarks.ts` | Índices MediaPipe pose (33) + mãos (21) |
| `src/lib/solver.ts` | Core MMD (não usado direto — portado para Mixamo JS) |
| `src/lib/math-utils.ts` | Math de referência |
| `src/lib/filters.ts` | One-Euro de referência |
| `src/lib/face-blendshape-solver.ts` | Face (não portado) |
| `src/lib/pose-worker.ts` | Worker (não portado; live usa PoseLandmarker main thread) |
| `src/lib/vmd.ts` | VMD (MMD-only) |
| `src/components/*` | Wiring de referência |
| `README_UPSTREAM.md` | README do upstream |

## O que foi portado (matemática)

```text
lab joints (+ foot_landmarks opcional)
        |
        v
reset Mixamo rest locals
        |
        v
tronco: across + torso (hips/spine*)
bracos/pernas: FromUnitVectors(dir) + roll witness (filho)
pescoco/ombros: aim
pe: ankle→toe (mesma fonte) | rest se ausente
        |
        v
One-Euro nos quats locais
```

## Diferenças que permanecem

| | MiKaPo | Lab agora |
|--|--------|-----------|
| Rig | MMD/PMX | Mixamo FBX |
| Detecção | Holistic + mãos/face | Pose 33 (+ GRU arms) |
| Dedos/face | sim | não |
| Engine | Reze WebGPU | Three.js |

## Como validar

1. `python scripts/serve_lab.py`
2. Avatar 3D + fonte MediaPipe — braços com crease estável; pe ankle→toe
3. Fonte Teacher aligned — depois de `export_teacher_feet.py`, pe Teacher (não MP)
4. Live `/live` — witness + pe ankle→foot_index

## Hipótese ainda a medir (WIN / spot-check)

> FK + witness vs IK antigo: menos twist errado de antebraço/joelho; `hand_prox` / elbow do export corrected inalterados (retarget é viz).
