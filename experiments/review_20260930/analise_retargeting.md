# Auditoria do retargeting e das decisões do repositório

Data: 30/09/2026. Estado analisado: arquivos presentes no workspace, incluindo alterações locais não commitadas. O repositório efetivo é `pose_corrector_lab/.git`; o Git da pasta pai trata esse projeto como não rastreado. Nenhum arquivo de produção foi alterado nesta auditoria.

**Conclusão:** existem falhas reais e reproduzíveis na conversão para o avatar. Algumas permitem giros grandes mesmo com entradas contínuas e sem erro do modelo. O projeto tem boas decisões de pesquisa e geometria, mas a implementação atual não possui a robustez e a validação que eu exigiria para liberar um sistema de captura corporal em produção. Não é possível inferir o nível ou a empresa do autor pelo código; é possível avaliar o que o sistema garante hoje.

## Escopo e evidência

Foi inventariado o código próprio em `src/pose_lab`, `scripts`, `viewer`, `docs` e `configs`: **118 arquivos, 31.944 linhas**, antes da inclusão desta auditoria. Esse inventário é um mapa de arquivos, docstrings e funções, não uma afirmação de que cada linha dos utilitários recebeu revisão manual. A leitura aprofundada concentrou-se nos caminhos de inferência, convenções de coordenadas, corretor, retargeting, calibração do rig, bake, métricas e experimentos relevantes. Também foi consultado o solver upstream em `external/MiKaPo` e o port em `pose_corrector_lab/external/mikapo_port`.

Validação executada:

- `scripts/smoke_test.py`: passou. Verifica módulos Python básicos; não testa a orientação do avatar.
- Solver JavaScript atual executado em Node com **Three.js 0.160.0**, a mesma versão dos import maps do viewer.
- Rig extraído diretamente da hierarquia, transforms e juntas de skin do **GLB real do boxeador**, sem modificar o asset.
- Casos sintéticos de continuidade, rotação antiparalela, perda de medida, escala, cabeça e contato com chão.
- Reexecução dos **1.056 frames** existentes de `nlf_fit_webcam1/fit_smplx.npz`, além dos payloads existentes `top_frames.json` e `abl_live.json`.
- Funções Python `apply_delta` e `eval_delta` atuais executadas a partir de sua AST, com entradas controladas.

Limites da evidência: não gravei uma nova sessão de webcam, não renderizei a malha nem fiz avaliação visual de todos os vídeos, não retreinei modelos e não medi latência na GPU. O replay mede quaternions dos ossos; não prova, sozinho, qualidade perceptual do skinning. A sequência tem somente **6 frames crus** com ao menos um punho acima do ponto de cabeça, insuficientes para certificar movimentos acima da cabeça. Resultados contra o fit medem concordância com outra estimativa; o fit não é uma medição independente da realidade.

Hash SHA-256 do solver analisado: `1631419293ff38210727f1d2beb1844b05a66d32aa7a3b58087cfc5c677d1f84`.

## O caminho realmente implementado

1. **MediaPipe ao vivo:** Pose-33 → 16 juntas do lab → opcional GRU corretora → direções dos ossos. Cabeça, mãos e pés vêm de auxiliares MediaPipe.
2. **NLF ao vivo:** fast path x55, sem fit paramétrico → 16 juntas + auxiliares x55 → mesmo solver FK. A nuvem densa pode ser exibida, mas o wrapper live não a fornece ao solver como `surfaceAux`.
3. **Baker top offline:** posições do fit + orientação da palma construída com rotações FK do fit → dedos sintéticos que transportam os eixos → solver com `fitPalm=true`.

O terceiro caminho recebe sinal melhor e usa comportamento diferente do primeiro/segundo. Não é válido transferir automaticamente a conclusão “o bake acompanha a palma do fit” para “o avatar live acompanha a mão real”.

O corretor aprendido produz **18 valores: posição de ombros, cotovelos e punhos**. Não produz orientação completa da mão nem pronação. Uma linha cotovelo–punho permite determinar sua direção, mas admite várias rotações da palma ao redor dela. A orientação adicional precisa vir de observações confiáveis, um estimador de rotações ou uma inferência explicitamente aproximada.

## Achados prioritários

P1 significa falha importante para confiabilidade ou interpretação dos resultados. P2 significa defeito condicionado a um caminho específico, ou limitação relevante de produto. São prioridades desta revisão, não classificações de segurança.

### 1. P1 — A regra de “giro agudo” introduz uma descontinuidade de quase 180°

Local: `viewer/mikapo_mixamo_solver.js:657`, chamadas em `:1181` e `:1519`; wrapper live em `viewer/live.html:1251`.

Quando o eixo lateral desejado tem produto escalar negativo com a referência já alinhada, o solver **nega o vetor desejado**. A comparação é com a referência derivada do repouso, não com a última palma válida. Assim, uma rotação física contínua que atravessa esse limite muda de representação subitamente: a palma direcionada passa a ser tratada como um eixo sem sinal.

Reprodução com direção do osso fixa e entrada sem ruído:

| Configuração | Variação de entrada | Variação de saída |
|---|---:|---:|
| Live, alvo antes da suavização | 2° — de 89° para 91° | **178°** |
| Live com One-Euro e timestamps a 30 Hz | 2° | **136,2°** |
| Mesmo caso com `fitPalm=true` | 2° | 2° |

O salto de 178° também foi reproduzido nos dois antebraços e nas duas mãos do GLB real. Portanto, há uma falha do solver independente da qualidade da detecção.

Este mecanismo já está citado em `scripts/ablate_palm_signal.py:8`, mas continua ativo no live. Isso explica por que o problema pode ser conhecido e ainda aparecer. Levantar os braços modifica a relação entre referência de repouso, direção do membro e eixo da palma; pode atravessar esse limite sem uma pronação real abrupta.

Direção de correção: preservar a polaridade anatômica; usar confiança e continuidade temporal para resolver ambiguidades. Não recomendo simplesmente ligar `fitPalm` globalmente: há outra singularidade no caso seguinte e os pontos crus continuam sujeitos a erro.

### 2. P1 — A operação de twist pode alterar a direção que deveria preservar

Local: `viewer/mikapo_mixamo_solver.js:658` e construção equivalente do witness em `:716`.

O solver usa `setFromUnitVectors` entre vetores laterais projetados no plano perpendicular ao osso. Para vetores não antiparalelos, o eixo do produto vetorial corresponde ao eixo do osso. Quando os vetores são exatamente opostos, a API escolhe um eixo perpendicular possível; esse eixo **não necessariamente coincide com o eixo do osso**. Assim, uma operação destinada somente à torção pode também mudar o aim.

Com `fitPalm=true`, direção fixa e across oposto, medi erro de aim de **70,5°** no caso sintético. No rig real: **29,0°/30,4°** nos antebraços e **76,6°/72,1°** nas mãos. O caso é uma singularidade específica; não afirmo que apareça a cada frame. Ele refuta, porém, a garantia dos comentários de que o ajuste de roll “nunca” altera a direção ou inverte a pose.

Direção de correção: calcular o ângulo assinado no plano com `atan2(axis·(a×b), a·b)` e construir o quaternion **sobre o eixo conhecido do osso**; resolver a continuidade perto de ±π com estado temporal. O witness também merece teste de invariância de aim.

O contrato de `setFromUnitVectors` é alinhar dois vetores; ele não promete preservar um terceiro eixo escolhido pelo chamador. Referência: [Three.js Quaternion](https://threejs.org/docs/pages/Quaternion.html). A reprodução usou a implementação 0.160.0 efetivamente usada pelo projeto.

### 3. P1 — O solver perde a qualidade da medida e não mantém a última pose válida

Locais: `auxFromPose33:955`, `computeHandPalmAxes:1144`, reset em `updateAvatarPose:1327`, wrappers live em `:1251` e produção NLF em `scripts/nlf_fast_path.py:144`.

O MediaPipe fornece visibilidade/presença, mas o auxiliar de mão guarda somente coordenadas. A API do solver não recebe confiança por junta. O helper NLF reduz a predição a `poses3d` e também não transporta as incertezas ao retarget. Consequentemente, um ponto ocluído plausível recebe praticamente o mesmo tratamento de um ponto bem observado. A documentação oficial descreve a visibilidade disponível no [Pose Landmarker](https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker).

Além disso, `computeHandPalmAxes` normaliza a separação indicador–mindinho antes da avaliação angular. Acima do corte de degeneração, uma separação de **60 mm** e outra de **1,1 mm** tornam-se o mesmo vetor unitário. O fade então mede principalmente a relação angular com o osso, não a qualidade da observação. Isso não torna normalização errada por si só; torna incompleta a interpretação de `obs` como confiança.

Todo frame começa restaurando repouso. Se uma direção colapsa e o writer retorna sem escrever, não há “held local” anterior aplicado, apesar do comentário do arquivo. No teste do rig real, fazer punho coincidir com cotovelo gerou um salto local de **144,0°** e retorno exato ao repouso. Uma coordenada `NaN` também contaminou o quaternion: os guards baseados somente em comparação de comprimento não rejeitam valores não finitos.

O upstream MiKaPo tem gate de visibilidade e estado de orientação mantida (`external/MiKaPo/src/lib/solver.ts:190`, `:281`, `:505`). Essa proteção não foi preservada no port atual.

Direção de correção: contrato de qualidade explícito; validação de finitude; retenção da última orientação válida; recuperação gradual; tratamento separado para geometria degenerada e detecção de baixa confiança.

### 4. P1 — O referencial corporal degenerado pode deslocar pontos mesmo com correção zero

Locais: `src/pose_lab/align.py:36`, `scripts/export_corrected.py:135`, `scripts/serve_lab.py:365`.

Se os ombros coincidem, o código troca a **escala** pelo comprimento entre quadris, mas não reconstrói o **eixo lateral**. A matriz resultante pode ter determinante zero e deixa de representar uma rotação. Se os eixos lateral e vertical forem colineares, ocorre problema semelhante.

Reprodução: com ombros coincidentes e `delta=0`, a aplicação da correção deslocou targets em até **524,4 mm** no exemplo controlado. Com a pose não degenerada, o deslocamento foi zero e `det(R)=1`. Portanto, o fallback não é uma operação identidade segura.

Direção de correção: testar condicionamento da base; tentar um referencial alternativo dos quadris; usar última base válida ou pass-through quando não houver informação suficiente. Esse é um problema de pré-processamento, antes do avatar.

### 5. P1 — As métricas chamadas “mm” não recuperam a escala métrica

Locais: `scripts/train.py:71`, `scripts/eval.py:66`, números do README e de `docs/04_evaluation.md`.

`eval_delta` calcula diferenças no body frame normalizado pela largura dos ombros e multiplica por 1000. O próprio comentário reconhece que são “bf_mm”, não metros reais, mas as chaves, relatórios e documentação chamam esses valores de `mpjpe_*_mm`.

Reprodução pela função original: erro de **0,25 largura de ombro**, em pessoa com ombros de **0,4 m**, equivale a **100 mm**. A função reporta **250 mm**.

Logo, o número publicado de aproximadamente **194,8 “mm”** não pode ser interpretado diretamente como erro físico de 19,48 cm. A melhora relativa no espaço normalizado continua sendo evidência útil; ela não equivale automaticamente à mesma melhora percentual num agregado de MPJPE em metros, que pondera cada amostra com sua escala.

Direção de correção: recuperar a escala **por amostra** ou avaliar as posições reconstruídas em metros; nomear unidades normalizadas corretamente; manter métricas separadas de posição, orientação e estabilidade temporal. Não basta multiplicar todo o resultado pela largura média de ombros.

### 6. P2 — O caminho de cabeça Pose-33 alinha o eixo do crânio à frente da face

Local: `viewer/mikapo_mixamo_solver.js:1096–1117`.

A calibração registra como direção primária de Head a continuação longitudinal do crânio. O caminho SMPL usa `head−neck` como up. Já o caminho Pose-33 manda alinhar essa direção ao vetor orelhas→olhos, que representa **frente da face**. A direção usada para o pescoço também é orelhas→nariz, não pescoço→cabeça.

Em um rig sintético com eixo craniano vertical e observações faciais neutras, esse caminho inclinou o eixo da cabeça **76,5°**. É uma demonstração da troca de grandeza física, não uma afirmação de que o GLB real esteja sempre inclinado exatamente esse valor.

Direção de correção: formar uma base facial completa e mapear a base facial de repouso do rig para ela, com eixos de up e forward distintos.

### 7. P2 — As translações de ombro/quadril misturam rotação global, deformação e escala local

Local: `viewer/mikapo_mixamo_solver.js:834–880`.

O código subtrai vetores esquerda/direita centrados entre primeira pose e pose atual em coordenadas da fonte. Uma rotação rígida do tronco muda esses vetores e pode ser interpretada como deslocamento adicional dos pivôs, mesmo que não haja encolhimento de ombro ou mudança anatômica. A saída também depende da primeira pose usada como referência.

O offset em unidades de mundo é convertido ao parent somente por quaternions. Falta desfazer a escala do parent. Reproduzi um offset adicional de **10 cm** numa rotação rígida de 90°; com esqueleto geometricamente equivalente e root scale=0,01, o deslocamento foi **1 mm**. A resposta difere por fator 100 devido à representação do asset. Isso é particularmente relevante para FBX autorado em centímetros.

Direção de correção: separar movimento rígido de deformação no referencial do tronco; converter offsets pela transformação completa do parent; definir calibração/referência explícita, independente de começar o clip em guarda, extensão ou movimento.

### 8. P2 — Há incoerência temporal entre corpo corrigido e mãos no live

Locais: `viewer/live.html:2170`, `:2242`, `:2292`; relógio offline em `viewer/index.html:638`, seeks em `:932`.

O request de correção copia auxiliares do frame enviado, o que é bom. Entretanto, enquanto chegam frames novos, `onPoseFrame` reaplica **a última pose corrigida** juntamente com **os auxiliares crus mais recentes**. Corpo e orientação da mão podem pertencer a instantes diferentes. A chegada da resposta alterna novamente para os auxiliares snapshotados. Isso pode causar oscilações mesmo sem trocar o modo visível.

No offline, o filtro recebe `performance.now()` em vez do tempo da amostra. Os resets existem ao carregar clip, mas o seek não reseta o filtro. O mesmo frame pode dar resultado diferente conforme a velocidade e a ordem de navegação. Como o solver só é atualizado quando o índice muda, uma pose filtrada também pode ficar parada antes de convergir completamente ao frame escolhido.

A troca de backend live também não chama diretamente o reset de motion/filtros em `setPoseBackend`. Essas são constatações de fluxo; não medi o tamanho do erro perceptual em webcam nesta auditoria.

Direção de correção: corpo, auxiliares, fonte, sequência e timestamp numa amostra indivisível; relógio da captura; política de descarte/interpolação de resultados atrasados; reset em descontinuidades e avaliação estática sem suavização herdada.

### 9. P2 — O caminho opcional `twist` muda filhos depois de eles terem sido resolvidos

Locais: `viewer/mikapo_mixamo_solver.js:1259`, `:1525`, `:1583`.

O código resolve Hand e só depois adiciona torção a ForeArm. Por hierarquia, o filho Hand gira junto. Uma torção posterior de 30° no antebraço alterou o quaternion mundial da mão já resolvida em **30°**. Isso pode desfazer a orientação da palma anteriormente calculada.

Essa segunda escrita também usa o mesmo filtro e timestamp. O ramo `dt<=0` reseta o estado de derivada; na reprodução, a derivada passou de **−3,68 para zero** na segunda escrita do mesmo frame.

O parâmetro não é usado pelos wrappers live e baker top atuais que inspecionei; é um defeito de um caminho opcional, não a explicação principal do live de hoje.

Direção de correção: compor o alvo final antes da única filtragem do frame, em ordem hierárquica; resolver/compensar filhos após alterar pais.

### 10. P2 — As sombras de comparação podem herdar auxiliares da fonte principal

Local: `viewer/index.html:620`, chamadas de sombra em `:837` e `:846`.

O wrapper sempre obtém `auxForFrame(fi)` da variável global `poseAux`, independentemente de o modelo recebido ser principal ou sombra MediaPipe. Com NLF principal e sombra MP, braços MP podem receber mão/cabeça NLF. A comparação deixa de isolar as fontes e contradiz o contrato de uma fonte declarada por pose.

Direção de correção: auxiliares por fonte e por overlay; ausência de auxiliar declarada explicitamente; nunca resolver todos os avatares a partir de uma variável auxiliar global.

### 11. P2 — “Plantar no chão” é uma aproximação global, não um solver de contato

Local: `viewer/mikapo_mixamo_solver.js:935` e chamada em `:1585`.

A função move o modelo inteiro para que o ponto mais baixo entre os ossos Foot/Toe esteja na altura zero. Ela não mede a sola da malha, não detecta contato, não trava pés em XZ e não preserva saltos com ambos os pés no ar.

Reprodução: elevar a raiz em **0,5 m** e aplicar a função anulou integralmente essa elevação. Isso pode ser aceitável para uma demo de boxe sempre apoiado. Não constitui retargeting corporal geral e pode explicar parte dos problemas de posição, deslizamento e altura.

Direção de correção: política de contato por pé, offset geométrico da sola e solução de raiz/pernas coerente; modo sem fixação para fase aérea. Avaliar posições de punhos/contato separadamente das direções dos ossos.

### 12. P2 — A evidência de qualidade ainda não certifica o uso pretendido

O split por vídeo evita o vazamento mais óbvio de frames aleatórios, mas a validação é de shots do mesmo vídeo predominante no treino. Tracks `person_XXX` não são identidades humanas independentes. O próprio README reconhece essa limitação. O melhor corretor não foi treinado para supervisionar orientação da palma.

Há diagnósticos valiosos, mas vários números foram medidos contra o fit, em um clip, com flags distintas e resultados anteriores ainda presentes. `palm_fidelity_final.json`, por exemplo, contém resultados antigos que outros registros já apontam como medição inadequada. É preciso vincular relatório a hash de solver, asset, fonte, flags, frames e definição da métrica antes de chamar uma versão de validada.

Também há contradições de documentação: `docs/02_dataset_and_features.md` ainda descreve Procrustes rígido por sequência, enquanto o pareamento atual faz translate+scale por frame e preserva rotação. A documentação 07 descreve output SMPL de 72 valores, e a 08 registra SMPL-X de 165. São modos distintos, mas o texto precisa delimitar isso para evitar novo erro de integração.

## O que os 1.056 frames mostram hoje

Reexecução com rig real, filtros padrão, intervalo nominal de 30 Hz. “Saltos” são diferenças angulares entre quaternions mundiais de frames consecutivos; são contagens somadas dos dois ossos Hand, não frames únicos. Um salto não é automaticamente erro físico, pois há movimento real, mas a comparação evidencia instabilidade que a suavização não elimina.

| Entrada/configuração | Saltos de mão >90° | Maior salto |
|---|---:|---:|
| `top_frames.json`, palma do fit, filtrado | 0 | 89,0° |
| `abl_live.json`, posições ajustadas, comportamento live, filtrado | 13 | 166,4° |
| x55 cru, filtrado, sem espelhamento | **22** | **165,3°** |
| x55 cru, filtrado, espelhamento selfie do live | **24** | **165,3°** |

O sinal de entrada também tem problemas: na mão direita, a normal da palma x55 teve máximo de **104,5°** entre frames e dois saltos acima de 90°. A esquerda não teve saltos de normal acima de 90° nesse clip, mas o avatar cru filtrado sem espelhamento teve **13 saltos** no osso da mão esquerda. Não são a mesma grandeza e não permitem atribuir todos os eventos a um único bug; o caso sintético de 2°→178° é a evidência isolada da amplificação pelo solver.

As métricas novas não devem ser misturadas com os antigos “66–87° por frame de roll”: tratam de grandezas e medições diferentes. Nesta auditoria o código de cada métrica está preservado.

## Avaliação das decisões de engenharia

### Decisões boas e justificáveis

- Usar quaternions, cache de repouso e transformação mundial→local: base adequada para rigs hierárquicos.
- Medir os eixos do rig e escolher filhos por nomes/ordem de aliases: corrige dependências frágeis da ordem do exportador.
- Investigar a geometria dos dedos e rejeitar PCA instável da luva: decisão sustentada por condicionamento, não somente impressão visual.
- Compartilhar referência de palma entre mão e antebraço: reduz inconsistência entre ossos acoplados.
- Separar teacher offline de inferência leve e usar modelo causal residual: arquitetura razoável para orçamento de jogo.
- Canonizar tempo em 30 Hz e manter o frame corporal do MediaPipe original ao aplicar residual: evita inconsistências de treino/inferência.
- Manter teste por vídeos, registrar limitações e rejeitar fine-tuning que piora teste geral: disciplina de pesquisa útil.
- Medir estágios do NLF antes de acelerar; comparar backends e descartar frames antigos na fila: decisões de desempenho sensatas.
- Registrar hipóteses rejeitadas e reconhecer validação circular: importante para uma pesquisa evolutiva.

### Decisões que ainda não sustentam produção

- Heurísticas como strengths fixos, amplificação lateral do torso, repouso ereto canônico, plano de dobra preferido em ±Z, neutral de clavícula e suavização Laplaciana podem funcionar para os assets/clips testados, mas precisam de contrato e calibração por rig/fonte.
- FK por direções transfere orientação dos segmentos, não garante que o punho fique na posição-alvo. As proporções do avatar, pivôs transladados e contato com chão determinam o endpoint. Para um jogo em que o alcance visual precisa coincidir com o alcance medido, essa diferença precisa ser medida ou resolvida com IK/restrições.
- O runtime e o oracle offline têm flags e dados diferentes; os gates devem testar explicitamente o caminho que será entregue.
- UI, transporte, calibração e controle temporal estão concentrados em um `live.html` com milhares de linhas; `serve_lab.py` combina HTTP, checkpoints, NLF, backends e estado de tracking. Isso amplia o risco de alteração local afetar outro modo.
- Flags globais de mão e preferências persistidas por `localStorage` podem mudar resultados sem aparecer numa identificação completa do experimento. `swapCrossOrder` continua na UI embora seja ignorada pelo solver.
- Há muitas alterações locais e artefatos importantes ainda não rastreados. Um checkout limpo não necessariamente reproduz o estado atual. A unidade de release precisa incluir código, assets, contratos e forma de obter modelos, sem exigir commit de todos os vídeos/arquivos grandes.
- Os testes atuais do core não exercitam os casos geométricos decisivos. Os scripts de experimento são úteis, mas não substituem gates determinísticos executados em cada mudança do solver.

Há ainda problemas de infraestrutura por inspeção: `AsyncPoseWorker` cria duas threads por conexão e seus loops são infinitos; o fechamento do websocket cancela o sender, sem encerrar os workers (`scripts/nlf_engine.py:622`, `:705`, `scripts/serve_lab.py:944`). A fila asyncio de saída é ilimitada, embora o caminho síncrono tenha fila limitada. Não fiz teste de carga nem medi vazamento; são pontos de ciclo de vida a corrigir antes de uso prolongado/múltiplas sessões.

## Seria trabalho de um engenheiro de alto nível?

**Como protótipo de pesquisa, sim: um engenheiro experiente poderia produzir e iterar uma base assim. Como entrega final confiável, eu não aprovaria este estado.**

O problema não é escolher FK ou usar heurísticas; essas escolhas são comuns e podem ser adequadas ao produto. O problema é uma função de twist que altera aim numa singularidade, uma regra que transforma uma entrada contínua em giro de quase 180°, falta de estado válido em dropout, conversões que ignoram escala e evidência publicada com unidade incorreta. Esses pontos exigem invariantes, testes e contratos explícitos.

Um trabalho de alto nível também manteria uma fronteira clara entre “acompanha os pontos do modelo”, “acompanha a rotação estimada pelo fit” e “acompanha a pessoa real”. Hoje essas três afirmações ainda não estão certificadas pelo mesmo protocolo.

Minha avaliação é: **base de laboratório com progresso técnico real e dívida de engenharia importante; não um solver genérico de captura corporal pronto para produto**. A associação a uma grande empresa não torna um algoritmo correto; as garantias e os testes são a referência adequada.

## Ordem recomendada de trabalho

1. Corrigir continuidade/polaridade da palma e twist de eixo fixo; adicionar casos de 89°→91°, 179°→180°→181°, rotação da raiz e invariância do aim.
2. Restaurar confiança/incerteza, rejeitar não finitos e definir held pose/recovery; corrigir bases degeneradas antes de aplicar residual.
3. Unificar corpo+aux+timestamp+fonte por frame; remover mistura temporal e tornar replay/seek determinísticos.
4. Corrigir mapeamento facial, translações com escala e auxiliares por overlay; decidir explicitamente as garantias de posição/contato.
5. Corrigir unidades das métricas e gerar relatório identificado por hash de código/asset/configuração.
6. Validar em novas pessoas/sessões com braços acima da cabeça, cotovelos retos, pronação sustentada, braços cruzados, oclusão, perfil, giro do corpo, baixa iluminação e perda/retorno da pessoa. Testar os dois rigs e FPS/cadências diferentes.
7. Só então comparar aquisição de mãos mais forte, fit amortizado ou head destilado de rotações. Uma rede melhor não corrige uma conversão geometricamente descontínua a jusante. Um head supervisionado apenas pelo fit também não prova precisão contra a realidade.

## Artefatos e reprodução

Nesta pasta:

- `probe_solver.mjs`: usa o solver original e o rig GLB; gera reproduções e replay.
- `prepare_sequence.py`: converte os x55 já existentes para o mesmo contrato de pontos/auxiliares.
- `probe_preprocessing.py`: testa as funções Python originais e gera inventário de código.
- `solver_probe_results.json`, `sequence_probe_results.json`, `input_sequence_results.json`, `preprocessing_probe_results.json`: resultados detalhados.
- `source_inventory.json`: mapa dos arquivos próprios.
- `three.module.mjs`: cópia da versão 0.160.0 baixada do mesmo URL usado no projeto, exclusivamente para o probe.

Da pasta pai do projeto:

```powershell
python pose_corrector_lab/scripts/smoke_test.py
python pose_corrector_lab/experiments/review_20260930/prepare_sequence.py
python pose_corrector_lab/experiments/review_20260930/probe_preprocessing.py
node pose_corrector_lab/experiments/review_20260930/probe_solver.mjs
```

O replay depende dos assets e das sequências já presentes nesta máquina. Nenhuma correção de produção, novo treino ou publicação foi feita.


## Complemento: validação visual executada depois desta análise

Foram feitas novas inferências com as 13 fotos como webcam simulada na própria página `/live`, com renderização e inspeção dos dois personagens. Consulte [resultado_visual.md](live_visual/resultado_visual.md) e [galeria.html](live_visual/galeria.html). O teste aquecido ficou estável nas fotos paradas e não reproduziu o giro contínuo das mãos. A orientação dos segmentos dos braços acompanha bem os pontos recebidos; isso não mede precisão contra a pessoa real. A primeira rodada expôs um problema upstream de inicialização/recorte, e o fechamento dos dedos não é aplicado pelo solver live. A conclusão de maior instabilidade do live continua limitada à sequência e aos probes anteriores; não foi realizada comparação visual A/B completa com o offline.
