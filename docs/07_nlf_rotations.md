# NLF-S: rotações SMPL no output completo

Probe: `scripts/probe_nlf_rotations.py` (introspecção) + `scripts/probe_nlf_rotations_fit.py` (fit na sequência de benchmark). Resultados em `experiments/nlf_rotations_probe/report.json` e `experiments/nlf_rotations_fit/report.json`.

## O que o modelo expõe

`detect_smpl_batched` (API completa: YOLOv8x + 1048 queries + fit) retorna o **fit SMPL completo**:

| Chave | Shape | Conteúdo |
|---|---|---|
| `pose` | (B, 72) | axis-angle por osso: `global_orient(3)` + 23 juntas de corpo (69) |
| `betas` | (B, 10) | shape params (identidade) |
| `trans` | (B, 3) | translação da raiz |
| `joints3d` / `joints2d` | (B, 24, 3/2) | juntas do fit |
| `vertices3d` / `vertices2d` | (B, 6890, 3/2) | mesh SMPL completo |
| `*_nonparam` | — | versões não-fit (queries canônicas) |
| `joint_uncertainties` / `vertex_uncertainties` | — | incerteza |

O fast path (`estimate_poses_batched`) retorna **somente** `poses3d` / `poses2d` / `uncertainties` — sem rotações, sem shape, sem mesh.

## Sinal validado na sequência de boxe (13 frames benchmark)

- Norma de rotação média por junta (graus): cotovelos **165°/120°** (guarda + extensão), ombros ~59°, `spine1` ~48° (inclinação de tronco), punhos ~29°, mãos **75–98°** (pronação/rotação do punho). Sinal real e diferenciado por junta.
- `betas` estável entre frames (std ~0.11) → identidade consistente.
- `trans` varia pouco (mm) → câmera estática, coerente.

## Custo (RTX 3060, torch, 960×540) — medido por estágio

Medição isolada por estágio (`measure_fit_head_cost.py`, mesmo frame + box do detector, sem YOLO):

| Estágio | p50 ms |
|---|---|
| Nonparam 24 juntas (`_estimate_poses_batched`, weights24) | 23.6 |
| Nonparam dense 1079 pts (x55+surface1024) | 26.8 |
| **Parametric (dense + fit)** `_estimate_parametric_batched` | **124.2** |
| **Fit head puro (parametric − dense)** | **~97.4** |
| Detector YOLOv8x (`detector.forward`) | ~25 |
| Full `detect_smpl_batched` (det + fit) | ~134–170 |

Conclusões importantes:

1. **O custo do fit head é ~97 ms em torch — não é poucos ms.** O fit (SMPL forward + refinamento/otimização com `beta_regularizer`) domina o custo de rotações. Sozinho ele estoura o orçamento de 30 fps (33 ms).
2. **A query densa é barata**: 24 → 1079 pontos custa só ~3 ms. O gargalo não é o número de pontos consultados, é o fit.
3. Acelerar o fit head com engines (TRT/DML) é incerto: o fit tem estrutura de otimização/iteração (control flow), que engines exportam mal — diferente das features (exp10/14 funcionaram).
4. `_estimate_parametric_batched` com `model_name='smpl'` + box do detector reproduz o fit do `detect_smpl_batched` (pose/betas/trans batem a ~0.7/0.2/0.05).
5. **Caminho realista para rotações a 30 Hz**: usar o fit OFFLINE como teacher de rotações (custo zero no runtime) e treinar o corretor/head de twist com esse GT — ou rodar o fit em frequência reduzida. Fit completo por frame no runtime não cabe no orçamento.

## Convenções

- `joints3d` (fitted) vs `poses3d` (fast) não compartilham espaço: offset Z ~242 mm + ~53 mm residual após centrar. Antes de usar fitted joints/vertices como fonte do avatar, alinhar convenções (raiz/trans, escala, flip YZ).
- `pose[3k:3k+3]` = axis-angle da junta k na ordem `SMPL24_NAMES` (ver `probe_nlf_rotations_fit.py`).

## Próximos passos

1. **Fit offline como teacher de rotações** (custo zero no runtime): rodar `_estimate_parametric_batched`/`detect_smpl_batched` nos clips e salvar pose/betas/trans por frame como GT — a base para treinar o head de twist do corretor ou dirigir o avatar por rotações.
2. Medir se o fit é amortizável (init temporal entre frames, frequência reduzida, crop menor) — o custo de ~97 ms é por frame único; com init do frame anterior pode cair.
3. Sondar export do fit para engine (TRT/DML) — incerto por causa do control flow da otimização; só faz sentido depois do item 2.
4. Alinhar o espaço fitted (joints/vertices) com a convenção do viewer antes de qualquer retarget.
5. Pontos de superfície como roll witnesses continuam sendo a alternativa barata de twist sem fit completo.
