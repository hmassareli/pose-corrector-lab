# Teacher: GVHMR

## Por que GVHMR

- Offline, usa imagem + temporal (não é só lift 2D→3D)
- Melhor que MediaPipe em oclusão / profundidade na maioria dos casos de shadowboxing
- Código aberto: https://github.com/zju3dv/GVHMR
- **Não** é para o jogo em tempo real (seq2seq + preprocess pesado)

## Setup (Windows)

```bash
# Dentro do lab
python scripts/setup_gvhmr.py
```

O script:

1. Clona `external/GVHMR` (se não existir)
2. Cria/atualiza `external/gvhmr_env` (conda ou venv — ver flags)
3. Baixa checkpoints conforme README upstream
4. Escreve `configs/gvhmr_local.yaml` com paths absolutos deste lab

Requisitos típicos: **CUDA**, Git, e contas/weights SMPL conforme o README do GVHMR.

### Câmera estática (ShadowPunch)

Muitos clips de shadowboxing têm câmera fixa. Use:

```bash
python scripts/run_teacher.py --input data/input --out data/teacher --static-camera
```

Isso passa `-s` / skip VO ao GVHMR (mais rápido e estável).

## Inferência em lote

```bash
# 1. Copie ou linke vídeos para data/input/
#    Aceitos: .mp4 .mov .avi .mkv .webm

# 2. Rode o teacher
python scripts/run_teacher.py --input data/input --out data/teacher --static-camera

# 3. Cada clip gera:
#    data/teacher/<clip_id>/
#      ├── meta.json           # fps original, n_frames, static_camera, git commit GVHMR
#      ├── smplx_params.npz    # pose/shape/transl (se disponível)
#      ├── joints3d.npy        # (T, J, 3) joints canônicos do lab
#      ├── joints3d_smpl.npy   # joints SMPL brutos (antes do remap)
#      └── preview.mp4         # overlay opcional (se --preview)
```

## Formato `joints3d.npy` (canônico do lab)

Após remap SMPL → joints do lab (ver `src/pose_lab/skeleton.py`):

| Index | Nome |
|------:|------|
| 0 | pelvis |
| 1 | left_hip |
| 2 | right_hip |
| 3 | left_knee |
| 4 | right_knee |
| 5 | left_ankle |
| 6 | right_ankle |
| 7 | spine |
| 8 | left_shoulder |
| 9 | right_shoulder |
| 10 | left_elbow |
| 11 | right_elbow |
| 12 | left_wrist |
| 13 | right_wrist |
| 14 | neck |
| 15 | head |

Unidades: **metros**, espaço da câmera (ou world se VO ligado — `meta.json` declara).

Alvos da corretora: índices **10, 11, 12, 13** (elbows + wrists).

## Visualização

```bash
python scripts/serve_viewer.py --clip shadow_01
# abre http://127.0.0.1:8765
```

Vídeo à esquerda; skeleton 3D do teacher à direita (orbit com drag).

## Troubleshooting

| Sintoma | Ação |
|---------|------|
| OOM GPU | `--batch-preprocess` menor; resolução menor; um vídeo por vez |
| Pose “flutuando” | tente `--static-camera` |
| Braços errados em oclusão forte | marque clip em `data/teacher/<id>/QA_FLAG.txt` e exclua do train hard-label |
| FPS != 30 no vídeo | OK — o builder de dataset resampleia; teacher salva FPS original em `meta.json` |

## QA humana (recomendado)

Depois do batch, abra o viewer e marque:

- `ok` — usar no treino
- `soft` — só easy / peso baixo
- `reject` — descartar

Arquivo: `data/teacher/<clip_id>/qa.json` → `{"status": "ok"|"soft"|"reject", "notes": "..."}`.
