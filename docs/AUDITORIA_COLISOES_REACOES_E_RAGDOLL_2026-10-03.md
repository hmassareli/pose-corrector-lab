# Auditoria de colisões, reações de impacto e ragdoll

Data: 03/10/2026. Referência: commit `848242e` (`Snapshot playable boxing game state`).

Este documento registra a análise do código e os sintomas relatados pelo usuário. Nenhuma correção de gameplay foi feita nesta etapa de documentação. As linhas abaixo correspondem ao estado inspecionado; os nomes das funções são a referência principal caso a numeração mude.

## 1. Objetivo e preferências do usuário

- Preservar o estado jogável salvo e a potência de KO ajustada pelo usuário. O efeito de arremessar o lutador é desejado.
- Evitar que pescoço, cabeça e braços fiquem excessivamente soltos ou torcidos durante o KO.
- Preferir juntas um pouco mais firmes e limites máximos de twist mais restritos. A proposta de amortecimento temporário e limites adicionais de velocidade não foi a preferência expressa.
- Melhorar a reação da cabeça aos golpes normais, com movimento firme, contínuo e legível.
- Investigar tremidas e interpenetrações usando a mesma gravação para comparar antes/depois.

O impulso escolhido é uma decisão estética; não deve ser reduzido automaticamente como solução para problemas de articulação. Corrigir erros físicos pode mudar o efeito, exigindo recalibração visual com a gravação de referência.

## 2. O que está confirmado e o que ainda é hipótese

| Item | Evidência | Estado |
|---|---|---|
| Tremidas e reações estranhas | Relato do usuário | Sintoma; causa completa não isolada |
| Oscilação durante stun | Seno aplicado à rotação do grupo em `renderActor()` | Confirmado no código |
| Reação sobre tracking variável | `applyImpactReaction()` executa após retarget | Confirmado; contribuição para tremida ainda precisa de A/B |
| Correções sucessivas nos braços | IK, retenção, compressão, punhos e contato na mesma apresentação | Confirmado; conflito entre elas é hipótese |
| Relógios diferentes nas reações | `vclock` versus `performance.now()` | Confirmado; efeito visual precisa de reprodução |
| Ponto incorreto no impulso do KO | Posição mundial passada onde Cannon espera deslocamento relativo | Erro confirmado |
| Torções excessivas no KO | Relato do usuário e configuração atual | Causas relativas entre torque, juntas e potência ainda não medidas |
| Testes insuficientes/desatualizados | Asserts de potência antiga e velocidade sem controle de gravidade | Confirmado por leitura; não reexecutados nesta auditoria |

## 3. Caminho atual da pose durante a luta

Orquestração: [viewer/boxing.js](../viewer/boxing.js), `renderActor()` (linha 1745).

1. `updateAvatarPose()` aplica retarget e filtros da pose.
2. `alignHandsToBody()` reposiciona os braços por IK.
3. `applyImpactReaction()` adiciona rotações de impacto.
4. O grupo recebe posição, orientação e oscilações de stun/dizzy; `groundSoles()` corrige apoio no piso.
5. `applyBlockHold()` segura/libera a mão atacante no contato.
6. `compressDefender()` flexiona o antebraço do defensor.
7. `alignWrists()` corrige punhos.
8. `NativeGuardContact.apply()` roda quatro passes de contato da própria guarda.
9. `meshHitBox()` atualiza os volumes usados na detecção de golpes.

Ter várias etapas é normal em animação procedural. Não há evidência suficiente para chamar todas de redundantes. A auditoria deve medir qual osso cada etapa altera, quanto altera e se desfaz uma correção anterior.

### 3.1 Tremida programada

Arquivo: [viewer/boxing.js](../viewer/boxing.js), `renderActor()`, linha 1821.

```js
f.stun > 0 ? Math.sin(tsec * 26) * 0.025 : 0
```

Esse termo gira o grupo inteiro em Z, com amplitude de aproximadamente 1,43° e frequência de 4,14 Hz, quando o ramo de stun é usado. O ramo de dizzy tem outras oscilações. Portanto, parte da tremida pode ser intencional, não ruído do tracker. Comparar a mesma sequência com esse termo isoladamente desativado.

### 3.2 Cabeça e tronco ao receber golpes normais

Arquivo: [viewer/boxing.js](../viewer/boxing.js), `applyImpactReaction()` (linha 1640) e `impact()` (linha 1229).

O algoritmo calcula uma envoltória exponencial de ataque/decaimento e um eixo pelo produto vetorial entre vertical e direção do golpe. Converte o eixo para o referencial do pai e aplica rotações adicionais nos ossos. Golpes na cabeça usam `spine2`, `neck` e `head`; golpes no corpo usam outra cadeia da coluna.

Essa reação parte da pose de tracking atual a cada frame, sem uma base capturada exclusiva para o impacto. `impact()` substitui `fighter.reaction` quando recebe novo impacto com direção válida, reiniciando a envoltória. São candidatos a descontinuidade, sobretudo com golpes próximos; não são uma causa comprovada de todos os sintomas.

Retarget relacionado:

- [viewer/mikapo_mixamo_solver.js](../viewer/mikapo_mixamo_solver.js): `updateAvatarPose()` (linha 1319), `headForwardFromSmplAux()` (linha 1104).
- [viewer/avatar_head.js](../viewer/avatar_head.js): `resolveHeadPose()` (linha 56), calibração, recuperação de referências faciais e interpolação das orientações.

A proposta de capturar uma base de reação ou controlar temporariamente cabeça/pescoço é uma possibilidade futura. Não foi implementada nem validada.

### 3.3 Braços, guarda e relógios

| Arquivo | Função | Algoritmo / responsabilidade |
|---|---|---|
| [boxing.js](../viewer/boxing.js), linha 1716 | `alignHandsToBody()` | Reescala posições das mãos conforme proporções do avatar e resolve IK de dois ossos |
| [boxing.js](../viewer/boxing.js), linha 1675 | `applyBlockHold()` | Alvo de contato capturado, retenção e liberação por IK em cerca de 190 ms |
| [boxing.js](../viewer/boxing.js), linha 1696 | `compressDefender()` | Flexão adicional do antebraço com envoltória temporal |
| [boxing_hands.js](../viewer/boxing_hands.js) | `alignWrist()`, `alignWrists()` | Orientação dos punhos |
| [avatar_self_contact.js](../viewer/avatar_self_contact.js), linha 169 | `NativeGuardContact.apply()` | Correções da própria guarda, incluindo alvos resolvidos por IK |
| [boxing_feet.js](../viewer/boxing_feet.js), linha 48 | `solveTwoBone()` | Solução geométrica compartilhada de cadeia de dois ossos |

`applyImpactReaction()` usa `vclock`; retenção e compressão usam `performance.now()`. Hit-stop e câmera lenta podem fazer as reações avançarem em ritmos diferentes. Verificar isso com timestamps e os estágios registrados, antes de unificar relógios ou remover etapas.

## 4. Detecção versus resposta de contato

- [viewer/boxing.js](../viewer/boxing.js), `meshHitBox()` (linha 347): volumes associados ao avatar apresentado.
- [viewer/boxing_core.mjs](../viewer/boxing_core.mjs), `resolvePunchBox()` (linha 242): segmento contra esferas de cabeça/queixo e cápsulas de tronco/braços; seleção por prioridades e posição do contato no segmento.
- [viewer/boxing.js](../viewer/boxing.js), `separateBodies()` (linha 1113): correção de sobreposição dos troncos e distância mínima, respeitando limites de deslocamento do ringue.
- [viewer/boxing_core.mjs](../viewer/boxing_core.mjs), `addImpactPush()` e `stepImpactPush()` (linhas 194 e 203): empurrão procedural durante a luta.
- `applyBlockHold()`: correção temporária da mão após contato.

A varredura da luva detecta impactos entre duas posições, mas não constitui um solver físico contínuo de todos os membros. A detecção e as correções existentes não garantem ausência de interpenetrações visuais. Também não foi demonstrado que a detecção esteja correta em todos os cenários.

Correção da explicação anterior: há bloqueio visual por IK e separação de troncos. Era incorreto afirmar que nenhum sistema tentava impedir atravessamento. O Cannon não participa dessas etapas da luta normal.

## 5. KO: erro de torque e configuração atual

Arquivo principal: [viewer/boxing_knockout.js](../viewer/boxing_knockout.js).

O KO cria um mundo temporário Cannon para a vítima, com 18 corpos simplificados, juntas, gravidade, piso e planos de perímetro. `step()` avança em passos de 1/120 s; `present()` apresenta os corpos no esqueleto. O vencedor não faz parte desse mundo físico.

### 5.1 Erro confirmado em `applyImpulse()` — prioridade de correção

Chamadas atuais nas linhas 383 e 388:

```js
head.body.applyImpulse(cv(impulse), cv(hitPoint));
torso.body.applyImpulse(cv(torsoImpulse), cv(torso.body.position));
```

Na biblioteca local [viewer/vendor/cannon-es/cannon-es.js](../viewer/vendor/cannon-es/cannon-es.js), `Body.applyImpulse()` (linha 3790) recebe `relativePoint`: deslocamento em coordenadas mundiais **relativo ao centro de massa**, e não uma posição absoluta do mundo. O torque depende do produto vetorial `relativePoint × impulse`.

Logo, as duas chamadas usam um braço de alavanca incorreto. Até um impulso pretendido no centro do torso produz torque. A resposta pode depender indevidamente da posição absoluta no ringue.

Correção proposta, ainda não aplicada:

```js
const relativePoint = hitPoint.clone().sub(head.body.position);
head.body.applyImpulse(cv(impulse), cv(relativePoint));
torso.body.applyImpulse(cv(torsoImpulse)); // centro de massa
```

Limitar a distância do ponto a 0,16 m não resolve o problema enquanto a chamada continuar recebendo posição absoluta. Esse erro foi introduzido na implementação anterior do assistente; as afirmações anteriores de correção física e validação foram excessivas.

### 5.2 Potência escolhida pelo usuário e cortes de velocidade

Na versão inspecionada, linhas 381 e 386:

```js
const impulseMagnitude = 1500 + power * 0.33;
const torsoImpulseMagnitude = impulseMagnitude * 0.9;
```

São os valores atuais a preservar como referência estética, não os valores antigos de 0,50–0,83 N·s e 18% citados anteriormente.

`step()` (linha 415) corta velocidade linear acima de 6 m/s e angular acima de 9 rad/s **depois** do passo físico. O solver já recebeu o impulso antes do corte. Essa combinação precisa ser medida com os impulsos atuais; os cortes não garantem ausência de deformação durante o passo.

Também há tratamento da direção: remoção da componente vertical, inversão quando aponta contra o vetor de afastamento e mistura de 18% com esse vetor. Portanto, a direção aplicada não é necessariamente a direção original integral do soco.

### 5.3 Juntas e torções

- `ballJoint()` (linha 71): `ConeTwistConstraint`, com eixos calibrados na pose capturada e sobrescrita de `update()` para os eixos da equação de twist.
- `bendJoint()` (linha 101): `HingeConstraint` com equação de cone adicional para restringir flexão.
- `connect()` (linha 314): configura equações com `setSpookParams(1e8, 5, STEP)`.

Limites configurados, em radianos:

| Ligação | Cone | Twist |
|---|---:|---:|
| `spine2 → neck` | 0,55 | 0,40 |
| `neck → head` | 0,50 | 0,45 |
| `spine2 → Arm` | 1,80 | 1,05 |
| `ForeArm → Hand` | 0,50 | 0,40 |

Esses valores não certificam limites anatômicos absolutos: é necessário verificar os referenciais e a pose capturada. A adaptação de twist precisa de testes que separem swing de twist. Aumentar a rigidez numérica da restrição também não equivale a criar tônus muscular ou sustentação de pose.

Limites menores e juntas mais firmes foram discutidos, mas não implementados nesta documentação. Primeiro corrigir o torque indevido; depois medir torção relativa e ajustar as juntas preservando o efeito de lançamento desejado.

## 6. Gravador e validação

[viewer/boxing_debug_recording.js](../viewer/boxing_debug_recording.js): `snapshotRig()` (linha 33), `stage()` e `capture()` (linha 196). Alvo de captura: 15 fps, sujeito ao desempenho real.

Já registra vídeo da webcam, comparação renderizada, poses recebidas, transformações finais dos ossos, estágios da apresentação e contexto dos lutadores. `reaction` inclui direção e ponto do impacto. Isso permite análise visual e reconstrução das poses amostradas, mas não garante reexecução idêntica da física.

Ainda não registra o estado completo do ragdoll a cada substep: vetores de velocidade linear/angular, orientações de todos os corpos físicos, impulsos aplicados, twist/swing medidos, limites, erro de âncoras e atuação dos cortes. `KnockoutRagdoll.diagnostics()` (linha 477) já expõe parte dos dados, mas o gravador não o inclui diretamente.

Limitações dos testes:

- [tests/test_boxing_ragdoll_push.py](../tests/test_boxing_ragdoll_push.py) espera a potência antiga. A configuração atual não atende a esses asserts por inspeção.
- Medir velocidade total do quadril/torso após alguns passos não isola transferência do soco: a gravidade também produz velocidade. Usar controle sem impulso, mesma pose, mesmos passos, e comparar a componente na direção do golpe.
- Erro de âncora mede separação dos pontos das juntas; não certifica twist correto nem naturalidade. O script admite 0,03 m no estado final, portanto não é uma garantia geral de erro abaixo de 1 mm.
- [tests/test_boxing_knockout.py](../tests/test_boxing_knockout.py) ainda consulta `j.bone`, `j.base` e `j.limit` da implementação anterior. Não valida diretamente as atuais constraints Cannon.
- Prints e resultados históricos não validam automaticamente a potência atual nem todos os avatares, direções ou posições.

## 7. Plano de investigação e critérios de comparação

1. **Fixar a referência:** guardar gravação, commit, avatar, pose inicial, ponto/direção do golpe, potência, parâmetros de juntas e passos de tempo. O commit preserva o estado jogável e os ajustes atuais.
2. **Corrigir o ponto do impulso:** testar o mesmo impacto em posições diferentes do ringue, afastadas das paredes. A translação do cenário não deve criar torque adicional. Um impulso no centro de massa não deve acrescentar rotação instantânea por braço de alavanca.
3. **Isolar a tremida de stun:** comparar a mesma sequência com e sem a oscilação, sem alterar os outros sistemas.
4. **Auditar os escritores da pose:** medir por estágio as alterações de cabeça, pescoço, coluna e braços; observar reinício de reação e divergência dos relógios.
5. **Avaliar contatos:** testar golpes frontais/laterais, guarda, contatos prolongados e liberação do braço; verificar atravessamentos, saltos de alvo e classificações inesperadas.
6. **Ajustar firmeza do KO:** medir swing/twist relativos, erro de âncora e velocidades antes/depois dos cortes. Alterar uma família de juntas por vez e preservar o lançamento aprovado visualmente.
7. **Comparar vídeos:** renderizar antes/depois da mesma entrada, com câmera e temporização iguais. Exibir também cabeça/pescoço/torso em aproximação. Apenas reutilizar um vídeo não gera a física alternativa; é preciso reproduzir a entrada no jogo.

Critérios de sucesso: reação contínua, menos tremida indesejada, contato legível, torções limitadas nos referenciais corretos, queda articulada sem aspecto excessivamente solto e manutenção do efeito de arremesso desejado. A confirmação exige números e revisão visual; nenhuma dessas correções está marcada como concluída por este documento.
