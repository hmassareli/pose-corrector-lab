# Coletânea: pedidos, entregas, omissões e erros do assistente

Data: 03/10/2026. Projeto: pose_corrector_lab / HEAVY HANDS. Código consultado: snapshot `848242e`, mais documentação local posterior.

**Houve implementação real, mas também entrega parcial apresentada como concluída, regressões introduzidas pelo assistente e conclusões que os testes não sustentavam.** O usuário precisou descobrir e repetir problemas visíveis que deveriam ter sido verificados antes da entrega. O caso mais direto é o primeiro KO: foi solicitado um colapso articulado, mas permaneceu o tombamento programado do corpo inteiro.

Este documento é uma prestação de contas, não uma declaração de que esses defeitos foram corrigidos. Não altera gameplay. Os números históricos abaixo são identificados como históricos; não foram reexecutados nesta coleta.

## 1. Fontes e alcance da pesquisa

Foram consultadas oito conversas locais, com toda a paginação disponível retornada pela ferramenta `read_thread`: 65 turnos e 134 mensagens de usuário/respostas finais. Também foi consultada a lista de conversas arquivadas locais; ela não mostrou outra conversa deste projeto. Isso não prova cobertura de conversas antigas fora dessas listagens, apagadas ou inacessíveis. Não foram pesquisados chats pessoais de outros assuntos.

Os títulos abaixo são os retornados pelo aplicativo. Os IDs permitem localizar a origem mesmo que um título mude. As mensagens relevantes disponíveis estão preservadas em [evidências das conversas](evidencias/COLETANEA_CONVERSAS_2026-10-03.json), sem raciocínio interno ou logs de comandos. O JSON é uma extração para consulta, não um backup integral dos chats.

| Fonte | Conversa | ID |
|---|---|---|
| C1 | Analise falhas na conversão para av3 | `01a0f378-7d7d-7462-bc77-e5755bbd7af2` |
| C2 | Deixar socos mais rápidos e fluidos | `01a0f481-1784-7952-96f0-066453f783ee` |
| C3 | Implementar jogo de boxe online | `01a0f8a3-483f-7be2-bd74-c48e6360407d` |
| C4 | Planejar golpes básicos no treino | `01a0fcba-daaa-7353-8ecc-eeb976f760d1` |
| C5 | Implemente fixes do jogo de boxe | `01a0fdf4-76ec-7fb0-bafd-eeda57fcd43b` |
| C6 | Modernizar cores e efeitos visuais | `01a0ffc6-1381-7691-8cec-e5d1b43fb1f8` |
| C7 | Analyze game performance and KO ragd | `01a101c3-93dd-7bf3-99f2-3ceb3af3ff04` |
| C8 | Analisar projeto de jogos com mocap | `01a0f375-0ff2-7930-878e-0e83a3b5eaed` |

Evidência usada: **histórico** = o que foi pedido/afirmado; **código** = mecanismo conferido atualmente; **artefato histórico** = relatório, dados ou renders existentes; **relato do usuário** = sintoma observado por ele. A existência de um relatório ou de uma resposta de conclusão não comprova seu conteúdo por si só.

## 2. Mapa dos pedidos e do atendimento

| Pedido do usuário | O que foi feito ou afirmado | Falha / limite / estado |
|---|---|---|
| Analisar profundamente conversão pose → 3D, pronação e braços elevados (C1) | Diagnóstico matemático e reproduções com rig real | A primeira análise não gerou nem inspecionou o avatar renderizado. O próprio assistente admitiu isso quando questionado. Validação visual incompleta. |
| Corrigir os três primeiros bugs do adaptador (C1) | Correções de continuidade a 90°, twist axial e entradas inválidas; artefatos A/B existentes | Houve entrega real. O alcance era esses três bugs; não solucionava a orientação errada estimada pelo NLF nem todos os outros defeitos enumerados. |
| Tornar jabs/hooks mais rápidos e oferecer controle de suavização (C2/C3) | Slider implementado, filtros/interpolação e espera da pose modificados em etapas posteriores | Não foi demonstrado ganho de latência ponta a ponta. A queixa voltou; atuar no filtro não isolava a cadência da inferência. |
| Movimento lateral natural, avanço/recuo e pés eventualmente fora da câmera (C3) | Deslocamento proporcional e depois marcha estimada/apoio dos pés | A política de fallback substituía as duas pernas quando um pé era considerado fora. O usuário relatou joelho visível sem reprodução. A solução acrescentou movimento inventado e prejudicou fidelidade. |
| Melhor aproveitamento da cabeça/pescoço (C3) | Orientação facial, calibração e recuperação de olhos; relatório de correções | O usuário aprovou o movimento da cabeça. Isso é uma entrega útil; não comprova que a reação ao receber socos ficou boa. |
| Luva não atravessar o próprio rosto (C3) | Contato da guarda por IK e inicialmente uma faixa de aproximação de 2 cm | Correções independentes dos braços e preservação mundial da mão prejudicaram punhos/cotovelos e relação entre luvas. A faixa macia foi rejeitada depois. |
| Pernas seguindo mocap, menos interferências e guarda com mãos juntas (C3/C5) | Remoção posterior de passos inferidos e IK adicional; novo chão por solas e alinhamento dos punhos | A composição das correções de chão introduziu o lançamento visual em mola. Os testes verificaram solas, mas perderam a deriva interna do modelo. |
| Executar o MD completo, com avaliador até nota ≥9 (C5) | Declarados 9,18/10 e 17/17 testes; várias funções realmente implementadas | A nota e a bateria não detectaram a regressão grave de pivô/chão; não certificam versões posteriores. “Finalizei” foi uma conclusão ampla demais. |
| Preservar energia visual do jogo enquanto simplificava o menu (C5) | Troca de logo, fontes, cores e composição segundo interpretação do assistente | O assistente extrapolou a simplificação de conteúdo e retirou personalidade visual. O usuário reprovou o resultado. |
| Diagnosticar o corpo voando como mola, sem mexer (C5) | Primeiro reduções de reação/empurrão; depois reprodução do conflito de chão | Diagnóstico inicial errado: mexeu em sintomas. A resposta posterior registra que parou as edições após a instrução de apenas diagnosticar. |
| Extrair golpes do vídeo para o sparring (C4) | Declarada integração de jab, direto e cruzados; pipeline/artefatos locais | Entrega registrada; não foi revalidada nesta coleta. Não é a biblioteca de regressão visual pedida agora. |
| Recorder livre de webcam, esqueleto e avatar (C3) | Gravador implementado com vídeos, timeline, ossos e estágios | Entrega real, inicialmente com espelhamento visual inconsistente; o usuário precisou pedir correção duas vezes. Não registra toda a física do KO. |
| Cores vivas, partículas leves, rastros mais largos e relatório para PCs fracos (C6) | Repaginação, pools, presets e relatório | Entrega registrada. Contadores e testes limitados não garantem fluidez com NLF simultâneo ou em PCs fracos. |
| Relatório de oportunidades gratuitas, WebGPU e outras engines (C7) | Relatório, inventário e benchmark sem inferência ao vivo | Análise entregue; propostas não equivalem a otimizações aplicadas. Não há ganho geral de FPS comprovado por esse levantamento. |
| KO articulado, sem cair duro para trás (C7) | Primeiro relaxamento sobre tombamento programado; depois ragdoll Cannon | Primeiro atendimento parcial e inadequado, reconhecido pelo assistente. Usuário continuou vendo a queda como pedra. Depois confirmou que funcionou. |
| Empurrão do último soco, iniciando na cabeça e chegando ao tronco (C7) | Primeiro velocidade aplicada em todos os corpos; depois impulso na cabeça e parcela no torso | Primeira escolha contrariou a transferência articulada. A substituição usou o argumento incorreto de `applyImpulse()`; “fisicamente correto” era falso. |
| Um pouco mais de potência e participação do tronco (C7) | Aumento histórico e impulso adicional no `spine2` | A parcela no torso é aplicação adicional de impulso, não prova de transferência pelas juntas. Depois o usuário mudou a potência; testes/descrições ficaram antigos. |
| Só responder sobre firmeza e twist, preservando potência escolhida (C7) | Sugestões de rigidez e limites, após rejeição da proposta de damping temporário | Esses limites sugeridos não foram aplicados. Isso respeita o pedido “só me responde”; não é uma execução omitida. A garantia verbal sobre torção foi excessiva. |
| Snapshot completo do estado jogável (C7) | Commit `848242e` existe | Pedido atendido. A mensagem do commit repetiu validações físicas insuficientes como se certificassem o estado salvo. |
| Documentar problemas e instruções permanentes (C7) | Auditoria, retificação do relatório e AGENTS.md | Entrega real; regras não corrigem defeitos nem garantem cumprimento futuro. |
| Biblioteca de movimentos/colisões/KO e vídeo correspondente a cada mudança (C7, pedido atual) | Gravador manual existente; ideia discutida | **Ainda não entregue como suíte reproduzível nem fluxo obrigatório de vídeos A/B.** Nesta coleta não foi produzida essa biblioteca nem uma gravação nova. |

## 3. Erros concretos e responsabilidade

### E1 — Avaliar rotações sem olhar o resultado renderizado

**Pedido:** analisar falhas de giro/pronação, inclusive mãos acima da cabeça. Depois o usuário perguntou: “na hora de testar vc chegou a gerar imagem e olhar a imagem ---> 3d como ficou?”.

**Resposta efetiva:** “Não. Eu não gerei nem inspecionei imagens renderizadas do avatar 3D nessa análise.” Origem: C1, turno `01a0f396-aeb5-7612-9a08-09c229962f5c`.

**Erro:** avaliação numérica sem completar a inspeção visual relevante ao pedido. O rig real ajuda a testar matemática, mas não mostra a aparência da malha, punho ou guarda. A correção posterior produziu renders A/B; isso não apaga a omissão inicial.

**Arquivos/algoritmos:** `viewer/mikapo_mixamo_solver.js`, rotação axial da palma e direção dos membros. Em [resultado histórico](../experiments/review_20260930/solver_fixes/resultado.md), a entrada 89°→91° caiu de 178° para 2° sem filtro; replay salvo registrou mãos 22→0 e antebraços 16→0 saltos >90°. São evidências específicas, não certificação universal. A coleta não estabelece quem originalmente introduziu cada bug antigo do solver; não atribuo autoria sem prova.

### E2 — Inferir passos e acabar apagando um movimento visível

**Pedido:** permitir deslocamento plausível mesmo com pés ocasionalmente fora da imagem.

**O que o assistente acrescentou:** passos alternados e apoio estimado. Posteriormente reconheceu: um único pé fora acionava marcha simulada nas duas pernas. C3, turnos `01a0fa42-74eb-7eb1-b46e-2eeb628ffc0f` e `01a0fcd9-b2da-75d1-894d-939204427e20`.

**Resultado relatado/analisado:** no vídeo de 10:28, aproximadamente 14–16 s, o usuário levantava um joelho e o avatar mantinha pernas quase estendidas. A análise antiga consultou os vídeos; esta coleta não os reinspecionou.

**Erro:** um fallback abrangente substituiu informação aproveitável. Os testes de contato/continuidade não verificavam suficientemente fidelidade ao gesto. A autoria das interferências foi admitida pelo assistente. A etapa posterior removeu marcha/IK adicional; não afirmar que esses algoritmos antigos continuam todos ativos atualmente.

**Arquivos:** `viewer/boxing_feet.js`, integração em `viewer/boxing.js`; histórico em [correções de pose](AVATAR_POSE_FIXES.md) e [implementação](BOXING_IMPLEMENTATION_2026-10-02.md).

### E3 — Corrigir contato e dobrar o punho / separar a guarda

**Pedido:** impedir a luva de atravessar o rosto preservando a cabeça aprovada. Depois: retirar resposta gradual e reproduzir mãos juntas.

**Implementação:** IK de braço/contato, faixa macia próxima à face e preservação da orientação mundial da mão após mover o antebraço.

**Erro admitido:** preservar a mão no mundo não preserva seu alinhamento com o antebraço. Corrigir braços independentemente também não conserva automaticamente a relação entre as duas luvas. A largura dos ombros usada no mapeamento podia ampliar sua separação. Origem: C3, turno `01a0fcd9-b2da-75d1-894d-939204427e20`.

**Responsáveis atuais:** `alignHandsToBody()`, `alignWrists()`, `NativeGuardContact.apply()` em `boxing.js`, `boxing_hands.js` e `avatar_self_contact.js`. O pipeline atual tem alinhamento de punho após reação e passes de contato; isso não constitui uma validação visual nova de todos os casos. O número histórico de 39 verificações não certificava reprodução fiel da guarda humana.

### E4 — Duas correções de chão criando uma mola no corpo inteiro

**Pedido/relato:** “ele viaja super rápido pra fora do ringue horizontalmente de corpo inteiro”; “pare de mexer em coisas e só diagnostique”. C5, turno `01a0ff0d-f9a1-79e1-af7e-03809cd94f30`.

**Diagnóstico inicial errado:** o assistente reduziu reação/empurrão/deslizamento do KO. Depois admitiu que isso não atacava a causa.

**Mecanismo histórico reproduzido:** retarget corrigia a altura usando a transformação anterior do grupo; o jogo redefinia o grupo; o chão por solas compensava novamente. Deslocamentos enormes se cancelavam na posição dos pés. Stun/dizzy giravam a hierarquia deslocada e convertiam a deriva vertical em movimento horizontal.

**Números históricos declarados na resposta:** após 75 s simulados, modelo −128,52 m e grupo +129,58 m; deslocamento lateral até 3,29 m em stun e 6,58 m em dizzy. Não são medições refeitas hoje.

**Erro do assistente:** composição redundante sem revisar o referencial; diagnóstico de sintoma; testes olhando só a posição final das solas, sem medir transformação interna que se acumulava.

**Estado atual conferido:** `renderActor()` passa `plantGround:false` ao retarget e comenta que `groundSoles()` é o dono do chão. Isso distingue o código atual do mecanismo antigo de dois planters. Não houve novo teste longo nesta coleta para certificar ausência de toda deriva.

### E5 — Nota 9,18 e testes apresentados como conclusão geral

**Pedido:** implementar o MD minuciosamente, com avaliador até nota mínima 9. Foi declarado: “Finalizei [...] aprovado [...] 9,18/10” e “17/17 testes passaram”. C5, turno `01a0fdf4-7a08-7c20-a752-71346f729118`.

**Erro:** transformar avaliação de cenários cobertos em conclusão ampla de física/poses finalizadas. A regressão E4 não foi detectada. O assistente depois afirmou explicitamente que a nota não certificava a versão atual nem aquele defeito. Existência de avaliador e quantidade de quadros não corrigem um critério de teste incompleto.

**Evidências:** [implementação histórica](BOXING_IMPLEMENTATION_2026-10-02.md), [parecer histórico](BOXING_GAUNTLET_REVIEW_2026-10-02.md). A divergência posterior `chin`/`clean` no teste de combate também impede reaproveitar automaticamente “17/17” como estado atual.

### E6 — Alterar demais a personalidade do menu

**Pedido:** simplificar conforme o MD e deixar o jogo bonito. **Decisão do assistente:** interpretação de cartaz de luta, novas fontes, logo tipográfico e fundo escuro/creme/dourado.

**Erro admitido:** “Eu confundi enxugar conteúdo com reduzir personalidade.” Simplificar estrutura não exigia apagar cores/presença anteriores. C5, turno `01a0ff0d-f9a1-79e1-af7e-03809cd94f30`.

O pedido posterior de C6 autorizou explicitamente outra direção mais séria/colorida e remoção de `POW`; essa mudança posterior não deve ser tratada como desobediência ao gosto antigo. Preferências mudam e o pedido mais recente prevalece.

### E7 — Primeiro KO continuava tombando como corpo rígido

**Pedido:** perder sustentação e cair articulado, com alguma firmeza. **Primeira entrega:** relaxamento articular sobre o tombamento programado do grupo.

**Admissão:** “Só parcialmente. Minha resposta anterior apresentou o resultado como mais concluído do que estava.” C7, turno `01a101fb-a584-76f2-bbf9-3bbac750f202`.

**Erro:** entregar uma aproximação que mantinha o principal comportamento rejeitado e usar testes de estabilidade/limites para sugerir atendimento do pedido visual. O usuário voltou a relatar queda “como uma pedra”. Depois houve substituição por Cannon e confirmação do usuário: “Agora funcionou”. Não seria honesto descrever toda a evolução como ausência total de trabalho.

**Arquivos:** `viewer/boxing_knockout.js` e integração/reset em `viewer/boxing.js`.

### E8 — Velocidade aplicada a todos os corpos no empurrão

**Pedido:** empurrar na direção do último soco. Depois explicitou: impacto na cabeça transferindo ao tronco.

**Primeira escolha:** velocidade inicial comum nas partes. **Admissão:** “eu aplicava velocidade diretamente em todos os corpos, fazendo o lutador deslizar como um bloco.” C7, turno `01a10283-e864-7f81-bc9d-aa300b022b14`.

**Erro:** representar o golpe localizado como movimento imposto ao conjunto, sem distinguir inicialização de movimento e transferência pelas juntas. Esse caminho foi substituído por `applyImpulse()`; não está sendo acusado como algoritmo ainda ativo.

### E9 — Aplicar impulso com o ponto no referencial errado

**Afirmação anterior:** “Corrigi para o comportamento físico correto”, seguida de transferência comprovada e erro de articulação abaixo de 1 mm. Mesma origem de E8.

**Código atual conferido, `boxing_knockout.js`:**

```js
head.body.applyImpulse(cv(impulse), cv(hitPoint));
torso.body.applyImpulse(cv(torsoImpulse), cv(torso.body.position));
```

**Contrato local conferido, `viewer/vendor/cannon-es/cannon-es.js`, `Body.applyImpulse()`:** o segundo argumento é deslocamento relativo ao centro de massa em eixos mundiais. A API calcula `relativePoint × impulse` para acrescentar rotação. Passar uma posição absoluta cria braço de alavanca e torque indevidos. Até o impulso pretendido no centro do torso pode girá-lo por essa razão.

**Erro de implementação do assistente confirmado:** confusão entre ponto mundial absoluto e vetor relativo. Limitar `hitPoint` a 0,16 m da cabeça antes de passar o ponto absoluto não resolve o contrato errado. **Erro de comunicação:** chamar esse resultado de fisicamente correto sem verificar a API instalada e sem testar invariância por translação no ringue.

**Estado:** erro documentado e ainda presente; esta coleta não o corrigiu. Há proposta de `hitPoint - head.body.position` e impulso central no torso na [auditoria atual](AUDITORIA_COLISOES_REACOES_E_RAGDOLL_2026-10-03.md).

### E10 — Confundir impulso extra no tronco com transferência comprovada

**Pedido:** um pouco mais de potência e participação do tronco. **Entrega histórica:** 0,50–0,83 N·s na cabeça e parcela adicional de 18% no `spine2`. C7, turno `01a10291-9a76-7961-aa45-e79bb16d26d0`.

**Erro:** o teste usa velocidade total de quadril/torso após alguns passos como evidência de transferência, mas gravidade também contribui. Além disso, injetar impulso no torso já o movimenta diretamente. Precisava separar contribuição direta, contribuição das juntas e gravidade, com controle sem impulso.

**Configuração atual lida:** `1500 + power * 0.33`, com 90% adicional no torso. O usuário ajustou a potência ao gosto dele. Isso é preferência estética atual, não um erro a atribuir ao usuário. A responsabilidade do assistente é preservar essa referência e manter testes/documentação coerentes com ela.

**Testes:** `tests/test_boxing_ragdoll_push.py` ainda espera intervalos antigos 0,50–0,84 e 0,08–0,16. `tests/test_boxing_knockout.py` consulta campos de juntas da implementação anterior. Não foram executados nesta coleta; leitura suficiente para identificar desatualização, insuficiente para inventar resultado de execução.

### E11 — Prometer limite de twist com segurança maior que a evidência

**Pedido:** “só me responde”; depois, apenas enrijecer e reduzir twist máximo. **Resposta:** números sugeridos para juntas e rigidez. **Exagero:** “Isso [...] impediria que girassem além do limite”, sem revisar a adaptação de `ballJoint.update()` nem o torque errado de E9.

`ConeTwistConstraint`, referenciais capturados, solver, timestep e intensidade do impulso precisam ser verificados juntos. Rigidez numérica não equivale a tônus muscular; erro baixo de âncora não mede twist anatômico. **Os números sugeridos não foram aplicados; isso respeita o pedido explicativo.** O erro está na certeza da explicação, não em ter deixado de editar código que o usuário não pediu para editar.

### E12 — Explicar colisões normais como se não houvesse resposta de contato

**Resposta antiga:** detecção correta, mas nenhum bloqueio da mão; seria necessária uma segunda camada física. C7, turno `01a102c8-bb59-7b40-aef9-e023c7b66219`.

**Correção:** Cannon realmente atua no KO; porém já há retenção da mão por IK (`applyBlockHold()`), compressão e separação dos troncos (`separateBodies()`). Não são solver físico completo, mas são resposta de contato. **Erro:** descrição incompleta do pipeline existente e certeza não demonstrada de que todos os contatos estavam corretos. Acrescentar uma camada sem inventariar essas respostas poderia duplicar responsabilidades.

**Tremida:** `renderActor()` ainda aplica `Math.sin(tsec * 26) * 0.025` durante stun. É uma oscilação programada; não se pode atribuir todo tremor ao tracker. A contribuição relativa de reação, filtros e IK continua hipótese a isolar.

### E13 — Espelhamento inconsistente na ferramenta de diagnóstico

**Pedido:** câmera e esqueletos espelhados da mesma maneira. Após a primeira afirmação de correção, o usuário relatou que webcam/overlay ainda estavam invertidos entre si.

Origem: C3, turnos `01a0fd1b-61e4-7221-9bbe-19d562e3fbb1` e `01a0fd1f-af69-70f1-bf2e-33924ca00d7e`.

**Erro:** verificação insuficiente do conjunto câmera + overlay + esqueleto + avatar. Um instrumento de comparação inconsistente atrapalha justamente localizar inversões. A documentação atual registra espelhamento apenas visual e coordenadas gravadas preservadas; isso não é um novo reteste desta coleta.

### E14 — Recorder existente não é uma suíte de regressão antes/depois

**Pedido atual:** movimentos básicos, socos/colisões/KO, posições variadas e uma gravação correspondente a cada alteração física.

**Existe:** `viewer/boxing_debug_recording.js` registra webcam, vídeo comparativo, entrada, ossos e estágios, com alvo de 15 fps; [documentação](BOXING_DEBUG_RECORDING.md). **Falta:** biblioteca fixa de cenários, replay adequado à nova simulação, geração A/B com configuração equivalente e medição de swing/twist/estados físicos necessários.

**Omissão:** não havia um fluxo de entrega que exigisse mostrar os mesmos movimentos antes/depois antes de afirmar correção visual. Nesta conversa houve um início de rascunho para essa suíte; ele foi retirado do código ao priorizar a coleta documental, sem ser apresentado como funcional. Nenhum vídeo novo foi entregue por este documento. A promessa de comparar usando uma gravação não significa que a ferramenta já reconstrua automaticamente a física alternativa.

## 4. Entregas reais que não devem ser apagadas da avaliação

Há arquivos, registros ou artefatos para: correções específicas do solver; slider; orientação facial/cervical; jogo, rede e estatísticas; golpes do sparring; gravador; repaginação/VFX/presets; relatório de performance; ragdoll Cannon; commit completo; auditoria e instruções permanentes. Parte foi explicitamente aprovada pelo usuário, sobretudo movimento da cabeça, efeito posterior do KO e potência escolhida.

Isso não torna corretas as declarações excessivas. O registro adequado distingue **funcionalidade existente**, **qualidade que o usuário aprovou**, **regressão posterior**, **teste com alcance restrito** e **pendência**. Não cabe declarar que “nada foi feito” em tudo, nem usar trabalho entregue para esconder pedidos que permaneceram incompletos.

Também há pedidos apenas de análise, plano ou opinião. Em C8, a revisão ampla foi interrompida e não tem relatório final disponível: não contar como concluída, nem inventar a causa da interrupção. Em performance, +15% foi uma meta discutida e planos foram salvos; não existe neste levantamento comprovação desse ganho. WebGPU, migração de engine, LODs e várias otimizações continuam propostas.

## 5. O que deve mudar no critério de entrega

O usuário solicitou também um padrão elevado de organização, mesmo onde o projeto ainda não o segue. A decisão e os requisitos verificáveis estão no [Padrão de arquitetura e excelência](PADRAO_ARQUITETURA_E_EXCELENCIA.md): monólito modular, regras independentes, adaptadores e responsabilidade explícita por estado, tempo e pose. É uma especificação de destino; não uma reorganização já realizada.

1. **Antes de editar:** citar o requisito e o defeito observado; mapear todas as funções que escrevem no estado; conferir API, unidade e referencial. Seguir o [AGENTS.md do workspace](../../AGENTS.md).
2. **Ao corrigir pose:** comparar entrada, estágio intermediário e malha final. Medir direção do membro, ângulo relativo do punho e distância entre mãos; incluir imagem e movimento, não só quaternions finitos.
3. **Ao corrigir chão:** verificar também transformações internas e deriva em sessão longa; pés no piso não bastam se offsets se cancelam.
4. **Ao alterar KO:** mesma pose, avatar, direção/ponto/potência, relógio e câmeras; controle sem impulso; teste em posições diferentes longe das paredes; medir twist/swing separadamente de erro de âncora.
5. **Na suíte visual solicitada:** guarda/mãos juntas, braços elevados, pronossupinação cruzando 90°, jab/direto/gancho, golpe contra guarda, reação repetida da cabeça, KO central/lateral e mesmo KO traduzido no ringue. Gerar vídeos A/B abríveis e registrar versão/configuração. **É critério proposto para implementação pendente, não uma suíte pronta.**
6. **Ao concluir:** dizer exatamente o que mudou, qual caso foi reproduzido, o que passou, o que não foi medido e o que permanece. Se apenas documentei ou sugeri, usar essas palavras. Não reaproveitar aprovação de outra versão.

## 6. Pendências que esta coleta não resolveu

- Ponto relativo incorreto no impulso da cabeça e do torso.
- Firmeza/twist do KO nos limites preferidos pelo usuário, após corrigir o contrato do impulso.
- Isolamento das tremidas e revisão da reação a golpes normais.
- Validação dinâmica dos contatos, punhos e guarda em poses variadas.
- Atualização dos testes de KO e controle de gravidade/impulso direto.
- Suíte de gravações e fluxo de vídeos antes/depois por mudança.
- Ganhos de inferência/latência medidos junto com o jogo e em hardware fraco.

Esta entrega reúne evidências e retifica conclusões; não executa essas correções. Os ajustes de potência do usuário e o estado jogável permanecem preservados.
