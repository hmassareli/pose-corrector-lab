# Dataset, FPS e Features

## 1. Amostra canônica (o que cada sample contém)

Uma **janela causal** no FPS canônico (**30 Hz**):

| Campo | Shape (exemplo) | Descrição |
|-------|-----------------|-----------|
| `clip_id` | str | id do vídeo |
| `person_id` | str | ID local do rastreador no shot; atualmente não representa identidade humana global |
| `t_end` | float | tempo (s) do frame alvo |
| `frame_idx` | int | índice @ 30 Hz do frame alvo |
| `x_seq` | `(T, F)` | features de entrada (MediaPipe) |
| `conf_seq` | `(T, J)` | confiança landmarks |
| `y_delta` | `(18,)` | Δx,Δy,Δz × {L/R shoulder, elbow, wrist} |
| `y_abs_teacher` | `(6, 3)` | pose abs teacher nos 6 targets (debug, quando persistida) |
| `motion_label` | int | pseudo-classe (aux) |
| `difficulty` | float | ‖Δ*‖ ou score hard |
| `fps_src` | float | FPS original do vídeo |

**T padrão = 15** → ~500 ms de história. Sem frames futuros.

### Residual

No **frame do corpo** (origem = midpoint ombros, escala = ‖L_shoulder − R_shoulder‖):

```
Δ* = teacher_joint - mediapipe_joint
```

para shoulders/elbows/wrists. O frame corporal usado para representar e aplicar o residual é calculado a partir dos ombros MediaPipe **antes** da correção. Isso significa que os ombros são simultaneamente referência do frame e targets de saída; manter ombros fixos e prever apenas 12 valores ainda é uma ablação futura, não o comportamento atual.

---

## 2. Solução simples de tempo (obrigatória)

**Um relógio: 30 FPS.**

1. Vídeo / poses teacher / MediaPipe → resample temporal para **30 Hz**
2. Velocidades = `(x_t − x_{t−1}) * 30` (por segundo, nunca “por frame” cru)
3. Na inferência do jogo: buffer da webcam sempre reamostrado para 30 Hz

ShadowPunch a 60 Hz → ficar com frames `0,2,4,...` (ou interpolar linear em joints).

Augmentação posterior (não v1): time-warp ±10–20%, frame-drop + re-interp para 30.

Implementação: `src/pose_lab/timebase.py`.

---

## 3. Normalização espacial (anti-overfit #1)

Por frame, a partir dos ombros MediaPipe (e hips como fallback):

1. `origin = (L_shoulder + R_shoulder) / 2`
2. `scale = ‖L_shoulder − R_shoulder‖` (clamp com hip–hip se colapsar)
3. Eixos aproximados:
   - **X**: ombro L → R
   - **Y**: up do tronco (shoulder_mid → hip_mid, invertido se necessário)
   - **Z**: X × Y (direita)

Tudo em coords relativas, escala 1. Residual previsto **nesse frame**.

Alinhamento teacher↔MP: Procrustes rígido no tronco (ombros+hips) **por sequência**, depois residual nos braços.  
`src/pose_lab/align.py`.

---

## 4. Features (cientista: o mínimo que carrega sinal de manobra)

### 4.1 Estado (pose) — implementação atual

| Feature | Dim | Motivo |
|---------|----:|--------|
| Joints contexto xyz (hips, shoulders, elbows, wrists, neck) | ~27 | base |
| Elbow/wrist no frame do ombro ipsilateral | 12 | jab vs guarda linear |
| Bone lengths shoulder–elbow, elbow–wrist | 4 | falha MP estica osso |
| Ângulo do cotovelo | 2 | extensão |
| Distância shoulder–wrist | 2 | extensão do braço |

### 4.2 Movimento — implementação atual

| Feature | Dim | Motivo |
|---------|----:|--------|
| Velocidade 3D dos 6 targets (/s) | 18 | movimento recente |
| Aceleração 3D dos 6 targets (/s²) | 18 | presente no schema de 113 features, mas zerada no melhor modelo |

Velocidade e aceleração são diferenças finitas com Δt=1/30. A ablação mostrou que a aceleração crua prejudicou: o melhor checkpoint mantém a largura F=113 por compatibilidade, mas zera o bloco de aceleração em treino e inferência (`features.zero_accel: true`).

### 4.3 Qualidade MediaPipe (quando corrigir)

| Feature | Motivo |
|---------|--------|
| Confiança por landmark | gate |
| 1 − conf | peso de loss |
| 2D normalizado dos 4 alvos + ombros | braço na câmera (XY mais confiável que Z; saltos absurdo do MP costumam ser em profundidade — ver losses cinemáticas em `03_training.md`) |

### 4.4 Auxiliar de movimento (pseudo-label)

Classes fracas do teacher (heurística cinemática):

0. `idle_guard`
1. `extend_L` (jab/direto lado esquerdo)
2. `extend_R`
3. `hookish` (vel tangencial alta, cotovelo flexionado)
4. `uppercutish` (componente up)
5. `retract`
6. `other`

A cabeça auxiliar existe na arquitetura/configuração atual, mas o melhor checkpoint usa `w_aux: 0.0`: seus logits são calculados, porém não contribuem para o gradiente da loss. A ablação sem loss auxiliar foi melhor que o baseline com CE.

### 4.5 O que NÃO colocar (v1)

- XYZ world absolutos sem normalizar
- One-hot de vídeo/pessoa
- FPS bruto sem Δt
- Joints de mão detalhados (ruído)
- Features que vazam identidade (bone lengths absolutas em metros sem ratio)

**Tensor implementado:** `F=113` por frame × `T=15`. No melhor modelo, as 18 posições reservadas à aceleração são zeradas sem alterar F.

---

## 5. Construção do dataset

```
data/raw_videos/   →  data/input/
        ↓ run_teacher.py
data/teacher/<clip>/
        ↓ run_mediapipe.py
data/mediapipe/<clip>/
        ↓ pair_poses.py + build_dataset.py
data/paired/<split>/*.npz
data/splits/manifest.json
```

### Manifesto de split desejado

```json
{
  "fps_canonical": 30,
  "window_T": 15,
  "persons": {
    "p001": {"clips": ["shadow_01", "shadow_02"], "split": "train"},
    "p002": {"clips": ["shadow_10"], "split": "val"},
    "p003": {"clips": ["webcam_holdout_01"], "split": "test"}
  }
}
```

Regra desejada: **nenhuma identidade humana nem sessão de captura em dois splits**.

### Split realmente usado em 2026-07-27

- Train: 221 clips/rastros, 91.068 janelas; 203 clips vêm de `burn_500_shots`.
- Val: 30 clips/rastros, 12.790 janelas; todos vêm dos shots finais de `burn_500_shots`.
- Test: 18 clips/rastros, 48.595 janelas; vêm de `intense_10_shadow` e `max_calories_left_half`.
- `person_XXX` é um track local por shot, não uma identidade persistente.

Consequência: o teste separa vídeos-fonte, mas a validação não é um hold-out real de pessoa ou domínio. Contagens de clips e minutos também podem contar simultaneamente vários tracks extraídos do mesmo vídeo; não equivalem a diversidade independente.

### Contagem honesta

Reportar em logs: `#persons`, `#hours`, `#clips` — não só `#windows` (overlap mente).

---

## 6. Augmentações (bone-space)

| Aug | Quando |
|-----|--------|
| Mirror L↔R (+ flip labels) | sempre (ortodoxo/southpaw) |
| Noise ∝ (1−conf) | planejada; não implementada no dataset atual |
| Time warp ±10–20% → regrid 30 Hz | planejada |
| Rotação leve do frame do corpo (±5–10°) | planejada |
| Escala torso ±5% | planejada |

---

## 7. Arquivos de referência no código

- `src/pose_lab/skeleton.py` — joints e bones
- `src/pose_lab/timebase.py` — resample 30 Hz
- `src/pose_lab/features.py` — tensor F
- `src/pose_lab/labels.py` — residual + motion pseudo-labels
- `configs/dataset.yaml` — defaults
