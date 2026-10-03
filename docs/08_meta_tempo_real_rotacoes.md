# 08 — META: Boxe em tempo real com rotações realistas

> **Status:** documento de meta e pesquisa. Nada aqui é implementação nova — é o mapa de
> soluções, o que já foi medido/esclarecido, e o plano de auto-avaliação. A implementação
> só acontece depois do OK explícito.
> Última atualização: 2026-08-16 (baker top **v4** — ver §3.6: o diagnóstico do v3
> estava errado e a verificação dele era circular; palma agora a ~8° do mesh, medido
> sem calibração).

---

## 1. Objetivo

O jogo de boxe em tempo real (online) precisa de posturas/poses **o mais realistas possível**.

O caminho atual — versão limitada, **só esqueleto, sem o fit** — não funciona bem:
- É difícil inferir **rotações**: ombros, cotovelos, **pronação** (giro do antebraço/punho), torção.
- Fica "bom no geral", mas **não dá sensação de realismo**.
- O **braço é o maior problema**: o soco varia muito o **giro do braço** (roll), e o esqueleto
  por pontos não carrega esse sinal (ângulo derivado de vetores curtos e ruidosos = ruído).

**Meta concreta:** um pipeline end-to-end com rotações de verdade, rápido o suficiente para
GPUs fracas de diferentes PCs (e, onde possível, CPU), com auto-avaliação embutida.

---

## 2. Preocupações do autor (transcritas)

1. **Custo do fit com rotações**: se for caro/demorado E não houver jeito de otimizar por
   engenharia até ficar "top", talvez seja preciso:
   - simplificar/leve o modelo, **ou**
   - criar uma **rede que alcance o mesmo resultado de rotações** no lugar do algoritmo atual
     (que é lento).
   - Observação: o **fast path** já parece ótimo; o problema é a **parte do fit**.
2. **Auto-avaliação**: conseguir formas de se auto-avaliar — confirmar end-to-end rápido o
   suficiente para **GPUs menos potentes de vários tipos de PC**.
3. **CPU**: em alguns casos (não obrigatório), ter versão para CPU.
4. **Insights gerais de otimização do pipeline**: o atual (sem pronações/rotações) **não serve
   muito, porque a mão é muito importante**.

---

## 3. Estado atual — o que já foi medido e esclarecido

### 3.1 O modelo NLF-S expõe o fit completo (sempre teve)

`detect_smpl_batched` devolve o **fit SMPL-X inteiro**: `pose` (165 dims = rotações axis-angle
por osso, incl. mãos), `betas` (shape), `trans`, `joints3d` (55), `vertices3d` (10475, mesh com
dedos). O fast path (`estimate_poses_batched`) devolve **só juntas** — as rotações estavam lá,
só não eram lidas.

### 3.2 Custos medidos (RTX 3060, torch, 960×540, p50)

| Estágio | ms |
|---|---|
| Fast path 24 juntas (o que o jogo usa hoje) | ~24 |
| Dense 1079 pontos (x55 + superfície) | ~27 |
| Fit completo (dense + fit) | ~124 |
| **Fit head puro** | **~97** |
| Detector YOLOv8x | ~25 |

- **Query densa é barata**: +1055 pontos custam só ~3ms → o gargalo **não** é o número de juntas/pontos.
- O fit é um **otimizador iterativo** (alinhamento global + laço de refinamento, 3 iterações,
  regularizador) → caro por natureza.
- Orçamento: 30fps = 33ms; 60fps = 16.7ms. **O fit cru (97ms) não cabe.**

### 3.3 Onde a rotação aparece / não aparece (medido)

- **x55 rápido (dedos)**: o across index↔pinky (a seta magenta do viewer) é **ruído puro para
  roll** — pula 66–87°/frame (máx 169°). Span estável (~50mm), mas ângulo de vetor curto ruidoso = ruído.
- **Fit (rotações)**: suave — roll do punho pula só 10–12°/frame (máx 26°), rotação total do
  punho 18–49°. O otimizador com priors estabiliza.
- **Punho do SMPL-24 é uma "luva" rígida** (sem dedos) → nunca vai mostrar rotação de verdade.
- Os **dedos do SMPL-X (fit)** carregam o sinal, mas **ainda não foram validados contra a realidade**.
- `fit_joints` e `x55` estão no **mesmo espaço** (mm, y-down, mesma ordem de 55 juntas;
  residual ~37mm após centrar na pelve) → **sem alinhamento** para usar o fit como fonte do bake.

### 3.4 O baker top (retarget por rotações) — v1 QUEBROU, v2 corpo OK, v4 palma = mesh (CORRIGIDO)

- **v1 (frame completo) era bugado**: o GLB do boxeador **não está em T-pose**, então transferir o
  frame completo (`restQuat * q`) como delta sobre o rest do avatar torceu o corpo — joelho no
  peito, ombros invertidos, pés pro alto (screenshot do autor).
- **v2**: a **direção** de cada osso vem SEMPRE das posições do fit (corpo nunca inverte —
  sanidade automática em `scripts/check_bake_sanity.py`: pés plantados, joelhos abaixo do
  quadril, ombros acima, cabeça acima). Só o roll local do punho vinha das rotações → mão ainda
  LATERAL no soco (autor reportou em t≈16s).
- **v3 tinha DIAGNÓSTICO ERRADO e validação CIRCULAR** (não repetir): culpou o **fade do across**
  (`ACROSS_FADE_LO=0.12m` > span dos dedos ~0.06m) e inventou o "span sintético de 0.6m" — mas
  `computeHandPalmAxes` **normaliza o across**, então 0.06m e 0.6m dão o MESMO vetor: o fix era um
  **no-op**. E o check "7.6°/7.4°" reconstruía o across do avatar a partir de `rest.restAcrossInRoot`
  (o vetor que o solver acabava de alinhar) → passava por construção com a mão errada.
- **Causa raiz real (v4)**: o rest across da mão/antebraço era `boneDir × up` (suposição T-pose
  palma pra baixo), mas o GLB é **A-pose** → referência **41° (esq) / 35° (dir)** fora do plano
  real da palma, e o antebraço (que recebe o across da palma) usava um eixo ~25° diferente do da
  mão. **Fix**: `deriveRestPalmAcross` no solver — o across da palma é o **eixo de flexão dos
  dedos**: ajusta um plano à [mão + cadeia de dedo] por dedo (bem condicionado mesmo com cadeia
  quase colinear), ancora o sinal no heurístico antigo, e aplica o MESMO across em mão e antebraço.
  PCA da malha da luva NÃO funciona (mitene quase isotrópica 6.57/6.12/4.22 → inverteu a mão esq.
  180°).
- **Validação v4 (não-circular)**: erro absoluto de palma vs mesh do fit **133°/50° → 8.3°/8.4°**
  (264 frames, `scripts/absolute_palm_error.py`); tracking vs fit via quaternion de osso em espaço
  mundo (`scripts/check_palm_fidelity.py`, nunca toca `restAcrossInRoot`); no soco a palma-Y do
  avatar bate com o mesh (fit −0.47 vs avatar −0.47). Close-ups em `experiments/palm_compare/v4_top/`.
- Render: `experiments/bake_top/henrique_webcam_1_bake_top_vs_fit.mp4` (528f@30fps, câmera
  lateral): esquerda = BAKER TOP v4 (palma do fit), direita = FIT JOINTS (dedos observados).
- **Custo do retarget em runtime: ~sub-ms a 1ms (JS)** — o retarget não é o gargalo.

### 3.5 Esclarecimentos já dados (respostas às perguntas desta jornada)

- **"O pipeline vai ficar mais lento com rotações?"** → Não necessariamente. Três rotas mantêm
  o custo: (1) fit offline como teacher (custo zero no runtime), (2) fit amortizado (init
  temporal / subsampling), (3) destilação (head barato prevê rotações das features já calculadas).
  Só o jeito ingênuo (fit completo por frame ao vivo) é inviável.
- **"Por que os autores não fizeram um head barato?"** → O barato deles é o fast path (pontos).
  Pontos não carregam rotação; para rotação eles usam um otimizador iterativo (precisão de
  benchmark, não de jogo). O que falta é **destilação** — ensinar um MLP a imitar o otimizador —
  que é exatamente o plano deste lab.
- **"Os pontos servem como feature de MLP?"** → Sim (o fitter é a prova viva: otimiza rotações
  contra os pontos ponderados pela confiança). Mas para rotação use **dedos x55 + antebraço/
  ombro** como entrada (e a incerteza por ponto como bônus), não o punho da luva.
- **"O viewer está errado?"** → Não. As setas se movem conforme o dado: ruidosas porque o
  sinal de roll não existe no caminho rápido.
- **"Baker top precisa de calibração?"** → Não, se o design for delta no eixo do osso (feito).
  Sobra só um bias constante de rest, mensurável.
- **Teacher (GVHMR)**: `run_teacher.py` descarta `pred_smpl_params`; os dumps brutos foram
  limpos; WSL não tem `smplx`. Para re-rodar: arg certo é `--video`, não `-f`.

---

### 3.6 v4 — a palma estava errada de verdade; v3 não fazia o que o texto dizia

> Investigação de 2026-08-16, motivada por "o vídeo do baker também não está certo".
> **Tudo aqui é medido**, e as medições antigas do v3 eram circulares.

**O que estava errado no diagnóstico do v3 (§3.4):**

1. **O span sintético de 0.6 m é um no-op.** `computeHandPalmAxes`
   (`mikapo_mixamo_solver.js`) faz `across.normalize()` incondicionalmente, e é a
   única fonte de across para a mão e o antebraço. O span nunca chega no fade —
   0.06 m e 0.6 m produzem o mesmo vetor unitário. Logo "o fade pulava o roll"
   **não era** a causa raiz, e o que mudou de v2→v3 foi só a fonte do across, o
   `noAcuteFlip` e o strength 0.85→1.0.
2. **`ACROSS_FADE_LO` mistura unidades.** Para tronco/quadril o `obs` é um span em
   **metros**; para a mão é `sin(ângulo entre across e o osso)` — adimensional.
   Mesma constante, dois significados. Corrigido: `UNIT_ACROSS_FADE` para os
   chamadores normalizados (mão/antebraço).
3. **`render_bake_top.py --verify` é circular.** Ele reconstrói o across do avatar
   *a partir de* `rest.restAcrossInRoot` — exatamente o vetor que
   `rotateBoneWithAcross` acabou de alinhar ao alvo. Mede a função objetivo do
   próprio solver: passa por construção mesmo com o eixo de rest errado. Os
   "7.6°/7.4°" não provavam nada sobre o render.

**A causa raiz real:** `restAcrossInRoot` da mão/antebraço era `boneDir × up`, com o
comentário "T-pose palms face down". **O GLB do boxeador não é T-pose** — os braços
caem ~66° abaixo da horizontal. Medido contra o eixo real da palma: **41° de erro na
mão esquerda, 35° na direita**; e o antebraço (que recebe o across *da palma*) usava
um eixo ~25° diferente do da mão.

**O que não funciona:** PCA da malha da luva. Medido: a nuvem de vértices da mão é
~10×12×10 cm com valores principais 6.57 / 6.12 / 4.22 — uma luva de boxe é uma
*mitene arredondada*, quase isotrópica, então o "eixo mais largo" é ruído. Uma
tentativa nesse caminho inverteu a mão **esquerda em ~180°** (as duas mãos ficaram
com across opostos) e deu erro absoluto de palma de **133° (esq) / 50° (dir)**.

**O que funciona (v4):** o across da palma **é o eixo de flexão dos dedos**. Os dedos
dobram num plano; a normal desse plano é o eixo medial-lateral da palma. Ajustando um
plano ao conjunto mão + cadeia de dedos (SVD/Jacobi):
- as duas mãos, modeladas independentemente, concordam a **3.3°** sob espelhamento
  (subconjuntos da cadeia: 33-37° → o conjunto completo é o que condiciona bem);
- não assume pose de rest nenhuma → serve para qualquer rig humanoide;
- fallback para o `boneDir × up` antigo se o rig não tiver cadeia de dedos.
O sinal da normal é ambíguo, então é ancorado na heurística antiga (que só precisa
estar a <90°, e está a 35-41°).

**Resultado medido (264 frames, clip inteiro):**

| métrica | antes (PCA da luva) | depois (plano dos dedos) |
|---|---|---|
| **erro absoluto de palma** esq / dir | **133.0° / 50.3°** | **8.3° / 8.4°** (p95 15.9/18.6) |
| palma-Y no soco (dir), fit vs avatar | −0.47 vs **+0.27** | −0.47 vs **−0.47** (\|dif\| 0.04) |
| palma-Y no soco (esq), fit vs avatar | −0.25 vs −0.44 | −0.26 vs −0.25 (\|dif\| 0.03) |
| residual de tracking (offset removido) | ~5° | ~5° |

O **residual de tracking já era ~5°** nos dois casos: a mão sempre *seguiu* o fit — o
defeito era um **offset constante** de palma, que é justamente "o punho está girado
90°/lateral". Métrica que remove o offset (a antiga) **esconde** esse defeito; por isso
`absolute_palm_error.py` mede **sem calibração**.

**Instrumentos novos** (o render é lento, então roda uma vez e grava `palm_raw_*.npz`):
- `scripts/check_palm_fidelity.py` — mede o avatar renderizado contra o fit sem tocar
  em `restAcrossInRoot`; grava o dump bruto.
- `scripts/absolute_palm_error.py` — **erro absoluto de palma, sem calibração**. É o
  número que o olho julga. Usar este como gate.
- `scripts/analyze_palm_raw.py` — tracking (offset removido) + métrica livre de
  calibração (magnitude de rotação por frame).
- `scripts/compare_palm_frames.py` — close-ups pareados mesh × avatar, mesma câmera.
- `scripts/glb_hand_axes.py` — diagnóstico de geometria do rig (foi como se mediu que
  a luva é isotrópica).

**Ressalva honesta:** o eixo "absoluto" do avatar usa a mesma definição geométrica
(plano dos dedos) que alimenta a correção, então há circularidade parcial — a
verificação independente é **visual**, em `experiments/palm_compare/` (mesh e avatar
lado a lado, t=440/460/480/500, as duas mãos), e ali as orientações batem.

**Aviso de concorrência:** durante esta sessão o `mikapo_mixamo_solver.js` foi
modificado por outra sessão/agente (a tentativa de PCA da luva acima). Se houver dois
agentes editando o mesmo arquivo, medições ficam instáveis — conferir `md5sum` antes de
confiar num "antes/depois".

---

### 3.7 v4b — varredura do corpo inteiro: onde MAIS o retarget perde o fit

Medido com `scripts/check_body_fidelity.py` (264 frames). Duas métricas por osso,
porque o solver trata aim e roll de formas diferentes:

- **swing_var** = erro de *direção* do osso, depois de remover a diferença de
  **convenção de rig**. Isso importa: Mixamo e SMPL-X não definem clavícula/pelve
  no mesmo lugar, e o ângulo cru entre as direções mistura convenção com erro.
  Levando a direção do avatar para o frame local do fit (`F_tᵀ · dir`), a
  diferença de definição vira **constante** e o que sobra é erro de verdade.
- **twist** = roll em torno do eixo do osso (o que posições não carregam),
  calibrado com o offset constante à direita (`A_t = F_t · C`).

| osso | swing_raw | **swing_var** | **twist** | leitura |
|---|---|---|---|---|
| rightLeg / leftLeg | 2.4 / 1.9 | 2.4 / 1.9 | **13.3 / 12.8** | pior twist — **sem sinal de roll** (`rotateBoneToward` puro) |
| neck | 5.8 | 3.4 | 8.5 | era 7.9 / 10.5 com `strength 0.4`; ver abaixo |
| hips | 30.7 | 6.7 | 2.5 | os 30.7 são quase todos convenção |
| shoulders (clavículas) | 33.1 / 33.4 | **2.9 / 3.1** | 5.1 / 4.0 | **estão OK** — os 33° são 100% convenção de rig |
| spine | 6.3 | 2.5 | 4.1 | **está OK** — o `shoulderAcross` compartilhado não atrapalhou |
| mãos / antebraços | 18-19 / 3.1 | 4.1 / 3.1 | 1.9-2.6 | melhores do corpo após o v4 |

**Três previsões minhas que a medição derrubou:** clavícula, coluna e quadril
pareciam problemáticos pela leitura do código (sem roll / across compartilhado) e
**não são**. Só o `swing_var` revela isso — o ângulo cru dava 33° na clavícula.

**Pescoço: `strength` 0.4 → 0.75 (aplicado).** Era o pior osso do corpo por margem
larga (7.9 / 10.5 vs 2-4 do resto), e o único cuja causa era um **parâmetro**, não
falta de sinal ([`applyHeadFromSmpl`]). O autor confirmou independentemente que
"o giro de cabeça não estava sendo aplicado bem". Depois: **3.4 / 8.5**, sem mexer
em nenhum outro osso.

Não é troca de suavidade por precisão — medido com `dump_bone_quats.py` +
`analyze_bone_jitter.py`:

| pescoço | jitter p50 | p95 | max |
|---|---|---|---|
| **FIT (referência)** | 2.73° | 7.80° | 14.12° |
| avatar 0.4 | 1.54° | 4.38° | 7.70° |
| avatar **0.75** | **1.96°** | 6.02° | 9.65° |

Com 0.75 o pescoço ainda treme **menos que o próprio fit** (1.96 vs 2.73), ou seja
o 0.4 não estava protegendo contra amplificação de ruído — estava só atrasando o
pescoço.

> **Ressalva:** tudo isso foi medido com entrada do **fit** (suave). No caminho
> **live** a fonte é o x55, cujo ruído de roll é 66-87°/frame (§3.3). Re-medir o
> jitter lá antes de assumir que 0.75 transfere.

**Lacunas conhecidas que ficam abertas** (não são bugs, é falta de sinal):
1. **Canela** — nenhum roll. Rotação tibial não é transferida. Provavelmente
   invisível no boxe (a perna gira pelo quadril, que está a 3-4°).
2. **Pé** — só yaw.
3. **Cabeça** — não medida: o osso `head` do avatar aponta pro topo do crânio e o
   SMPL-X não tem equivalente direto, então não entra no `BONE_MAP`. Julgar por
   print.

---

## 4. Front de soluções (exploração; implementação só com OK)

### A. Otimizar o fit por engenharia (sem treinar nada)

| # | Solução | Alavanca | Estado |
|---|---|---|---|
| A1 | **Init temporal** (`initial_pose_rotvecs`, `initial_shape_betas` — API oficial) + `num_iter` 1–2 | custo ∝ iterações; quente converge com menos iterações | **teste pendente (o botão oficial)** |
| A2 | **Subsampling temporal**: fit a cada N frames + interpolar | custo/frame ÷ N; empilha com A1 | pendente |
| A3 | **Warm start pelo head rápido** (x55) em vez de estado temporal | robusto a corte de cena | pendente |
| A4 | **FP16** no forward do fit | ~metade do custo; risco de estabilidade na otimização | pendente (10 linhas) |
| A5 | **TRT/DML com laço desenrolado** (num_iter é contagem fixa → desenrolável) | features já provaram 27→1.9ms; ops do fit são mais variadas | incerto, testável |
| A6 | Chamar `_estimate_parametric_batched` direto (sem YOLO) | economiza os ~25ms do detector | já validado |
| A7 | Crop só da pessoa / menor resolução | reduz pré-processamento | marginal |
| A8 | Batch de vários frames (throughput offline) | amortiza overhead | offline |

**Referência do que destrava export:** as features densas (x55 + surface 1024) já rodam no
runtime a ~11–14ms via TRT/DML (exp10/14 no results.tsv), e são **as mesmas features que o fit
consome** — a base para um head destilado já está de graça no jogo.

### B. Destilação — rede barata que imita o otimizador (a resposta de "tempo real" de verdade)

1. **Teacher**: fit offline (já exportado: `experiments/nlf_fit_webcam1/fit_smplx.npz`,
   1056 frames com pose/betas/verts).
2. **Entrada**: as features que o runtime já calcula (dense x55 + superfície + confiança por ponto).
3. **Saída**: quaternions/6D por osso (ou twist por osso). Preferir **6D** (evita descontinuidade
   de eixo-ângulo) + **loss geodésica** ponderada por confiança.
4. **Arquiteturas candidatas**: MLP pequeno (~1–3ms); MLP + janela temporal (conv 1D / LSTM) para
   fluência; ou **predizer resíduo em cima do fast path** (delta learning).
5. **Métricas**: erro angular por osso vs fit (punho/antebraço/ombro/coluna), fluência
   (jump°/frame), e validação visual via baker top.
6. **Riscos**: generalização fora dos clips de treino; precisar de mais dados/augmentação;
   validar os dedos do fit antes de destilar com eles em peso total.

### C. Simplificação do modelo

- O "fit" é um **otimizador**, não uma rede → simplificar = **destilar** (B).
- O que é rede de verdade no pipeline: detector (já trocado YOLOv8x→n + sticky crop) e a
  backbone das features (já TRT/DML). Sobra: medir impacto de **resolução menor** (540p→270p)
  no fast path.
- Alternativa operacional: **fit em baixa frequência + interpolação** (A2) — "fit em 10Hz,
  avatar em 30fps".

### D. Auto-avaliação (harness)

1. **Matriz de dispositivos**: benchmark de cada estágio (detector, features, head de rotações,
   retarget) em: torch CUDA, TRT, DML, ONNX CPU; GPUs da 3060 para baixo (1650, 1060, MX, iGPU
   Intel/AMD); CPUs (AVX2/ARM).
2. **Orçamento**: 30fps=33ms (meta), 60fps=16.7ms (aspiração). Relatório p50/p95 + veredito
   "roda 30fps?" por config.
3. **Fidelity gate**: erro angular por osso vs fit (GT), fluência (jump°/frame), e **render check**
   automático (baker top em clips fixos, screenshots em frames fixos, métricas de roll).
4. **Um script "certifica PC"**: roda em qualquer máquina e reporta latência + veredito — é o
   que o autor quer para "rodar em GPUs menos potentes de diferentes tipos de PC".

### E. CPU (opcional, não obrigatório)

- Head destilado em **ONNX Runtime CPU** (int8 se possível) — provável que caiba (rede pequena).
- Fast path já é leve; **fit em CPU puro é inviável** (97ms+ em GPU), mas **amortizado** (A1/A2)
  talvez sobreviva em CPU para qualidade máxima.
- **Fallback hierárquico**: GPU → CPU com qualidade reduzida (fit a cada N frames), mantendo o
  jogo jogável em qualquer máquina.

### F. Insights gerais de pipeline (a mão é o que importa)

1. **Camadas recomendadas** (em ordem de maturidade):
   - (a) **Offline**: fit/baker top como validação e teacher — **feito**.
   - (b) **Runtime**: head destilado (B) alimentando o **solver que já consome rotações** (baker
     top, ~1ms JS) — o elo que falta.
   - (c) Suavização temporal (One-Euro) já no solver.
2. **A mão**: sem pronação o jogo não serve. O punho "luva" do SMPL-24 não resolve; o caminho é
   (i) dedos do fit validados → (ii) destilação com sinal de mão → (iii) bake top.
3. **Decisão que desbloqueia tudo** (medir primeiro): **teste do init temporal** — se o fit
   amortizado cair para ~15–20ms, o fit de verdade roda ao vivo sem treinar nada; se não cair,
   vamos de destilação.

---

## 5. Próximos passos (aguardando OK do autor)

1. **Teste do init temporal** (`num_iter` ∈ {1,2,3} × init do frame anterior, custo e erro vs
   fit completo) — decide o caminho runtime (A vs B).
2. **Medir o bias de rest do baker top** vs mesh (roll por osso, frames fixos) — decide se entra
   o alinhamento automático de rest (offset estático de ~50 linhas).
3. Se o fit não couber ao vivo: **montar a destilação** (B) e medir erro angular por osso.
4. **Matriz de auto-avaliação** (D) nos backends/dispositivos disponíveis + CPU (E).
5. Ajustes finos do baker top (damp de roll de ombro se parecer "torcido" — artefato da
   decomposição axis-angle).

---

## 6. Fatos ancorados (para não re-medir à toa)

- Fast 24j ~24ms · dense 1079q ~27ms · parametric ~124ms · **fit puro ~97ms** · detector ~25ms.
- Query densa ≈ +3ms para +1055 pontos.
- Roll x55: 66–87°/frame de ruído (máx 169). Roll fit: 10–12°/frame (máx 26).
- Features runtime: ~11–14ms (TRT/DML); export TRT 27→1.9ms.
- `fit_joints` ≡ `x55` em espaço (mm, y-down, ordem 55; residual ~37mm centrado na pelve).
- FK SMPL-X validado (<1° direções; sintético exato); baker top validado (0.01° na página).
- Modelos/artefatos: `data/models/nlf/nlf_s_multi_0.2.2.torchscript`,
  `external/GVHMR/inputs/checkpoints/body_models/smplx/SMPLX_NEUTRAL.npz`,
  `experiments/nlf_fit_webcam1/fit_smplx.npz` (1056 frames),
  `experiments/bake_top/` (baker top), `experiments/watch.html` (preview :8785).
