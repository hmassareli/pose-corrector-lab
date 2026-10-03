# Avatar 3D: Fluidez e Corretude

Este documento registra as regras para o avatar 3D do Pose Corrector Lab. Ele existe para impedir que um ajuste visual local esconda mistura de fontes, perda de dados ou deformacao anatomica.

> Escopo: estas regras tratam da renderizacao do avatar. Elas nao mudam nem invalidam o contrato atual de treino do corretor: o treino usa pares MediaPipe/Teacher no mesmo frame a 30 Hz, Teacher alinhado no tronco e residual de ombro, cotovelo e punho no referencial corporal do MediaPipe. Pes nao fazem parte dos 18 valores que o corretor aprende hoje.

## Termos basicos

- **Fonte de pose:** sistema que produziu uma medida corporal, por exemplo MediaPipe ou Teacher (GVHMR).
- **Retargeting:** transferencia de uma pose medida para os ossos de outro corpo, neste caso o rig Mixamo do avatar.
- **Rig:** hierarquia de ossos que deforma o avatar.
- **Pose de repouso:** orientacao e posicao originais dos ossos no FBX, antes de qualquer pose ser aplicada.
- **Payload:** arquivo JSON que o viewer recebe para desenhar um clip.
- **Referencial do corpo:** eixos definidos pelo proprio corpo: direita-esquerda pelos ombros, cima-baixo pelo tronco e frente-costas pelo produto entre esses vetores.

## Regra principal: uma fonte por pose

O avatar deve declarar qual fonte o dirige e nao pode misturar fontes silenciosamente.

```text
Modo Teacher aligned
  teacher: tronco, bracos, pernas, pes

Modo MediaPipe
  MediaPipe: tronco, bracos, pernas, pes

Modo Corrector exportado
  corrector: juntas que ele corrige
  MediaPipe: somente juntas que o corretor nao produz
```

Usar `Teacher` para quadril, joelho e tornozelo, mas `MediaPipe` para ponta do pe, e uma mistura de fontes. Mesmo que deixe o sapato mais bonito em um frame, pode criar uma pose incoerente.

### Excecao temporaria

Uma mistura so pode existir quando todas estas condicoes forem verdadeiras:

1. O viewer mostra explicitamente que ha duas fontes.
2. O codigo a trata como um modo de depuracao, nao como pose Teacher pura.
3. A documentacao registra por que o dado ausente nao foi exportado da fonte principal.
4. Existe uma tarefa para remover a mistura exportando o dado correto.

## Contrato de dados do viewer

O payload atual do lab reduz cada pose para 16 juntas. Ele termina em tornozelos e, por isso, nao contem calcanhar, ponta do pe nem rotacao do pe.

```text
Teacher bruto (GVHMR / SMPL-X)
  possiveis juntas e rotacoes adicionais
              |
              v
Teacher aligned payload atual
  16 juntas: ... joelho -> tornozelo
              |
              v
Avatar offline
  nao pode conhecer a direcao do pe sem dado adicional
```

Consequencias:

- Nao inventar uma direcao de pe a partir da abertura do joelho. Um pe apoiado pode continuar reto enquanto o femur gira no quadril e abre o joelho; esse era o caso anatomico mais provavel no frame de referencia.
- Antes de usar um dado adicional, verificar se ele ja existe no Teacher bruto e exporta-lo do Teacher.
- Se o Teacher nao tiver a orientacao necessaria, o viewer deve deixar isso claro ou usar uma inferencia marcada como aproximacao.
- Dados auxiliares devem ter `source`, nomes de juntas, FPS e numero de frames. Nunca pressupor que dois arquivos estao alinhados apenas porque possuem o mesmo clip ID.

### Export completo do MediaPipe

Cada clip MediaPipe agora preserva, alem do esqueleto legado de 16 juntas usado pelo treino atual:

| Arquivo | Shape | Conteudo |
|---|---:|---|
| `landmarks33_world.npy` | `(T, 33, 3)` | os 33 pontos 3D nativos do MediaPipe Pose |
| `landmarks33_image.npy` | `(T, 33, 3)` | coordenadas normalizadas da imagem (`x`, `y`, `z`) |
| `landmarks33_conf.npy` | `(T, 33)` | visibilidade/confianca por ponto |

`T` e identico ao de `joints3d.npy` no mesmo clip. Os indices relevantes para o avatar incluem nariz `0`, orelhas `7/8`, ombros `11/12`, quadris `23/24`, tornozelos `27/28`, calcanhares `29/30` e pontas `31/32`.

Esses arquivos sao uma camada adicional para viewer e retargeting. Eles nao alteram `joints3d.npy`, `conf.npy`, `joints2d.npy`, `paired/`, datasets, checkpoints nem as metricas de treino de bracos existentes.

## Prioridade para pes offline

Quando for corrigir pes em modo Teacher, seguir esta ordem:

1. Exportar do Teacher a rotacao do osso do pe, se estiver disponivel no resultado GVHMR/SMPL-X.
2. Caso nao haja rotacao, exportar uma junta de pe do Teacher que permita obter `tornozelo -> pe`.
3. Como fallback visual declarado, manter a orientacao de repouso do pe; nao deduzir abertura ou yaw a partir de joelho, quadril ou tronco.
4. Nunca usar MediaPipe para completar uma pose apresentada como Teacher puro.

`Calcanhar -> ponta` do MediaPipe e um dado util para o modo MediaPipe e para comparar fontes, mas nao deve ser aplicado automaticamente ao avatar Teacher.

## Conversao de referencial

Vetores de duas fontes nao podem ser copiados diretamente. Cada sistema pode ter frente, profundidade e escala diferentes.

```text
vetor do pe no MediaPipe
          |
          v
base local do tronco MediaPipe
  direita, cima, frente
          |
          v
base local do tronco alvo
  direita, cima, frente
          |
          v
rotacao do osso do pe do avatar
```

Mesmo com essa conversao, a pose continua uma mistura se a base alvo for Teacher e o vetor vier de MediaPipe. Converter coordenadas resolve eixos; nao torna duas estimativas independentes na mesma estimativa.

Isso e diferente do pareamento do treino. No treino, as duas estimativas sao observacoes do mesmo frame do mesmo video e sao colocadas em um contrato comum antes de calcular o residual dos bracos:

```text
MediaPipe e Teacher do mesmo video
  |
reamostrar ambos para 30 Hz
  |
alinhar Teacher por tronco: translacao + escala
  |
referencial corporal do MediaPipe
  |
residual somente de ombro, cotovelo e punho
```

Nao ha vetor de pe do MediaPipe sendo copiado para o Teacher nesse caminho. O alinhamento preserva a rotacao do tronco do Teacher; ele remove apenas diferencas globais de translacao e escala para tornar o residual de braco comparavel.

## Retargeting anatomico

### Pose de repouso e eixos reais do FBX

- Cachear orientacao, posicao e eixo local de cada osso quando o FBX carrega.
- Comecar cada frame da pose de repouso. Acumular rotacoes de frame em frame causa deriva, tremor e membros torcidos.
- Ossos do tronco (quadril, coluna, pescoco, cabeca) misturam a forca do retarget em relacao a uma referencia **ereta canonica**, nao ao repouso bruto. Personagens sao autorados em poses neutras diferentes — o `fighter-web` ja vem com o tronco inclinado ~21° e o pescoco ~52° para frente — e misturar em direcao ao repouso deixava essa inclinacao no resultado (avatar corcunda ao lado de um rig T-pose na mesma pose). Com a referencia ereta, `strength` significa "quanto do alvo a partir do neutro", independente da pose de autoria. Rigs T-pose nao mudam (repouso ≈ ereto).
- Medir o eixo real de cada osso e o pivo do pe. Nomes de osso nao dizem onde fica a ponta visual do sapato.
- Nunca assumir que o eixo local `Z` de todo FBX aponta para frente.

### Bracos e pernas

- Resolver coxa-perna e braco-antebraco como cadeias de dois ossos.
- Preservar o angulo do joelho/cotovelo, em vez de apontar os dois ossos diretamente ao tornozelo/punho. Isso evita pernas esticadas em poses agachadas.
- O joelho define a dobra da perna; ele nao define a rotacao do sapato. A abertura lateral do joelho pode vir da rotacao da coxa no quadril, mantendo o pe plantado e apontando para frente.
- A cadeia `quadril -> joelho -> tornozelo` posiciona coxa e canela, mas tres pontos nao revelam a torcao ao redor do eixo da canela. Logo, eles nao bastam para decidir o yaw do pe.
- Claviculas, quadril e coluna precisam participar da pose. Mover somente bracos e pernas deixa ombros comprimidos e tronco rigido.

### Pes

- Sem dados confiaveis de inclinacao, aplicar somente yaw, isto e, giro ao redor do eixo vertical do chao.
- Nao construir inclinacao completa com tres pontos incertos. Isso causou pes levantados, virados ou atravessando o chao.
- Nao impor abertura externa minima. Sem uma medida de direcao do pe, manter o sapato para frente e deixar a cadeia da perna representar a rotacao da coxa no quadril.
- Validar o contato: sola plana, tornozelo sem deslocamento inesperado e nenhum pe flutuando.

## Fluidez temporal

Fluidez nao e aplicar um filtro forte. Primeiro a pose deve estar correta; depois a transicao deve ser limitada.

1. Usar timestamps/FPS reais e preservar a associacao frame a frame entre video e pose.
2. Rejeitar ou manter a ultima orientacao valida quando uma junta essencial estiver ausente ou degenerada.
3. Suavizar posicoes e rotacoes separadamente. Rotacoes usam interpolacao esferica (slerp), isto e, uma transicao de orientacao sem acelerar por um eixo errado.
4. Usar pouca suavizacao para punhos e pes em contato; atraso excessivo faz o avatar parecer atrasado em relacao ao video.
5. Resetar o estado de suavizacao ao trocar clip, fonte, avatar ou ao voltar para um frame distante.
6. Nunca usar suavizacao para mascarar troca de fonte, erro de eixos ou osso errado.

## Carregamento e modos

- O FBX deve carregar sem tocar animacoes embutidas. O avatar segue apenas a pose recebida.
- Arquivos auxiliares opcionais devem carregar depois de o esqueleto/payload principal estar pronto. Uma busca lenta ou inexistente nao pode impedir o viewer de montar o primeiro frame.
- Respostas assincronas antigas nao podem alterar um clip novo; proteger carregamentos por geracao/ID do clip.
- O avatar cinza de sombra deve usar a mesma fonte declarada do avatar principal, salvo modo de comparacao explicitamente habilitado.

## Validacao obrigatoria

Uma contagem de ossos mapeados ou ausencia de excecao JavaScript nao prova que o avatar esta correto.

Para cada mudanca de retargeting, validar:

1. Frame parado com joelho dobrado e base aberta.
2. Frame com ambos os pes em contato com o chao.
3. Frame com um pe levantado.
4. Movimento curto reproduzido para frente e para tras.
5. Pelo menos uma vista frontal e uma lateral/orbitada.
6. Comparacao lado a lado com o frame real do video.
7. Fonte, FPS e numero de frames de todo dado auxiliar.

Registrar junto ao resultado:

```text
clip + frame + fonte selecionada + dados auxiliares usados
```

## Estado atual (MiKaPo port)

O avatar Mixamo usa retarget **FK estilo MiKaPo** em `viewer/mikapo_mixamo_solver.js` (ambos `index.html` e `live.html`):

- reset para rest pose a cada frame
- direcao parent/root + `FromUnitVectors`
- **roll witness** em bracos/coxas (antebraco/canela fixam o plano de dobra)
- One-Euro nos quaternions locais
- **pe flat** (mesmo sinal ankle→toe, so sem componente vertical) + `plantAvatarOnGround`
- **cabeca** ears/eyes do Pose-33 (`/api/pose-aux.json` / live aux)
- **mao** pronacao no `ForeArm` (across = indicador/mindinho); `Hand` aponta wrist→knuckles com o mesmo across. Sem dedos, nao ha twist — nunca `hand×forearm`.

| Modo | Pes | Cabeca/mao aux |
|------|-----|----------------|
| MediaPipe | `foot_landmarks.json` MP | pose-aux MP |
| Corrector | pes MP | pose-aux MP |
| Teacher aligned | `export_teacher_feet.py` | sem aux MP (nao misturar face) |

```bash
python scripts/export_teacher_feet.py --split test
```

Referencia upstream: `external/mikapo_port/` + `PORT.md`.
## Tronco torto: encurvamento vs torcao (medido)

Duas falhas distintas, com sintomas parecidos ("tronco torto") e causas
independentes. Diagnosticar uma nao resolve a outra.

**Encurvamento (hunch).** Rigs sao autorados em poses neutras diferentes:
`fighter-web` vem com a coluna 19,7-21,1° fora da vertical e o pescoco 54,4°,
contra 7,3° / 26,2° do boxeador (`probe_trunk_rest.py`). Com `strength < 1` o
blend ia em direcao ao rest CRU, entao essa inclinacao autorada vazava em todo
frame. Corrigido com `restUprightInRoot`: os ossos do tronco misturam a partir
da orientacao ERETA canonica, entao `strength` passa a significar "quanto do
alvo a partir do neutro". Rigs T-pose ficam iguais (rest ≈ ereto).**Encurvamento — causa raiz (off-by-one da cadeia).** O retarget misturava os
3 ossos de coluna do rig com apenas os 3 segmentos SUPERIORES da cadeia SMPL-X
(`spine1→spine2→spine3→neck`, descartando `pelvis→spine1`). Cada osso do rig
recebia a direcao do segmento ACIMA do que ele ocupa; num tronco curvado cada
segmento inclina mais que o de baixo, entao o erro acumula na cadeia — medido
como **+9,3° de inclinacao excedente** (avatar 28,0° vs fit 18,7°) nos DOIS
personagens, independente de rig. Corrigido mapeando a cadeia completa
(`pelvis→spine1→spine2→spine3→neck`) com parametrizacao continua (osso i cobre
[i*seg/count, (i+1)*seg/count], interpolado entre waypoints): erro cai para
**-0,9° / -1,0°**. Resample com `Math.round` REJEITADO: pula o segmento
`spine1→spine2` inteiro e piora a deformacao de bind do `spine1` (47°).
`probe_torso_twist.py` mede as duas grandezas (inclinacao e bind deviation).

**Torcao (twist).** `probe_spine_kink.py` mede a linha pelve→pescoco e angulos

de dobra — ambos INVARIANTES a rotacao em torno dessa linha. Ou seja, e cego
para torcao, que e justo o que se ve como "torto". `probe_torso_twist.py` mede
o angulo horizontal quadril→ombros do avatar contra o do fit (grandeza livre de
convencao de rig: nao ha constante a subtrair). A/B confirmou que a referencia
ereta move a torcao em 0,1° — ela nao trata esse eixo.

Causa achada e corrigida: a cadeia do tronco nao nomeava seu filho de
referencia, entao o eixo de aim vinha de `children[0]`. `Spine2` tem tres
filhos; no boxeador o exportador lista `LeftShoulder` primeiro, deixando o eixo
"ao longo da cadeia" 26,5° fora da vertical (0,42 lateral). Com childAliases
nomeados: vies constante do boxeador **-3,6° → -1,0°**; `fighter-web` (que lista
`Neck` primeiro) inalterado em +4,8°, servindo de controle. `check_body_fidelity`
sem regressao (spine 1,4 / spine1 2,0 / spine2 1,5).

**Hipotese REJEITADA** — dar a cada osso do tronco seu eixo lateral autorado em
vez do across de ombros compartilhado. O across e uma medida entre lados, e no
`fighter-web` os ombros estao 9,5° girados em relacao a pelve no rest, entao a
lombar herda o giro da cintura escapular. Parecia certo; medido, PIOROU
(+4,8° → +6,2°, controle boxeador -3,7°). Nao adotado. Ver
`probe_torso_twist.py --authored-across`.

**Aberto:** o vies de +4,8° do `fighter-web` nao foi explicado. Nao e a coluna
(controle acima) — os candidatos restantes sao o solve de clavicula
(`applyShoulderFromSmpl`, que move os ossos do braco usados na medida) e a
deformacao de skinning da malha. Note que o espalhamento (std ~10°) e MAIOR que
o vies nos dois personagens, entao parte do que se ve e rastreio, nao constante.

**Coluna em S ("osso torto" no live) — causa raiz e correcao (17/ago/2026).**
Sintoma: SkeletonHelper mostrava `spine`→`spine1` com kink de 25-51° (pior
sentado/inclinado), lido como "osso torto". Diagnostico em
`experiments/bone_crook/`: (1) as juntas INTERNAS `spine1/2/3` do NLF x55 cru ja
oscilam 20-40° por segmento com sinal ALTERNADO (zig-zag de ruido, nao anatomia —
curva sagital real nao alterna sinal por segmento); (2) o fit SMPL-X mantem ou
amplifica (+3-9°) — residuo fit-vs-x55 de 170-290 mm nos frames normais indica
fit mal convergido; (3) a MESH do fit nao mostra o S porque a pele (LBS) faz
media de varios ossos e os segmentos `spine2→spine3` tem so ~6-7 cm (wiggle de
3-5 cm vira 30-40° de angulo, mas quase nada de superficie). O avatar expunha o
ruido porque o solver copiava a DIRECAO de cada segmento com ~1° de erro.

Correcao em `updateAvatarPose`: cadeia `pelvis→spine1→spine2→spine3→neck`
construida ANTES do hips; 2 passadas de suavizacao Laplaciana (0.5) nos
waypoints internos quando `aux.kind==="smpl"`; hips passa a mirar o primeiro
segmento da cadeia (em vez de `-hipCenter`, que discordava 17-30° por frame).

A/B (mesma sequencia, `_solver_spine_zigzag.js` = baseline, NAO o HEAD do git):

| medida | antes | depois |
|---|---:|---:|
| kink hips→spine (4 frames) | 16-30° | 2.5-5.6° |
| kink spine→spine1 (sit/lean) | 35° / 51° | 15.6° / 23.6° |
| bind deviation tronco (soma) | 148.5° | 94.2° |
| hips swing_raw / swing_var | 31.0° / 6.7° | 15.6° / 3.6° |
| spine swing_raw / swing_var | 24.6° / 4.1° | 16.0° / 3.2° |
| spine1 swing_raw / swing_var | 26.4° / 3.6° | 35.4° / 4.0° |
| pes/maos/bracos/neck | — | inalterados (controle) |

Tradeoff consciente: `spine1` afasta-se do segmento cru do fit (que e o ruido
sendo removido) e a inclinacao media do tronco fica -6.0° vs fit (antes -2.2°) —
a suavizacao corta um pouco de bend real extremo. Curvas reais sustentadas sao
preservadas (lean 1052: kink spine→spine1 residual 23.6° = bend real).

**Pescoco torto + ombros assimetricos (17/ago/2026).** Diagnosticos em
`experiments/bone_crook/neck_*.json` e renders `neck_*_front.png`:

1. **Pescoco torto: bend concentrado numa juncao.** `applyHeadFromSmpl` mirava
   neck (0.75) E head (0.9) no MESMO vetor `basis.up` (neck→head), que carrega
   um kink real de 25-29° do NLF logo apos o spine2 endireitado pelo de-zigzag.
   Resultado: neck bind 21-35° vs head 4-7° — a dobra inteira acumulava na base
   do pescoco. Correcao: neck mira no PONTO MEDIO da cadeia
   (`spine3-dir.lerp(basis.up, 0.5)`), head continua no `basis.up` (gaze
   inalterada). Medido: bind neck 21.6→16.0° (em pe), 28.9→18.1° (sentado),
   kink neck→head 4.5→9.7° (dobra distribuida), fidelity neck twist 9.0→7.7°,
   todos os outros ossos inalterados.
2. **Ombros diferentes: o DADO e assimetrico (nao o solver).** NLF no frame
   "mid": elevacao clavicula L 18.2° vs R 38.0° (ombro direito realmente
   levantado). bindDeg R 58° vs L 23° e o solver seguindo o dado. O bug real
   era menor: `latU` entrava NAO-normalizado na composicao esferica do alvo em
   `applyShoulderFromSmpl` (mistura de vetores unitarios com um nao-unitario
   distorce elev/az de forma diferente por lado). Normalizado — mudanca <0.1°
   nos frames testados (acrossU ja era ~unitario), mas fecha o buraco
   conceitual. Ombros assimétricos continuarao visiveis quando a pessoa
   estiver com um ombro levantado — isso e fidelidade, nao defeito.

```bash
python scripts/probe_trunk_rest.py            # geometria de repouso do tronco
python scripts/probe_torso_twist.py           # torcao vs o fit (com flags A/B)
# A/B de solver: NUNCA usar git stash como baseline (HEAD pode ser muito antigo);
# snapshotar o solver em experiments/_solver_*.js e servir via Handler transladado.
```
