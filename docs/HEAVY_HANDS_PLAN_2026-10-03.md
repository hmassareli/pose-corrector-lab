# HEAVY HANDS — Plano 2 (03/out/2026)

Pré-requisito: **uma ferramenta editando por vez.** Em 02/out 22:51 o Astra ainda estava gravando
`viewer/boxing.js` e `viewer/boxing_hands.js`. Pausar o Astra antes de começar.

Termos:

- **Grupo / modelo**: o avatar tem duas "caixas" aninhadas. O _grupo_ fica no ringue (posição do lutador);
  o _modelo_ fica dentro dele (o corpo em si). Mover qualquer um move o corpo na tela.
- **IK (cinemática inversa)**: calcular ombro e cotovelo para a mão chegar num ponto.
- **Punho reto**: a luva continua na direção do antebraço, sem "quebrar" no pulso.
- **Rastro (trail)**: faixa de luz que segue a luva rápida, como nos jogos de luta.
- **Game feel / "sugar"**: os pequenos exageros que dão peso ao golpe (pausa no impacto, tremida, som, rastro, partícula).

Ordem: primeiro o que **quebra** (1–3), depois a sensação (4–6).

## Status (02/out 23h30)

| Item | Status | Medição |
| --- | --- | --- |
| 1 Chão único | FEITO (`plantGround:false` na luta) | 75 s: modelo fixo em 1,05 m (antes −128 m); lateral com tontura 13 cm (antes 6,6 m); salto máx. 5 mm |
| 2 Punhos | FEITO (eixo reserva espelhado) | dobra luva×antebraço 0° em guarda/jab/gancho/cotovelo alto; palma 4–7° do rosto na guarda |
| 3 Calibração | FEITO: sem espera; 1ª pose plausível já joga, escala refina 4 s | `test_boxing_core` PASS |
| 3 Espera de 25 s | FEITO: YOLO numa thread fixa aquecida (1ª convolução CUDA por thread nova custava ~26 s) | 1ª pose por conexão: 26–33 s → 0,7 s |
| 3 Botão | FEITO: Treino liberado ao carregar e liga a câmera; chip "Turn on webcam" | — |
| 4 Layout | 3 propostas em `experiments/layout_mockups/layout_{a,b,c}.png`, aguardando escolha | — |
| 5 Sugar | FEITO: rastro em todo soco detectado (cor/espessura por força), zoom curto em golpe ≥ médio | — |
| 6 Queixo | `test_boxing_combat_e2e` PASS (não reproduziu) | — |
| — | Texto corrompido (`Â·`, `â€“`) na tela de resultado/combo corrigido | — |

---

## 1. Mola lateral no atordoamento (bug de chão) — PRIORIDADE MÁXIMA

Causa (confirmada pelo Astra e pelo avaliador):

```
retarget (plantGround) ── desce o MODELO usando o grupo do quadro anterior ──┐
jogo ─── redefine a posição do GRUPO                                          │ acumulam em
groundSoles ── sobe o GRUPO pelas solas                                       ┘ sentidos opostos
                         modelo −128 m  /  grupo +129 m  →  pés "certos" na tela
tontura ── gira o grupo ── o deslocamento de 128 m vira balanço lateral de até 6,6 m
```

Correção: **um único dono do chão.**

- `boxing.js` (`renderActor`, ~linha 1779): `plantGround: false` na luta e zerar `a.root.position.y` (posição de
  descanso) antes do retarget a cada quadro. O chão fica só com `groundSoles`.
- Balanço de tontura/atordoamento girando em torno da pelve, não da origem do grupo.

Aceite (teste novo, porque o atual só olhava a sola final):
`|modelo.y| < 5 cm` e `|grupo.y − 0,026| < 5 cm` após 75 s simulados; deslocamento lateral do quadril
com tontura < 8 cm; nenhum salto entre quadros > 5 cm.

## 2. Punhos dobrados e luva virada para fora

Casos enviados: (a) tela inicial, luva esquerda com a palma para fora; (b) e (c) jab/gancho com o punho
quebrado em relação ao antebraço.

Causa principal (CORRIGIDA 02/out 23h): **mão direita espelhada errado.** Os avatares não têm ossos de dedo
(PRISM nenhum; o oponente só o indicador), então `prepareHands` usava o eixo reserva `(1,0,0)` igual nas duas
mãos e depois invertia só a palma da direita. Como os ossos de mão Mixamo já são espelho um do outro em X,
a direita ficava do avesso. Correção: eixo reserva espelhado (`-1` na direita). Medido: palma local agora
`[0,0,-1]` nas duas mãos, igual à malha; menu com luvas simétricas.

Restante a verificar:

1. `avatar_self_contact.js`: o IK do contato com o rosto já chama `alignWrists` (o Astra corrigiu); não é causa.
2. `boxing_hands.js` `alignWrist`: a palma usa "para trás do lutador" + eixo lateral fixo. A direção real do
   rosto só entra como fallback. Avaliar no jab/gancho se precisa da bissetriz real (luva → rosto, luva → outra luva).

Aceite (teste visual + numérico em 4 poses: guarda do menu, guarda NLF, jab estendido, gancho com cotovelo alto,
em todos os avatares):

- ângulo luva × antebraço < 10°;
- palma a 45° ± 15° entre rosto e outra luva na guarda;
- simetria esquerda/direita: diferença < 10°;
- print antes/depois em `experiments/wrist_fix/`.

Futuro (pergunta do plano 1): detectar dobras feias automaticamente **é possível**: medir por quadro o ângulo
entre ossos vizinhos e a distorção dos vértices (quanto o _skinning_ encolhe o volume). Acima de um limite,
corrigir a rotação. É viável, mas como segunda fase, depois de 1–3.

## 3. Webcam e calibração

Hoje: o botão da câmera fica embaixo e parece rótulo; a primeira pose demorou ~25 s e o jogo bloqueia até a
calibração estável. Quem joga acha que está quebrado.

- **Jogar sem calibrar**: começar com escala padrão (altura 1,72 m) assim que chegar a 1ª pose válida.
  Calibração refina em segundo plano (média móvel da altura), sem bloquear. Botão "Calibrar" vira opcional.
- **Webcam automática**: pedir a câmera ao abrir o jogo (ou no 1º clique em Treino). Treino nunca
  fica cinza sem explicação: se faltar câmera, o clique liga a câmera.
- **Status visível**: chip grande no centro com etapas reais: "Abrindo câmera → Procurando você → Pronto".
- **Primeira pose rápida**: aquecer o YOLO no `load()` do servidor (o 1º `detect` custava ~25 s).

Aceite: do clique até o avatar mexer < 3 s com servidor aquecido; nenhum botão desabilitado sem texto dizendo
o motivo.

## 4. Layout: sério, mas não vazio

Pedido: menos infantil que o antigo, mas com presença. O atual ficou "sem sal".

- Manter: nome HEAVY HANDS, fundo escuro, PEAK, menus PT/EN.
- Voltar a ter energia: luz de ringue (holofote no lutador), cor de destaque forte (vermelho-sangue
  ou dourado saturado), sombra e textura (lona, metal), ícones nos botões.
- Botões grandes e óbvios: **TREINO** e **ONLINE** como botões principais; câmera como chip com ícone e
  estado, perto deles, não no rodapé.
- Card do lutador: nome, apelido, 2–3 atributos (alcance, peso), setas grandes para trocar.
- Tela de carregamento com dica curta enquanto o NLF aquece.
- Referência de tom: menus de _Fight Night_ / _Creed_, não de jogo infantil.

Aceite: 3 propostas em prints (sem código final) para você escolher antes de implementar.

## 5. "Sugar" (sensação dos golpes)

Já existe: rastro (`boxing_fx.js`), hit-stop, tremida, onomatopeia, sons. Na prática, quase não aparece.
Verificar primeiro se está sendo desenhado (pode estar desligado pelo limite de velocidade ou pelo modo).

- Rastro da luva sempre visível em soco detectado; cor e espessura pela força (faixa da seção 5.3 do plano 1).
- Hit-stop proporcional (40–120 ms), _zoom_ curto da câmera no impacto forte.
- Faíscas/poeira de suor no impacto; flash na luva do bloqueio.
- Câmera lenta curta em DEVASTATING e no KO.
- Contador de combo com "pulso".

Aceite: vídeo lado a lado antes/depois, mesma sequência de golpes.

## 6. Pendências do Astra

- Regressão do queixo: golpe no queixo registrado como acerto comum, sem tontura. Corrigir e rodar
  `test_boxing_combat_e2e.py`.
- Legendas do Victor: otimização sem validação. Rodar o teste e conferir no vídeo.
- Nota 9,18 do avaliador não vale para a versão atual: refazer a avaliação depois dos itens 1–3.

---

| Ordem | Item              | Risco se adiado                  |
| ----- | ----------------- | -------------------------------- |
| 1     | Chão único (mola) | corpo voando em todo golpe forte |
| 2     | Punhos            | visual quebrado o tempo todo     |
| 3     | Webcam/calibração | jogador acha que não funciona    |
| 4     | Layout            | primeira impressão fraca         |
| 5     | Sugar             | jogo funciona, mas sem impacto   |
| 6     | Pendências        | regressões escondidas            |
