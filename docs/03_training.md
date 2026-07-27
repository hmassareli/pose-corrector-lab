# Treino — formato e protocolo

## Objetivo da rede

```
x_seq: (B, T, F)  MediaPipe features @ 30 Hz, causal
        ↓
   Encoder (GRU ou TCN causal, ~0.5–2M params)
        ↓
   h_t (último passo)
        ├─ head_delta → (B, 18)   Δxyz × 6 joints
        └─ head_motion → (B, C)   aux classes (opcional)
```

Output aplicado:

```
pose_corr[shoulders,elbows,wrists] = pose_mp + R_body @ (Δ * scale)
```

com gate na inferência: se a confiança média dos 6 targets for alta e ‖Δ‖ < ε, Δ = 0. Na prática, esse gate só elimina uma correção que já seria pequena; ele ainda não é um gate aprendido de necessidade de correção.

---

## Config padrão (`configs/train.yaml`)

Ver arquivo. Resumo:


| Item         | Valor v1                                        |
| ------------ | ----------------------------------------------- |
| T            | 15 (~500 ms)                                    |
| FPS          | 30                                              |
| Batch        | 64–128                                          |
| Opt          | AdamW                                           |
| LR           | 3e-4, cosine                                    |
| Weight decay | 1e-2                                            |
| Epochs       | early stop (paciência 15) na val por shots; a val atual não separa identidade global |
| Amp          | bf16/fp16 se GPU ok                             |


---



## Loss realmente implementada

Seja `Δ̂` a predição e `Δ*` o residual teacher−MP no body frame.

1. **Huber** em `Δ̂ − Δ*` nos 6 targets, com pesos por articulação (melhor modelo: shoulder=1.0, elbow=1.0, wrist=1.4).
2. **Peso por confiança:** cada amostra Huber recebe fator `0.5 + (1 − mean_conf_targets)`; baixa confiança pesa mais.
3. **Pass-through:** quando `‖Δ*‖` é pequeno e confiança é alta, penaliza a magnitude de `Δ̂`.
4. **Aux CE:** implementada, mas desligada no melhor modelo (`w_aux=0`).
5. **Reach/angle:** implementadas como opções, mas desligadas no melhor modelo; `w_angle=0.2` piorou a ablação.

Dois nomes de configuração ainda não correspondem ao que a documentação antiga afirmava:

- `w_bone` está presente nos YAMLs, porém **não é lido nem somado** por `total_loss`; não houve loss de comprimento de osso nos treinos registrados.
- `w_smooth` multiplica `mean(Δ̂²)`, uma regularização de magnitude. Ela **não compara frames vizinhos** e não é uma loss temporal.

Nos treinos recentes (`noaux`, `noaux_dropaccel`, `noaux_angle`, `noaux_wrist2`, `noaux_gru384`, `noaux_long` e `WIN` fine-tune), `w_smooth=0.0`. Portanto, nenhum deles treinou com esse termo, mesmo no sentido de regularização de magnitude.

Para o melhor checkpoint, a fórmula efetiva é aproximadamente:

```
L = 1.0 * L_huber_conf + 0.5 * L_passthrough
```

Fórmula mental: *erro no hard é caro; inventar correção no easy é mais caro ainda.*

---

## Possibilidades pós-v1 — ainda não implementadas

Não entram no treino v1 obrigatório. Ideia: a rede continua prevendo só `Δ̂`; depois de

```
pose_corr = pose_mp + R_body @ (Δ̂ * scale)
```

a loss olha a **cinemática do corrigido** (e priors fracos), não só a posição. Derivadas sempre @ 30 Hz no body frame (`timebase.velocity` / `acceleration`), **após** aplicar `Δ̂` — nunca nas vel/acc cruas do MediaPipe como alvo.

### Por que isso importa

- Residual sozinho *pode* cancelar saltos do MP (o teacher quase não teleporta → `Δ*` vira anti-salto).
- Correção parcial ainda deixa fração do salto → pico de velocidade na direção errada.
- Em boxe, muitos saltos absurdo do aluno são **no eixo Z** (profundidade); XY no plano da câmera costuma ser mais estável. O corretor tende a ajudar aí, mas XYZ igual na loss subestima isso.

### Losses candidatas

| Sinal | Loss | Efeito esperado |
|-------|------|-----------------|
| Velocidade | ‖vel(corr) − vel(teacher)‖ nos 6 targets, ou só elbows/wrists | preserva direção/timing do soco |
| Aceleração | ‖acc(corr) − acc(teacher)‖ (Huber, peso menor) | picos de extensão / freada |
| Jerk | ‖jerk(corr)‖ ou vs teacher | mata tremedeira pós-salto do MP |
| Smooth temporal condicional | implementar comparação entre frames corrigidos e aplicar mais no hard | alisa sem atrasar jab no easy |
| Inércia fraca | penalizar acc absurda quando conf baixa e ‖Δ*‖ alto | evita teleporte; **não** é física rígida (massa/torque) |
| Eixo Z | peso maior em Z no hard (ou Huber mais tolerante em XY) | ataca o modo de falha típico do MP |
| Features 2D | já no dataset | rede confia no braço na imagem e desconfia do Z saltitante |

Fórmula mental pós-v1:

```
L = L_pos(Δ̂, Δ*)             # ancora (não remover)
  + λ_v * L_vel(corr, te)     # hard↑
  + λ_a * L_acc(corr, te)     # menor
  + λ_s * L_smooth_temporal(corr) # ainda precisa ser implementada
  + gate / pass-through
```

### Ordem sugerida de ablação

1. `L_vel` com peso maior no hard (`w ∝ 1−conf` ou ‖Δ*‖)
2. `L_acc` leve
3. peso extra em **Z** do residual / do `pose_corr`
4. só então priors de “inércia” (ex.: constância curta só em `idle_guard` / baixa vel do teacher — **nunca** durante extensão de jab)

### Cuidados

- Não substituir `L_pos` por só vel/acc → drift / pose errada estável.
- `λ_v`, `λ_a` altos no easy viram borracha e atrasam soco bom.
- Body frame ≠ câmera: o “salto em Z” do viewer pode misturar eixos após o align — validar no QA hard.
- Gate: MP às vezes mantém **conf alta com Z errado**; pass-through agressivo atrapalha nesse caso.
- Eval além de MPJPE: erro de **direção da velocidade do punho**, timing do pico e jitter no hard. `jitter_energy` existe em `metrics.py`, mas o `eval.py` usado nos relatórios atuais não o inclui no JSON final.

### O que não fazer (por enquanto)

- Simulador físico completo (massa, contato, torque) no loop de treino
- Prever velocidade como output principal em vez de residual
- Low-pass cego no runtime (mata onset de soco)

---

## Currículo

1. **Warmup (2–5 epochs):** samplear janelas com ‖Δ*‖ alto (hard)
2. **Mix:** 50/50 hard/easy
3. **Fine-tune domínio (opcional):** poucos minutos da webcam do jogo, LR baixo

---



## Anti-overfit checklist (treino)

- [ ] Split por identidade humana e sessão reais (não pelo `person_XXX` local do YOLO)
- [ ] Modelo ≤ 2M params no v1
- [ ] Early stop em métrica val **hard MPJPE** + constraint easy
- [ ] Mirror aug ligada
- [ ] Sem leak de frames do mesmo vídeo em train e val
- [ ] Seed fixo + log de `git_hash` + `config` em cada run

---



## Logging (pré-pronto)

Cada run em `runs/<run_id>/`:

```
runs/20260324_153012_tcn_v1/
├── config.yaml          # snapshot
├── metrics.jsonl        # uma linha por epoch
├── scalars/             # TensorBoard ou CSV
├── checkpoints/
│   ├── last.pt
│   └── best_hard.pt     # melhor hard MPJPE val
├── eval/
│   ├── val_epoch_XX.json
│   └── plots/
└── system.json          # GPU, torch, seed, dataset hash
```



### `metrics.jsonl` (schema)

```json
{
  "epoch": 12,
  "train/loss": 0.041,
  "train/loss_delta": 0.033,
  "train/loss_aux": 0.008,
  "val/mpjpe_hard_mm": 38.2,
  "val/mpjpe_easy_mm": 12.1,
  "val/mpjpe_overall_mm": 21.4,
  "val/bone_len_std": 0.012,
  "val/jitter_energy": 0.004,
  "val/overcorrect_rate": 0.06,
  "lr": 0.00021
}
```

Ferramentas: TensorBoard (`scripts/train.py` escreve), e `scripts/report_run.py` gera tabela Markdown.

Implementação: `src/pose_lab/logging_utils.py`.

---



## Comando

```bash
python scripts/train.py --config configs/train.yaml
```

Dry-run (1 batch):

```bash
python scripts/train.py --config configs/train.yaml --debug-one-batch
```

