# Ablation competition — punch corrector

Duelo de configs sobre o baseline `noaux_dropaccel` (GRU 256, sem accel, sem aux).

## Times

| ID | Time | Mudanças |
|----|------|----------|
| `baseline_dropaccel` | ref | checkpoint existente (só eval) |
| `gpt_multilag` | GPT | accel → deslocamentos multi-lag 1/3/6 |
| `gpt_seq_vel` | GPT | saída em todos os frames + `L_vel` |
| `gpt_seq_vel_dir` | GPT | seq + `L_vel` + direção em golpes ativos |
| `me_seq_vel_z` | me | seq + `L_vel` + peso extra em Z |
| `me_seq_vel_z_bone` | me | seq + `L_vel` + Z + `w_bone_len` |

Ombros continuam sendo corrigidos (18-D) em todas as variantes.

## Como rodar

```bash
# 1) (uma vez) adicionar y_seq aos NPZs — necessário para seq/vel/dir
python scripts/augment_npz_yseq.py --splits train val

# 2) competição completa (treino sequencial + benches)
python ablations/run_competition.py

# subset / retomar
python ablations/run_competition.py --only gpt_multilag me_seq_vel_z
python ablations/run_competition.py --from-name gpt_seq_vel
python ablations/run_competition.py --eval-only
python ablations/run_competition.py --conclusions-only
```

## Métricas (objetivo do jogo)

Ordem de ranking no leaderboard:

1. `hand_prox_impr_vs_mp` (mãos em frames estendidos) — primária histórica
2. `test_hard_mm` / melhoria vs MediaPipe
3. Punch bench: pico do punho, timing, direção, idle safety, jitter
4. Easy regression ≤ 3% (hard constraint no treino)

Artefatos: `ablations/competition_*/leaderboard.tsv`, `CONCLUSIONS.md`, `punch_bench.json`.

## Fase 2: replicação, losses calibradas e arquitetura

Esta bateria parte dos resultados da primeira competição e mantém uma pergunta por experimento:

| Grupo | Experimentos | Pergunta |
|---|---|---|
| `replication` | baseline e multi-lag nas seeds 42/1337/2026 | O ganho de multi-lag sobrevive à aleatoriedade? |
| `temporal` | sequência isolada; `w_vel` 0.003/0.005/0.01; direção 0.005 | A loss temporal ajuda quando não domina a posição? |
| `architecture` | multi-lag separado; hidden 192; uma camada; T=9/24 | Representação, largura, profundidade ou contexto ajudam? |

O modo `sequence_position_mode: last` supervisiona posição apenas no último frame, como na inferência real, mas permite que velocidade e direção usem a sequência completa.

O multi-lag separado preserva os deslocamentos 1/3/6 em canais próprios (`F=149`), em vez de reduzi-los por média (`F=113`).

Planejar sem treinar:

```bash
python ablations/run_phase2.py --plan
python ablations/run_phase2.py --group temporal --plan
```

Executar por grupo, retomando automaticamente entradas concluídas:

```bash
python ablations/run_phase2.py --group replication
python ablations/run_phase2.py --group temporal
python ablations/run_phase2.py --group architecture
```

Executar entradas específicas:

```bash
python ablations/run_phase2.py --only multilag_separate arch_hidden192
```

Os contextos T=9 e T=24 são construídos em `data/datasets/T9` e `data/datasets/T24`. O dataset baseline em `data/dataset` não é sobrescrito.

### Fora desta fase

A saída sem ombros muda o contrato do modelo de 18 para 12 números. Ela precisa de uma migração conjunta de loss, métricas, exportação e Live; portanto, não foi representada por um YAML que o pipeline atual não conseguiria avaliar corretamente.
