# Avaliação e logging

## Princípio

**MPJPE médio sozinho mente.** Sempre reportar:

| Métrica | Definição | Passa se… |
|---------|-----------|-----------|
| `mpjpe_hard` | erro nos 6 targets onde a norma média de ‖Δ*‖ ≥ P80 **ou** confiança média < 0.5 | ↓ vs MediaPipe baseline |
| `mpjpe_easy` | complemento do hard | **não piora** > 3% vs MP |
| `mpjpe_wrist` / `mpjpe_elbow` | por grupo | hard melhora |
| `bone_len_mae` | desvio dos comprimentos após correção | ≤ baseline ou melhor |
| `jitter` | energia de aceleração do pose corrigido | função disponível, mas ainda ausente dos relatórios principais atuais |
| `overcorrect_rate` | fração easy com ‖Δ̂‖ > τ e ‖Δ*‖ < τ₀ | baixo (< 10%) |
| `latency_ms` | só rede corretora @ T=15 | orçamento do jogo (ex. < 5–8 ms) |

Unidades: mm no espaço métrico após desfazer escala do body frame (usar scale médio ombro–ombro × metros do teacher).

---

## Protocolos de eval

### A. Offline paired (hold-out de vídeos atual)

```bash
python scripts/eval.py --ckpt runs/.../best_hard.pt --split test
```

Gera `runs/.../eval/test_best_hard.json` (ou tag equivalente). Os plots/per-person descritos abaixo são o formato desejado, não uma garantia do `eval.py` atual.

### B. Cross-FPS stress

Resample input MP para 20 / 30 / 60 → forçar pipeline a 30 → medir hard/easy.  
Se 20 ou 60 quebrar e 30 ok → bug de timebase.

### C. Webcam hold-out (necessário antes do modelo final)

Clips gravados na setup real do jogo, com pessoas e sessões ausentes de train/val. Ainda não existe um conjunto amplo com essa garantia; prioridade máxima de go/no-go.

### D. Ablations (obrigatório antes de celebrar)

| Ablation | Expectativa |
|----------|-------------|
| sem vel/acc | hard piora |
| sem conf | overcorrect sobe |
| sem aux motion | já executada: melhorou; o melhor modelo usa `w_aux=0` |
| sem aceleração | já executada: foi a melhor ablação; `zero_accel=true` |
| janela T=5 vs 15 vs 30 | U-shape; reportar |
| só Δz vs Δxyz | Δxyz deve ganhar no braço-na-câmera |

---

## Baseline obrigatório

Sempre comparar com:

1. **Identity** — MediaPipe cru (Δ=0)
2. **EMA** — suavização exponencial nos joints (não é correção semântica)
3. **Nosso modelo**

Tabela no relatório:

```
method | hard | easy | wrist_hard | overcorrect | jitter
MP     |  ... |  ... | ...        | 0           | ...
EMA    |  ... |  ... | ...        | 0           | ...
Ours   |  ... |  ... | ...        | ...         | ...
```

---

## Critério de “go” (v1)

- `mpjpe_hard` ↓ ≥ **15%** vs MediaPipe no teste por vídeo; para release, repetir em pessoas/sessões reais não vistas
- `mpjpe_easy` não piora > **3%**
- `overcorrect_rate` < **0.10**
- Viewer: 10 clips QA sem “soco fantasma” óbvio em idle

---

## Logging de eval desejado

O contrato desejado é:

```
eval/
├── summary.json
├── per_clip.csv
├── per_person.csv
├── hard_mask_stats.json
└── plots/
    ├── hard_vs_easy.png
    ├── residual_hist.png
    └── jitter_curve.png
```

Integração TensorBoard: histograma de ‖Δ̂‖ em easy vs hard.

Estado atual: `scripts/eval.py` grava um resumo agregado JSON. Os relatórios `per_clip.csv`, `per_person.csv`, máscaras, plots, baseline EMA e histograma ainda não fazem parte da saída principal implementada.

## Evidência atual (2026-07-27)

O melhor checkpoint geral é `20260726_092251_gru_noaux_dropaccel_v1/best_hard`:

- Test hard: 194,77 mm vs 519,88 mm do MediaPipe (62,54% melhor).
- Test easy: 150,83 mm vs 296,80 mm do MediaPipe.
- Test overall: 159,83 mm vs 342,47 mm do MediaPipe.
- Melhor época: 69; treino total: 1.423 s (~23,7 min); 0,753M parâmetros.

O fine-tuning WIN não substitui esse checkpoint: melhorou o clip WIN presente no treino, mas no teste oficial passou de 194,77 para 196,28 mm hard e de 150,83 para 157,55 mm easy.

---

## Visual QA

```bash
python scripts/serve_viewer.py --clip <id> --source teacher
python scripts/serve_viewer.py --clip <id> --source mediapipe
python scripts/serve_viewer.py --clip <id> --source corrected --ckpt runs/.../best_hard.pt
```

Comparar lado a lado mentalmente: vídeo | bones. Marcar `qa.json` no teacher quando GT estiver duvidoso.
