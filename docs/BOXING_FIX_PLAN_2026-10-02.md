# HEAVY HANDS — Plano de correções (02/out/2026)

Status: **plano aprovado, nada implementado ainda.** Antes de começar: pausar o Codex nos arquivos
`viewer/boxing*.js`, `viewer/avatar_self_contact.js`, `scripts/serve_lab.py`, `scripts/nlf_engine.py`
(duas ferramentas editando o mesmo arquivo já quebraram o jogo uma vez).

---

## 1. Como o jogo funciona hoje (mini-mapa)

```
 webcam ──► live.html (iframe) ──JPEG──► servidor NLF (WebSocket :8781)
                                            │  1. recorte da pessoa (YOLO, "crop box")
                                            │  2. NLF estima 16 juntas 3D em metros
                                            ▼
 boxing.js ◄── postMessage "corner-pose" (pose + cameraPose)
   │
   ├─ WebcamFootwork  → normaliza a pose (escala pela altura do 1º quadro), anda no ringue
   ├─ PunchDetector   → decide "isso foi um soco?" e "quão forte?"
   ├─ retarget        → aplica a pose no avatar cartoon (mikapo_mixamo_solver.js)
   ├─ alignHandsToBody / NativeGuardContact / FootPlanting → correções em cima do avatar
   └─ simulate        → colisão luva × corpo do oponente, dano, efeitos, som
```

Termos usados no documento:

- **NLF**: a rede neural que olha a imagem e devolve onde estão as juntas do corpo, em metros.
- **Crop box (recorte)**: o retângulo da imagem que o NLF analisa. Se estiver errado, o NLF vê só um pedaço
  do corpo e "chuta" o resto.
- **cameraPose**: juntas em metros no espaço da câmera (inclui distância até a câmera).
- **Retarget**: transferir a pose humana para o esqueleto do boneco.
- **IK (cinemática inversa)**: calcular ângulos de ombro/cotovelo para a mão chegar num ponto.
- **Quantidade de movimento (momentum)**: massa × velocidade. É o que um soco "carrega".
- **Newton (N)**: unidade de força. Força ≈ momentum ÷ tempo de contato.

---

## 2. Dados que usamos para decidir

| Fonte                                               | O que é                                                                                                                                             | Script                             |
| --------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------- |
| `debug_luta/corner-debug-2026-10-02T15-07-23-920Z/` | Luta real de 11 min: webcam, vídeo comparativo, `timeline.ndjson` com 17.696 poses NLF (27 Hz) e cada golpe que acertou o sparring                  | `scripts/analyze_punch_power.py`   |
| `benchmarks/punch_cadence_20261002.mp4`             | 67 s de socos com cadência aumentando + final só com punho/antebraço                                                                                | `scripts/benchmark_punch_power.py` |
| Resultados                                          | `experiments/punch_power_audit.txt`, `debug_luta/.../punch_power_audit.json`, `benchmarks/punch_cadence_20261002.{power.txt,power.json,punches.md}` | —                                  |

---

## 3. Descobertas

### D1. Potência atual está saturada (não diferencia soco fraco de forte)

Cálculo atual: velocidade do pulso entre **dois quadros seguidos** → `punchPower(speed)` com 100% a 4,2 m/s.

- Luta de 11 min: **73%** dos 158 golpes com potência ≥ 0,95; 111 golpes com exatamente 100%.
- Benchmark: socos lentos do começo já saem com 94–100%; na fase "só punho" deu **100% para um movimento de 45 N**.
- O detector antigo **perdeu 17 de 67 socos** reais e **disparou em 25 movimentos que não eram soco**.
- Causa: um único quadro com tremida do NLF vira pico de velocidade.

### D2. Cálculo físico funciona e acompanha a cadência

Benchmark (socos reais = braço esticando ≥ 1 m/s e alcance ≥ 40 cm):

| Fase                       | Socos | Antigo | Novo    | Força média |
| -------------------------- | ----- | ------ | ------- | ----------- |
| 0–12 s devagar             | 12    | 94%    | 22%     | 270 N       |
| 14–26 s                    | 11    | 100%   | 51%     | 613 N       |
| 30–40 s rápido             | 11    | 82%    | 50%     | 599 N       |
| 43–55 s mais rápido        | 16    | 94%    | 56%     | 682 N       |
| 58–66 s só punho/antebraço | 17    | 87%    | **11%** | 136 N       |

Observação honesta: soco muito rápido mas curto e sem corpo (fase 30–40 s) dá a mesma força que soco mais
lento com corpo. Fisicamente correto; pode não bater com a sensação "estava batendo mais forte".

### D3. A mão da guarda "pega carona" no corpo

Quando o tronco gira, a mão que está parada na guarda também se move. O cálculo físico deu ≥ 50% para
**23 movimentos que não eram soco**. Solução: força só é calculada para um **soco detectado** (braço esticando),
e a parte do corpo só conta se o braço também estiver indo na direção do alvo.

### D4. NLF subestima o pico de velocidade

Luvas medidas a 2–6 m/s; jab real chega a 7–10 m/s. NLF a ~27–30 Hz + suavização corta o pico.
Consequência: os newtons medidos ficam ~2–3× abaixo de laboratório. **A ordem (fraco < forte) é confiável;
o valor absoluto é uma estimativa.** Por isso a escala é calibrada com os dados do próprio jogo (seção 5).

### D5. "DEFESA" falsa em metade dos golpes

Luta de 11 min: **79 de 158** golpes classificados como `guard`. Causa: em `simulate`
(`boxing.js`) ainda existe `guard = res.target === "head" && !open && guarded(b.pose)`, que olha o
**esqueleto mocap** do bot (luvas a < 38 cm da cabeça, ignorando profundidade). No avatar renderizado as luvas
estavam a 33–55 cm da cabeça — o golpe passava, mas o jogo dizia "DEFESA".

### D6. BUG do recorte velho no início de cada conexão (causa provável do "voar")

Ao abrir uma conexão WebSocket nova, o `AsyncPoseWorker` (`scripts/nlf_engine.py`) usa o
**crop box da sessão anterior** (o `StickyBBox` é global no runtime) até a primeira detecção YOLO assíncrona
ficar pronta — o que levou **~25 s** nas duas medições.

Durante esses ~25 s:

|                                 | Recorte velho (0–25 s) | Recorte certo |
| ------------------------------- | ---------------------- | ------------- |
| Altura do esqueleto             | **1,10 m**             | 1,51 m        |
| Tremida entre quadros (mediana) | **15 cm**              | 2–4 cm        |
| Pico de tremida (p95)           | 0,4–3,2 m              | 8–13 cm       |

Por que isso faz o boneco voar / ficar errado a partida toda:

```
1º quadro da partida (recorte velho, altura 1,10 m)
        │
        ▼
WebcamFootwork.reference = { root, floor, scale = 1.72 / 1.10 = 1.56 }   ← CONGELADO aqui
        │
        ▼
Quando o recorte corrige (altura real 1,51 m): tudo é multiplicado por 1.56
  → corpo ~36% maior, pelve "sobe", pés não chegam no chão = boneco voando
  → deslocamentos lateral/radial também 36% exagerados
```

Além disso: o jogo usa cameraPose relativo ao 1º quadro para a altura da raiz; com o chão estimado errado,
a raiz flutua. O `live.html` original não sofria disso porque plantava o pé mais baixo no chão a cada quadro
(`plantGround` + média móvel do chão).

### D7. Caminho HTTP do NLF é ~25× mais lento

`/api/nlf_pose` (HTTP) leva ~600 ms/quadro; o WebSocket leva ~25 ms. O jogo já usa WebSocket; só os scripts
de teste usavam HTTP. Benchmarks agora usam WebSocket.

### D8. Memória da placa de vídeo (VRAM)

Com 10,7 GB de 12 GB ocupados, o NLF ficou lento. O servidor `serve_lab.py`, rodando desde cedo, segurava
memória: reiniciar liberou ~9 GB. Chrome com os avatares de 760 mil vértices também pesa ~6 GB.

### D9. Mãos afastadas na guarda e punho torto

- **Afastadas**: o `NativeGuardContact` (`viewer/avatar_self_contact.js`, Codex) tem uma faixa "macia" de
  2 cm contra um casco da cabeça que inclui as orelhas — empurra as luvas para fora.
- **Punho torto**: `alignHandsToBody` reposiciona a luva via IK de 2 ossos mas **mantém a rotação de mundo da
  mão**; quando o antebraço muda de direção, o punho dobra.
- Guarda em proporções cartoon abria ~1,85× mais que a real; `alignHandsToBody` trouxe para 1,15×.

### D10. Já corrigido nesta sessão (para referência)

- Contorno (outline) dobrava os triângulos → NLF caía para ~1 pose/s → HUD piscando.
- Pernas do menu tortas → sem footContacts, a perna não é mexida.
- Jab não alcançava (17 cm curto) → colisão pela malha renderizada + `COMBAT.minDistance = 0.72`.
  Efeito colateral: corpos se sobrepõem (vira o item E).

---

## 4. Plano de correções (ordem de execução)

Cada passo: implementar → rodar os mesmos dados (luta de 11 min + benchmark) → tabela antes/depois.

Ps: Por favor retire os contornos. retire os contornos do avatar permanentemente pq pesa muiito!

### 0. (NOVO, primeiro) Recorte certo desde o 1º quadro + calibração só com pose boa

Servidor (`scripts/nlf_engine.py`, `scripts/serve_lab.py`):

- Ao abrir conexão nova: **zerar o `StickyBBox`** (`last_xywh = None`, `frame_i = 0`).
- Enquanto não houver detecção publicada: rodar **YOLO síncrono** no 1º quadro (custa ~1 quadro de atraso,
  uma vez) em vez de usar o recorte velho ou a imagem inteira.
- Aquecer o YOLO no `load()` do runtime (o primeiro `detect` na thread custava os ~25 s).

Jogo (`viewer/boxing_core.mjs` → `WebcamFootwork`):

- Só fixar `reference` (escala/chão) quando a pose estiver **estável**: altura plausível (1,3–2,1 m) e
  tremida baixa por ~0,5 s. Até lá, mostrar "Calibrando…".
- Com o item B (chão plantado todo quadro), a dependência do 1º quadro some de vez.

Critério de aceite: altura do esqueleto estável (±3 cm) desde o 1º segundo; tremida mediana < 4 cm.
Teste: `benchmark_punch_power.py` **sem** o "priming" (deve dar o mesmo resultado que com).

### A. Pernas 100% NLF

- Remover passos sintéticos, `FootPlanting.applyInferred`, detecção de pé visível/invisível.
- Pernas seguem exatamente o NLF.
- Aceite: nenhum código de perna além do retarget; menu sem pernas tortas.

### B. Chão igual ao `live.html` original

- A cada quadro, o pé (sola) mais baixo é plantado no canvas, com média móvel suave do chão.
- Remove o "voar" e o "afundar". Testar com o vídeo antes de manter ("antes estava ótimo").
- Aceite: sola a ±2 cm do canvas em 95% dos quadros; nenhuma deriva lenta de altura.

### C. Luva × própria cabeça: colisão firme, sem faixa macia

- Remover a faixa macia de 2 cm do `NativeGuardContact`.
- Usar forma justa do rosto (sem orelhas). Luva só para se fosse atravessar; fora isso, fica onde você colocou.
- Aceite: distância entre luvas na guarda ≈ a sua real (medida no vídeo).

### D. Orientação da mão determinística

- Luva alinhada com o antebraço (punho reto).
- Palma a ~45° entre "olhando para o rosto" e "olhando para a outra luva".
- Rola junto com o antebraço quando o cotovelo sobe.
- Aceite: ângulo punho–antebraço < 10°; palma 45° ± 10° na guarda.

Ps: por favor tenha certeza de que isso não vai resultar em dobras/torções feias no modelo 3D. (pro futuro era bom termos algum algoritmo que detecte e corrija automaticamente essas dobras no modelo 3D, no final me responda se acha que isso é possível ou não)

### E. Corpos não se atravessam

- Colisão firme tronco × tronco (cápsulas do avatar renderizado). Mantém a distância mínima de alcance do jab.
- Aceite: zero quadros com interpenetração de tronco no replay.

### F. Bloqueio só pela geometria renderizada

- Física será baseada na colisão do modelo renderizado (luvas e antebraços).
- Remover o fallback `guarded(b.pose)` de `simulate`.
- Golpe é "DEFESA" só se o caminho da luva bater na luva/antebraço renderizado do oponente antes da cabeça.
- Aceite: % de `guard` na luta cai de 50% para o que o vídeo comparativo mostrar como defesa real.
  (qualquer outra lógica que estiver no projeto que esteja atrapalhando isso pode retirar, desde que não quebre outras funcionalidades essenciais)

### G. Potência física (ver seção 5 para números)

- Força só é calculada **depois** de um soco detectado (corrige D3).
- Novo detector de soco: braço esticando ≥ 1,0 m/s e alcance ≥ 40 cm (em vez de velocidade de 1 quadro).
- Velocidades por regressão em 150 ms (reta ajustada, não diferença de 2 quadros).
- Massas por segmento (de Leva 1996) para corpo de `PUNCH.bodyKg` (padrão 80 kg, configurável):
  mão 0,6%, antebraço 1,6%, braço 2,7%; tronco 43% e cabeça 7% entram com acoplamento de 18%.
- Só conta movimento **na direção do alvo**.
- Força = momentum ÷ 0,015 s (tempo de contato da luva).
- Aceite: benchmark reproduz a tabela D2; fase "só punho" ≤ 15% médio; guarda pegando carona = 0 golpes.
  temos já um script no projeto que realiza o benchmark da potência dos socos, comparando a detecção atual com a física baseada em massa e velocidade. tenha ele como referência para validar as mudanças propostas nesta seção.

### H. Impacto firme, não "molenga"

- Luva para na superfície por ~110 ms.
- Os dois cedem um pouco: ~6–8° no cotovelo, 2–3 cm de compressão.
- Volta rápida em ~80 ms; empurrãozinho no atingido proporcional à força.
- se o oponente está tonto, o impacto pode ser mais severo, causando maior deslocamento e caso seja K.O o personagem pode cair no chão com gravidade na direção do impacto.
- Cada tipo de impacto tem seus próprios padrões de efeitos visuais vfx, como faíscas de cores variadas dependendo da velocidade do soco saindo do braço e ficando no ar (como tekken), ou outras particulas desde que não fique muito exagerado ou tampe demais a jogabilidade
- as onomatopéias atualmente estão muito infantilizadas, poderiam ser mais realistas e impactantes, sérias, refletindo melhor a intensidade do golpe. (veja sessão de classificações de golpes)
- sons de impacto: `heavy punch` na faixa `pesado` e `super strong punch` na `devastador` (seção 5.6).
- ao cair no nocaute, o som de ouvido tampado da seção 5.11.

### I. Narrador (voz do Victor)

- Ligar os clipes de `assets/boxing_audio/victor_clips/` aos eventos da seção 5.5, com a função `say()`
  (uma voz por vez, intervalo mínimo, prioridade) e os dois avisos de vida baixa (`hp <= 25`).
- Aplicar o efeito de voz da seção 5.5 (reverb curto + dobra leve) no barramento do narrador.
- Fazer **depois do G**: as falas por faixa de força (`hit_good`/`hit_heavy`/`hit_brutal`) dependem da potência física.
- Aceite: no replay da luta de 11 min, no máximo 1 fala a cada 3 s; nocaute sempre fala; vida baixa fala 1 vez por lutador e round.

### J. Remover o contorno dos avatares (definitivo)

Pedido: tirar de vez, porque pesa (dobra os triângulos dos avatares de ~760 mil vértices e derrubava o NLF).

- Apagar `addSkinnedOutlines` e `outlineNormals` de `boxing_fx.js`, a chamada em `boxing.js` (~linha 468) e
  o tratamento de `a.outlines` (~linha 1699).
- Apagar a opção "Cartoon + contorno" de `boxing.html` e o `localStorage` `cornerOutline` (`boxing.js` ~linhas 693–696).
- Remover as guardas `userData.cornerOutline` que sobram em `avatar_self_contact.js`, `boxing_feet.js` e `boxing.js`.
- **Manter** o `outline()` simples dos objetos estáticos do cenário (`boxing_arena.js`): não é skinned e custa quase nada.
- Aceite: nenhuma referência a `addSkinnedOutlines`/`cornerOutline` nos avatares; contagem de triângulos por avatar
  igual à da malha original; taxa de poses do NLF e FPS iguais ou melhores que hoje (`probe_boxing_fps.py`).

### K. Idioma e tom dos textos

- Jogo em inglês e menus nos dois idiomas, conforme a seção 5.7; enxugar os menus conforme a seção 5.8 (rótulos, sem texto de apresentação).
- Montar o menu principal da 5.9 e aplicar o nome da seção 8.
- Fazer junto com ou depois de H, I e J, que também mexem em textos, para não escrever duas vezes.
- Aceite: nenhuma string em português fora de `strings.pt`; trocar o idioma em Ajustes atualiza todos os menus sem recarregar;
  `<html lang>` acompanha o idioma escolhido.

---

## 5. Força, dano e feedback (a constante reguladora)

### 5.1 Duas coisas separadas: escala das classificações × teto físico

- **Escala das classificações** (`tierScaleN`): só decide o _nome_ do golpe (toque … devastador),
  onomatopeia, narrador e intensidade dos efeitos. Calibrada nas faixas **mais comuns** das medições,
  para cada nível aparecer com frequência razoável.
- **Teto físico** (`maxN`): limite de segurança da força aceita, **acima** do soco mais forte medido
  (1468 N), para dar margem a gente mais forte. Não é "o 100%" de ninguém; só corta pico absurdo de ruído.
- **Dano** não usa nenhuma das duas como 100%: é proporcional aos newtons (5.2). Quem bate mais forte
  que o Henrique causa mais dano que ele.

Proposta: em `viewer/boxing_core.mjs`, junto do `COMBAT`:

```js
export const PUNCH = {
  // Classificações (feedback): faixas como fração de tierScaleN. Calibrado nas lutas de 02/out.
  tierScaleN: 1200,
  tiers: [
    { at: 0.0, id: "toque" },
    { at: 0.13, id: "leve" }, // ~150 N
    { at: 0.33, id: "solido" }, // ~400 N
    { at: 0.54, id: "forte" }, // ~650 N
    { at: 0.75, id: "pesado" }, // ~900 N
    { at: 0.96, id: "devastador" }, // ~1150 N
  ],
  // Teto físico com margem: ~1,7x o soco mais forte medido (1468 N).
  maxN: 2500,
  minN: 80, // abaixo disso não é golpe (encostar)
  damagePerN: { head: 1 / 85, body: 1 / 120 },
  bodyKg: 80,
  trunkCoupling: 0.18,
  contactSeconds: 0.015,
};
```

Por que **frações**: se um dia a escala das classificações precisar mudar (outra câmera, público mais
fraco/forte), muda-se um número só e todas as faixas acompanham. O teto `maxN` é independente.

### 5.2 Dano fiel aos newtons

- `F = clamp(forcaMedida, 0, maxN)`.
- Dano **linear** nos newtons (fiel à medição): `dano = F × damagePerN[alvo]`, depois
  queixo ×1,35, tonto ×1,3, contra-ataque ×1,2. `COMBAT.maxDamage` sobe de 18 para 30 (só alcançável perto de `maxN`).
- Abaixo de `minN`: zero dano (só um "toque" visual).

O que isso dá na prática (cabeça, sem bônus):

| Golpe                 | Força  | Dano                     |
| --------------------- | ------ | ------------------------ |
| mediana da luta       | 471 N  | ~6                       |
| p90 da luta           | 1001 N | ~12                      |
| seu mais forte        | 1468 N | ~17 (≈ o máximo de hoje) |
| alguém bem mais forte | 2000 N | ~24                      |
| teto                  | 2500 N | ~29                      |

`damagePerN` é o botão de balanceamento (quantos golpes para um KO); não muda as classificações.

### 5.3 Faixas de feedback calibradas pelo que acontece de verdade

As mensagens/onomatopeias/narrador **não** esperam newtons altos demais: as faixas foram escolhidas pelas
distribuições reais, para cada nível aparecer com frequência razoável.

| Faixa      | Força      | Luta de 11 min | Benchmark (socos) | Feedback sugerido                              |
| ---------- | ---------- | -------------- | ----------------- | ---------------------------------------------- |
| toque      | < 150 N    | 11%            | 0%                | sem texto; "tap" baixinho                     |
| leve       | 150–400 N  | 31%            | 28%               | sem texto; faísca pequena                      |
| sólido     | 400–650 N  | 30%            | 42%               | sem texto; hit-stop curto, recuo da cabeça     |
| forte      | 650–900 N  | 15%            | 26%               | **LANDED** (pequeno, num canto); narrador `hit_good` |
| pesado     | 900–1150 N | 7%             | 2%                | **CRUSHING**; heavy punch (5.6); tremida de tela; narrador `hit_heavy` |
| devastador | ≥ 1150 N   | 6%             | 2%                | **DEVASTATING**; super strong punch (5.6); câmera lenta curta; torcida; narrador `hit_brutal` |

Texto na tela só a partir de `forte`, em inglês, sem onomatopeia de quadrinho (os "POW!/BAM!/PÁ!" de
`WORDS` em `boxing.js` saem). Fonte sem serifa, condensada, branca com contorno fino; aparece e some em
~0,6 s, sem tremer nem girar. Em `pesado` e `devastador` pode mostrar a força pequena embaixo ("1.250 N").
Além da força, aparecem **tags de contexto**, que contam o que aconteceu na luta e valem mesmo com força média:
`COUNTER`, `ON THE CHIN`, `LIVER SHOT`, `ROCKED`, `KNOCKDOWN`, `K.O.`, e para sequências `COMBO` (a partir de 3 golpes)
e `UNSTOPPABLE` (a partir de 7), que aparecem junto do contador de combo (`N HITS`).

Referência das distribuições:

|                                      | p10 | p25 | p50 | p75 | p90  | p95  | máx  |
| ------------------------------------ | --- | --- | --- | --- | ---- | ---- | ---- |
| Luta 11 min (158 golpes)             | 136 | 277 | 471 | 678 | 1001 | 1181 | 1468 |
| Benchmark (50 socos, sem fase punho) | 237 | 342 | 564 | 689 | 785  | 882  | 1392 |

Ou seja: "devastador" é raro mas alcançável (~1 em cada 16 golpes numa luta real); "forte" aparece
com frequência suficiente para o narrador falar.

### 5.4 Efeitos escalam com a força

Hit-stop, tremida de tela, flash, volume do som, tamanho do hematoma e duração do atordoamento
crescem com a faixa / `F / tierScaleN`. Opcional: mostrar "1.250 N" rapidinho nos golpes `pesado`/`devastador`
(com aviso de que é estimativa).

### 5.5 Narrador (voz do Victor)

Clipes em `assets/boxing_audio/victor_clips/` (37 frases cortadas do áudio do ElevenLabs por
`scripts/split_voice_clips.py`; nomes `categoria_frase.wav`; `manifest.json` guarda texto e categoria).
Os nomes foram atribuídos pela ordem do roteiro e a duração de cada clipe bate com o tamanho da frase,
mas **conferir de ouvido** antes de ligar ao jogo.

**Escolhidos: só eventos que o jogo já detecta** (`impact()`, `showCombo()` e `finish()` em `boxing.js`),
sem nenhuma checagem nova:

| Evento que já existe | Clipe(s) | Observação |
|---|---|---|
| Fim por nocaute | `ko_k_o` | junto de `sound.ko()` e do banner "K.O.!" |
| Tela de resultado após nocaute (`ko.shown`) | `ko_it_s_over` ou `ko_finished` (sorteia) | |
| Bot fica tonto (`hit.dizzy`, vítima não é você) | `hit_he_s_rocked` | |
| Você fica tonto (`hit.dizzy`, vítima é você) | `pressure_you_re_hurt`, `pressure_stay_up` ou `pressure_hold_it` (sorteia) | |
| Seu golpe no queixo (`kind === "chin"`) | `hit_clean` | só quando você é o atacante |
| Seu golpe em oponente tonto (`kind === "finisher"`) | `hit_finish_it` | só quando você é o atacante |
| Seu contra-ataque (`kind === "counter"`) | `counter_counter` ou `counter_caught_him` (sorteia) | |
| Combo de 3, 5 e 7+ golpes | `combo_combo`, `combo_keep_it_going`, `combo_unstoppable` | só compara o contador de combo existente; texto na tela `COMBO` (3+) e `UNSTOPPABLE` (7+) |
| Faixas de força `forte`, `pesado`, `devastador` (5.3) | `hit_good`, `hit_heavy`, `hit_brutal` | **só depois do passo G**: hoje 73% dos golpes saem com potência máxima e o narrador falaria o tempo todo |

**Mais um, com uma checagem mínima: limite de vida.** Dispara uma vez quando a vida de um lutador
cai até o limite baixo, que **já existe no jogo** (`hp <= 25`, usado hoje para `low-hp`, batimento
cardíaco e abafamento do som). Reaproveitar o mesmo número, sem criar outro.

| Evento | Clipe | Regra |
|---|---|---|
| Vida do bot cruza 25 para baixo | `hit_he_s_hurt` | uma vez por round |
| Sua vida cruza 25 para baixo | `pressure_he_s_got_you` | uma vez por round |

O disparo é na **passagem** pelo limite (antes > 25, depois ≤ 25), não enquanto a vida estiver baixa.
Por isso precisa de uma marca "já falou neste round" por lutador, zerada no início do round.

**Regras do narrador** (uma função `say(clipe, prioridade)`, única peça nova de infraestrutura):

- Uma voz por vez; nunca toca duas falas ao mesmo tempo.
- Intervalo mínimo de 3–4 s entre falas; se duas coisas acontecerem juntas, fala a de maior prioridade:
  nocaute > tonto > vida baixa > queixo/contra-ataque/finalizador > força > combo.
- Opcional: baixar a música ~3 dB enquanto a voz toca.

**Efeito da voz ("narrador supremo")**

O nome é **reverb** (reverberação): o som batendo nas paredes de um lugar grande, com várias reflexões muito
próximas que se misturam numa "cauda" que some devagar. **Eco** (ou *delay*) é diferente: repetições separadas e
audíveis ("ei... ei... ei"). O que você descreve é um reverb curto com a voz levemente dobrada; no cinema isso
é chamado de *voice of God* (voz de Deus). Aplicado **na reprodução**, sem alterar os WAV, para poder regular:

1. Barramento próprio da voz (`voiceBus`), separado dos efeitos, com volume próprio.
2. **Reverb de salão**: `ConvolverNode` com resposta ao impulso gerada por código (ruído com decaimento
   exponencial, sem arquivo novo). Cauda ~1,4 s, pré-atraso 35 ms, mistura ~20% de voz "molhada" sobre a voz seca.
3. **Reforço de graves**: filtro *low-shelf* de +3 dB em 120 Hz. A voz do Victor já é grave; só ganha peso.
4. **Dobra leve**: uma cópia da voz 18 ms atrasada, com `detune` de −12 cent (cent = centésimo de semitom) a −10 dB.
   Dá largura e grandeza sem virar eco.
5. **Corte de agudos** acima de ~9 kHz só na cauda do reverb, para ela não chiar.

Cuidados: a palavra precisa continuar clara no meio da música (as falas têm 0,8–1,6 s e a cauda 1,4 s, então o
intervalo mínimo de 3–4 s do `say()` já impede uma fala atropelar a outra); quando você está tonto, o abafamento
que já existe (`hurtMuffle`) pode valer também para a voz. Valores em uma constante `VOICE_FX` para ajustar de ouvido.
Teste: ouvir 5 clipes em 4 intensidades (seco, 15%, 25%, 35% de reverb) com a música de fundo e escolher.

**Fora do escopo por enquanto** (precisam de lógica nova):
`miss_*` (soco que expira sem acertar / desvio), `pressure_guard_up`, `combo_heavy_combo`/`combo_brutal_combo`
(somar força da sequência), `ko_down`/`ko_he_s_down`/`ko_stay_down` (knockdown com contagem),
`counter_perfect_counter`/`counter_big_mistake` (janela após defesa/desvio), `pressure_move`/`get_out`/`too_slow`,
`ko_good_night`.

### 5.6 Som de impacto por faixa (heavy punch e super strong punch)

Hoje `impact()` em `boxing_audio.js` toca sempre um dos `punch1`–`punch3` (DavidW, CC-BY 4.0) com volume
`0.45 + power × 0.25`, mais camadas sintetizadas (subgrave, estalo no queixo). O volume sobe com a potência,
mas o **timbre é o mesmo** do golpe mais leve ao mais pesado. Os dois sons novos (gerados no ElevenLabs,
em `assets/boxing_audio/`) dão um timbre próprio às duas faixas de cima:

| Faixa (5.3) | Som | Arquivo original |
|---|---|---|
| toque, leve, sólido, forte | `punch1`–`punch3` como hoje (volume pela força) | — |
| pesado (900–1150 N) | **heavy punch** | `A_solid,_heavy_punch_#1-1790963020354.mp3` |
| devastador (≥ 1150 N) | **super strong punch** | `A_super_strong,_heav_#3-1790963481872.mp3` |

Nas duas faixas o som novo toca **no lugar** do `punch1`–`punch3` (não por cima, para não embolar). As camadas
sintetizadas (subgrave, estalo) continuam, e o `hurtMuffle`/`ring` quando você é a vítima.

O que foi medido nos arquivos e o que precisa de preparo antes de ligar:

| | heavy punch #1 | super strong punch #3 |
|---|---|---|
| Duração do arquivo | 3,02 s | 2,04 s |
| Início do golpe | 0,00 s (pico em 0,03 s) | 0,00 s (pico em 0,04 s) |
| Som útil (queda até −45 dB do pico) | ~1,2 s | ~0,7 s |
| Pico | −2,8 dB | **0 dB (saturação provável)** |
| Preparo | cortar em ~1,3 s com fade-out | cortar em ~0,8 s com fade-out; baixar ~3 dB; checar estalo |

Passos de preparação:

1. **Renomear para nomes sem vírgula e sem `#`**: `punch_heavy.wav` e `punch_super.wav`. Nomes que começam com
   `punch` já ganham de graça o corte automático do silêncio inicial que `start()` faz hoje.
2. **Converter para WAV 44,1 kHz** (o carregador busca `/assets/boxing_audio/<nome>.wav`) e cortar a cauda longa.
3. **Igualar o nível** com `punch1`–`punch3` (média entre −15 e −18 dB) e deixar pico ≤ −1 dB, sem saturar.
4. **Adicionar os dois nomes à lista de carregamento** em `start()` e escolher o som em `impact()` pela faixa de força.
5. **Registrar em `manifest.json` e `CREDITS.md`**: origem ElevenLabs gerada pelo dono do projeto (sob os
   termos do plano dele), com a lista do que foi alterado (corte, ganho).
6. **Ouvir os dois no jogo** contra a música: o `devastador` deve se destacar sem estourar; opcionalmente a música abaixa ~0,5 s nele.

Fora desta etapa: `slight_punch_in_the__#2` (3,02 s, bem mais baixo, golpe começa só em 1,16 s) serviria
para a faixa `leve`/`toque`, mas não foi incluído agora.

### 5.7 Idioma: jogo em inglês, menus em português (opcional)

**Regra:** tudo que aparece **durante a luta** é em inglês: onomatopeias e tags de golpe (5.3), banners,
mensagens de combate, rótulos do HUD e o narrador (já é em inglês). Os **menus** (lobby, ajustes, sala online,
resultado, dicas e status de rastreamento) existem em inglês e português, e a pessoa escolhe em Ajustes.
Padrão: o idioma do navegador (`pt-*` abre em português, o resto em inglês).

Implementação: uma tabela única de textos de menu (`strings.en` / `strings.pt`) lida por `data-i18n` no
`boxing.html` e por uma função `t(chave)` no `boxing.js`. Os textos do jogo ficam fixos em inglês, fora da tabela.

O que muda no jogo (hoje em português ou em quadrinho):

| Onde | Hoje | Passa a ser |
|---|---|---|
| `WORDS` (onomatopeias) | POW!, BAM!, PÁ!, TUM!, CRACK!, BOOM!, KAPOW!, CONTRA!, TOC!, DEFESA! | removidas; tags da 5.3 |
| Banner de início | `ROUND 1 • LUTE!` | `ROUND 1` + sino |
| Banner de tontura | `TONTO!` / `TONTO! FINALIZE!` | `ROCKED` |
| Banner de fim | `EMPATE!` / `FIM DE LUTA` | `DRAW` / `TIME` |
| Defesa na guarda | `DEFESA!` | `BLOCKED` |
| Avisos (`notify`) | "No queixo!", "Contra-ataque • dano extra", "Golpe de misericórdia" | `ON THE CHIN`, `COUNTER`, `FINISHER` |
| Aviso de fígado | "Golpe no fígado • seus socos enfraquecem" | `LIVER SHOT` / `LIVER SHOT • WEAKENED` |
| Rótulo de força | `MÁXIMO! / FORTE / BOM / FRACO` | faixas da 5.3 (`DEVASTATING`, `CRUSHING`, `LANDED`, vazio) |
| Combo | `GOLPES` | `HITS` |
| HUD | `VOCÊ`, `CANTO AZUL`, `CANTO VERMELHO`, `PRONTO`, `TREINAMENTO`, `DUELO ONLINE`, `AGUARDANDO WEBCAM` | `YOU`, `BLUE CORNER`, `RED CORNER`, `READY`, `TRAINING`, `ONLINE`, `WAITING FOR CAMERA` |

Limite a combinar: o painel de dicas e o status de rastreamento ("Mostre o tronco…") contam como **menu**,
porque dão instrução à pessoa, não fazem parte da luta.

### 5.8 Menus: mostrar, não explicar

Correção de rumo: a primeira proposta só trocava um texto explicativo por outro. O problema é o próprio texto
explicativo. Street Fighter não abre dizendo "jogo de arcade para jogar com botões": quem abre um jogo de luta já
sabe o que ele é. A identidade daqui tem que vir do que o jogo **mostra e faz soar** (o boneco, a voz do Victor, o
phonk, o ringue), não de frase de apresentação.

Padrões a eliminar (todos aparecem hoje em `boxing.html`):

- **Slogans e subtítulos**: "Seu corpo. Seu combate.", "UM RINGUE. DOIS LUTADORES.", "ENTRE NO RINGUE".
- **Parágrafos que descrevem o jogo** e **cartões de "como jogar"** na tela inicial (Guarda, Velocidade, Queixo).
- **Texto de venda** dentro de Ajustes: "Impactos com peso, torcida que reage, sino e efeitos de desenho."
- **"Seu/sua" em tudo** e chamadas motivacionais: "SEU CANTO", "Entre no ritmo", "Convide seu oponente."
- **Jargão interno** na tela: "NLF-S", "Pés fora da imagem usam passos estimados".

Princípios:

1. O jogo **não se descreve**: sem slogan, subtítulo ou parágrafo dizendo o que ele é ou promete.
2. Menu é **rótulo curto**: botão com uma ou duas palavras, sem frase de apoio.
3. **Ensinar na luta, na hora certa**, e não numa lista antes dela. A guarda, o queixo e a tontura já têm tag e
   voz do narrador (5.3 e 5.5). Dicas novas, como `GUARD UP` quando a guarda está baixa e o bot ataca, ficam para depois
   (precisam de checagem nova; ver "Fora do escopo" em 5.5).
4. A única explicação obrigatória é **funcional**: como se posicionar na câmera, que não é óbvio num jogo de webcam.
   Uma instrução curta e factual ("Step back until your whole body is in frame."), mais erros claros. Sem tom, sem humor.
5. A voz do texto é de **cartaz de luta**: poucas palavras, caixa alta, secas (`ROUND 1`, `BLUE CORNER`, `RED CORNER`),
   sem "você/seu", sem exclamação.
6. Em Ajustes, só rótulo e controle. Explicação só quando houver consequência real e com número, em dica ao passar o mouse.
7. Nenhum nome interno de tecnologia na tela.

O que acontece com cada texto (o português vai em `strings.pt`; o inglês segue o mesmo princípio):

| Hoje | Proposta (PT) | Proposta (EN) |
|---|---|---|
| ENTRE NO RINGUE / Seu corpo. Seu combate. / parágrafo da tela inicial | *(remover; ficam o logo, o lutador e os botões)* | *(remove)* |
| SEU LUTADOR | Lutador | Fighter |
| Treinar ▶ / Lutar online | Treino / Online | Training / Online |
| 3 cartões: Guarda, Velocidade, Queixo | *(remover; ensinado na luta)* | *(remove)* |
| Preparando os lutadores… / Lutadores prontos • webcam + NLF | barra de progresso, sem texto; texto só se falhar | progress bar, no text; text only on failure |
| Painel SEU CANTO / Entre no ritmo + dica longa | *(remover; ficam os botões Webcam e Calibrar e o status)* | *(remove)* |
| Status: Webcam necessária • aguardando rastreamento / Mostre o tronco • deslocamento suspenso | Sem webcam / Mostre o tronco | No camera / Show your torso |
| AJUSTE SEU COMBATE / Seu estilo de luta. | Ajustes | Settings |
| Parágrafos explicativos em Ajustes (suavização, movimento, sons) | *(remover; dica ao passar o mouse só onde houver número)* | *(remove)* |
| Cartoon • sombra chapada / Clássico • materiais originais | Cartoon / Original | Cartoon / Original |
| UM RINGUE. DOIS LUTADORES. / Convide seu oponente. | Online | Online |
| Compartilhe o código e o endereço do servidor. Apenas poses e comandos entram no duelo. | Só poses são enviadas. O vídeo não sai do seu computador. *(informação, não descrição)* | Only poses are sent. Video never leaves your computer. |
| FIM DO COMBATE / Vitória! / Voltar ao seu canto | Resultado / Vitória / Voltar | Result / Victory / Back |
| CORNER CHAMPIONSHIP ★ NOITE DE GALA | *(remover)* | *(remove)* |

Observação: a explicação sobre "pés fora da imagem usam passos estimados" some junto com o passo A
(pernas 100% NLF). A opção "Cartoon + contorno" some com o passo J.

### 5.9 Menu principal

A peça central é o **recorde de força** (`PEAK`): o único texto da tela além de rótulos. Ele vem do que o jogo tem
de diferente, a força do soco medida em newtons, e dá motivo para voltar sem nenhum texto de apresentação (5.8).

```
┌──────────────────────────────────────────────┐
│ HEAVY HANDS                      Ajustes   │
│                                            │
│       (lutador em guarda, no ringue)       │
│                                            │
│   ‹  PRISM  ›                              │
│                                            │
│   PEAK   1.468 N                           │
│                                            │
│   Treino                  Online           │
│   ● Webcam ligada                          │
└──────────────────────────────────────────────┘
```

- **Cabeçalho:** o nome do jogo como logotipo (arte ainda a definir; o logo atual é do CORNER) e o botão Ajustes.
- **Centro:** o lutador escolhido em guarda, no ringue, com o 3D do próprio jogo; as setas trocam de lutador.
- **`PEAK`:** maior força de um golpe que **acertou o oponente** (treino ou online), salvo no navegador
  (`localStorage`). Soco no ar não conta. É o valor do jogo, na mesma escala dos newtons do dano (5.2), sem correção.
  O número segue o idioma (1.468 em português, 1,468 em inglês). Sem recorde ainda, a linha não aparece.
  É um recorde geral da pessoa, não um por lutador.
- **Ações:** `Treino` (principal) e `Online`.
- **Webcam:** `● Webcam ligada` / `○ Sem webcam`. Clicar liga a câmera. Sem webcam, Treino fica desativado e o
  próprio chip diz o motivo (a instrução funcional da 5.8).
- **Som (opcional):** ao apertar Treino, o Victor diz "GUARD UP." (`pressure_guard_up`) antes do sino. Aqui não precisa
  de detecção nova, só tocar no clique.
- **Resultado:** a tela de fim de luta mostra as estatísticas de força da 5.10; se bateu o recorde, a tag `NEW PEAK`.

Depende do passo G (força em newtons) e do K (textos). Até o G existir, a linha `PEAK` não aparece.
Aceite: menu sem recorde mostra só rótulos; depois de um golpe de 1000 N que acertou, recarregar a página mostra
`PEAK 1.000 N`; um golpe de 1500 N no ar não altera o recorde.
Em aberto: arte do logotipo e se o seletor de lutador fica abaixo do boneco ou ao lado.

### 5.10 Estatísticas do fim da luta

Hoje a tela de resultado (`finish()` em `boxing.js`) mostra quatro números: golpes limpos, maior combo, golpes no
queixo e soco mais rápido (m/s). Com a força em newtons (passo G), o resultado passa a contar a luta pela força.

**Destaques (cartões grandes):**

| Estatística | O que é | Exemplo |
|---|---|---|
| `PEAK` da luta | maior força de um golpe que acertou, com a equivalência em kgf (kgf = N ÷ 9,81) | 1.468 N ≈ 150 kgf |
| `TOTAL FORCE` | soma da força de todos os golpes que acertaram, em kN | 18,4 kN |
| `AVERAGE` | força média dos golpes que acertaram | 512 N |
| `ACCURACY` | golpes que acertaram sobre golpes dados | 41 de 63 (65%) |

**Linha de apoio (menor):** golpe mais forte na cabeça e no corpo; maior combo e a força somada dele; quantos
golpes em cada faixa (`LANDED`, `CRUSHING`, `DEVASTATING`); soco mais rápido (m/s); golpes no queixo; defesas;
golpes por minuto; dano recebido e o golpe mais forte que você tomou.

**Gráfico da luta:** uma barra por golpe ao longo do tempo, com a altura na força e a cor na faixa. Mostra de
um olhar onde a luta esquentou. É feito com barras em CSS, sem biblioteca. Se bateu o recorde, a barra mais alta
ganha a tag `NEW PEAK` e a comparação com o recorde anterior.

Dados: registrar cada golpe como `{t, mão, força, alvo, faixa, acertou, combo}`. Os golpes dados vêm do detector de
soco (novo, no passo G) e os que acertaram vêm de `simulate`. A estimativa vem da câmera, então o número tem uma
dica curta ao passar o mouse dizendo isso (sem texto fixo na tela, pela 5.8).
Aceite: nenhum `NaN`; sem golpe que acertou, as estatísticas mostram `–`; `PEAK` = maior valor do registro e
`TOTAL FORCE` = soma dele.

### 5.11 Som ao cair: ouvido tampado

Hoje `hurtMuffle` e o abafamento de tontura (`setState`) só filtram a **música** (`musicFilter`); a torcida, os efeitos
e o narrador seguem nítidos. E `ko()` toca três sinos e faz a torcida rugir, até quando é você quem cai. Para a sensação
de ouvido tampado, o efeito vale quando a vítima do nocaute é você (`ko.victim === self`) e, no futuro, em qualquer
knockdown com contagem. Para o vencedor, nada muda.

```
Golpe final    estalo agudo; o som do mundo some em ~60 ms (−18 dB)
Queda (~0,8 s) baque grave no chão (subgrave ~45 Hz)
0–3 s          mundo abafado: filtro de 18 kHz até ~300 Hz
               zumbido agudo de 3,9 kHz, bem baixo, com tremolo leve
               batimento cardíaco ~60 bpm
               a voz do Victor atravessa o abafamento (+6 dB)
3–6 s          o filtro abre devagar, o zumbido some
```

- **Barramento do mundo:** música, torcida, efeitos e voz passam por um filtro passa-baixa de "mundo" antes do
  `master`. O zumbido e o batimento ficam fora dele. Hoje só a música é filtrada.
- **Curva:** fecha em ~80 ms; reabre em ~3 s, exponencial. O resultado já aparece com o som quase normal.
- **Para quem cai:** um sino abafado em vez dos três, torcida baixa, música no nível `ko` de hoje (0,18) com o
  tom caindo ~7% (o `wobble` já existente).
- **Visual (opcional):** vinheta fechando e leve dessaturação por ~2 s, junto do som.
- **Cuidado:** zumbido baixo (−30 dB) e curto (menos de 4 s). Opção em Ajustes para desligar o zumbido e o
  abafamento (som de impacto reduzido).
- **Implementação:** novo método `earPlug(segundos)` em `boxing_audio.js`, chamado em `finish()` quando `victim === self`.
  Reaproveita `hurtMuffle`, `ring` e `heartbeat`.
Aceite: ao cair, a energia acima de 2 kHz na saída cai pelo menos 20 dB em 100 ms e volta ao normal em até 4 s; o
zumbido e o abafamento só acontecem para o perdedor; com a opção desligada, o som não muda.

---

## 6. Como medir cada passo

| Métrica                                   | Hoje         | Meta                                              |
| ----------------------------------------- | ------------ | ------------------------------------------------- |
| % de golpes marcados DEFESA (luta 11 min) | 50%          | o que o vídeo mostra (perto de 0 sem guarda real) |
| Potência ≥ 95%                            | 73%          | ~6% (faixa devastador)                            |
| Fase "só punho" (benchmark)               | 87% médio    | ≤ 15%                                             |
| Socos reais detectados (benchmark)        | 50/67        | ≥ 64/67                                           |
| Movimentos falsos detectados              | 25           | ≤ 3                                               |
| Altura do esqueleto nos primeiros 25 s    | 1,10 m       | igual ao resto (±3 cm)                            |
| Distância entre luvas na guarda           | 1,15× a real | ≈ 1,0×                                            |
| Ângulo punho–antebraço                    | torto        | < 10°                                             |
| Sola × canvas                             | voa/afunda   | ±2 cm                                             |

Comandos:

```
python scripts/analyze_punch_power.py ../debug_luta/corner-debug-2026-10-02T15-07-23-920Z 80
python scripts/benchmark_punch_power.py benchmarks/punch_cadence_20261002.mp4 80
node scripts/test_boxing_core.mjs
python scripts/test_boxing_combat_e2e.py
python scripts/test_boxing_footwork.py
```

---

## 7. Riscos e pendências

- **Profundidade do NLF é ruidosa**: a parte "corpo avançando" da força usa justamente o eixo que mais erra.
  Mitigado pela regressão de 150 ms e por só contar velocidade na direção do alvo.
- **Escala absoluta** em newtons é estimativa (D4). `PUNCH.tierScaleN` recalibra as classificações e
  `PUNCH.damagePerN` o balanceamento, sem mexer no teto `maxN`.
- **Codex** editando os mesmos arquivos: pausar antes de começar.
- Benchmark extra sugerido (não obrigatório): séries rotuladas fraco/médio/forte e "só braço" vs
  "com passo e quadril", para confirmar a ordem.

---

## 8. Nome do jogo: HEAVY HANDS

Decidido. "Heavy hands" é gíria de boxe para quem bate com a mão pesada, e combina com a força medida em
newtons, que é o que o jogo tem de diferente. **Pendente:** checar se o nome está livre (marca, domínio, lojas);
isso não foi verificado.

- **Muda (visível):** `<title>`, logo e `aria-label` de `boxing.html`, o subtítulo "WEBCAM BOXING" (sai, pela 5.8),
  a sala padrão `CORNER1` (vira `HEAVY1`), `CREDITS.md` e o README.
- **Não muda:** `BLUE CORNER`/`RED CORNER` do HUD (são termos de boxe), os arquivos `boxing_*` e as chaves internas do
  navegador (`cornerToon`, `cornerVolume`, `cornerAudio`); renomeá-las apagaria os ajustes salvos de quem já usa.
- **"Heavy" virou o nome do jogo:** o rótulo da faixa de 900–1150 N passa de `HEAVY` para `CRUSHING` (5.3 e 5.7).
  O clipe do narrador `hit_heavy` continua; é só a voz dizendo a palavra.
- **Descartados:** CORNER, SHADOWBOX, GUARD UP, RAW ROUNDS, TELL, GLASS JAW, TEN COUNT, ON THE ROPES.
