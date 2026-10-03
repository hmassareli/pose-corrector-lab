# HEAVY HANDS — eficiência, performance e nocaute

Relatório de engenharia • 3 de outubro de 2026 • código local, medições reproduzíveis e documentação oficial.

## 1. Recomendação

**Manter Three.js neste momento. Priorizar malhas e carregamento, eliminar trabalho repetido no navegador e medir renderização junto com a inferência NLF. Avaliar WebGPU depois, com a mesma cena e os mesmos movimentos.**

O maior sinal concreto encontrado está nos personagens: o Prism tem **1.494.256 triângulos**, o Titan tem **294.525**, e os dois arquivos GLB somam **122,87 MB decimais**. A cena de teste chegou a aproximadamente **1,92 milhão de triângulos**. Isso oferece uma oportunidade muito mais específica que trocar de biblioteca por expectativa de velocidade.

Não há evidência de que outra engine, por si só, resolveria nosso gargalo. Há evidência de que o projeto transporta e anima geometria muito densa, usa CPU para diversos ajustes da malha e compartilha a GPU com reconhecimento corporal. O maior ganho final dependerá de qual desses custos domina no computador do jogador.

“Gratuito” neste relatório significa **sem necessidade de assinatura, servidor adicional ou compra de hardware para experimentar**. Desenvolvimento, validação e manutenção continuam tendo custo de tempo. Trocar de engine pode ter licença gratuita e ainda ser a opção mais cara em engenharia.

**Entrega desta revisão:** análise e instrumentos de medição; implementação local da queda com relaxamento articular. As otimizações de malhas, WebGPU, rede e inferência abaixo são propostas, não mudanças já aplicadas. Nenhuma melhoria percentual de FPS é atribuída a uma proposta ainda não testada.

## 2. O que foi examinado e medido

Foram examinados renderização, arena, efeitos, rig/retarget, mãos, contato com o próprio corpo, pés, legendas, áudio, captura, ponte do tracker, NLF e transporte multiplayer. O jogo usa Three.js **0.160.0**, carregado pelo import map de `viewer/boxing.html`, e `WebGLRenderer`.

### Benchmark novo: renderização sem inferência ao vivo

Ambiente: Windows, Chromium headless 149, ANGLE/D3D11, **NVIDIA GeForce RTX 3060**; viewport 1366 × 768 e device pixel ratio 1,5. Cena em terceira pessoa, pose neutra sintética a aproximadamente 30 Hz e adversário procedural. Duas rodadas de cinco segundos por perfil, em ordem alta/balanceada/baixa e depois inversa, com aquecimento entre mudanças. Amostragem de CPU coletada separadamente.

| Perfil existente | Resolução interna | FPS observado | Intervalo p95 entre quadros | Triângulos no contador | Draw calls no contador |
|---|---:|---:|---:|---:|---:|
| Alta | 2049 × 1152 | 59,9–60,2 | 16,8 ms | ~1,921 milhão | 66–68 |
| Balanceada | 1707 × 960 | ~60,2 | 16,7–16,8 ms | ~1,880 milhão | 66–70 |
| Baixa | 1161 × 652 | ~60,2 | 16,7 ms | ~1,838 milhão | 62–64 |

São leituras de `renderer.info` no cenário observado; movimentos e efeitos mudam as contagens. Os FPS estão limitados pela apresentação próxima de 60 Hz. O teste **não demonstra empate de capacidade máxima entre os perfis**, nem desempenho a 60 FPS com webcam/NLF simultâneos.

O tempo mediano da chamada JavaScript `renderer.render` ficou entre 0,3 e 0,6 ms, conforme o perfil. **Isso mede submissão/comportamento da chamada na CPU, não duração real da GPU.** Houve valores máximos isolados de 27,5 e 38,6 ms; sem uma captura de tracing correspondente não é correto atribuí-los a shaders, GC ou driver.

O perfil de CPU teve predominância de amostras ociosas. Entre as funções ativas apareceram `soleBottom`, transformações de ossos, skinning, retarget e contato das luvas. As contagens individuais foram pequenas: servem para orientar investigação, não para afirmar que determinada função consome uma porcentagem precisa do jogo.

### Inventário de personagens

| Asset | Arquivo | Vértices | Triângulos | Textura embutida |
|---|---:|---:|---:|---|
| Prism | 73,60 MB | 763.162 | 1.494.256 | PNG 4096²; 15,98 MB |
| Titan/Trellis | 49,27 MB | 730.862 | 294.525 | PNG 2048²; 7,69 MB |

Os GLBs inspecionados não declaram extensões de compressão. Cada personagem aparece como uma mesh/material no cenário medido. Portanto, **juntar as meshes desses dois personagens não é a grande oportunidade**: reduzir vértices, triângulos, transferência e memória é mais relevante.

O Titan tem muitos vértices em relação ao número de triângulos. É um motivo para investigar vértices duplicados, costuras de UV e atributos, não uma autorização para fundir tudo: vértices que diferem em normal, UV ou pesos de skin podem precisar continuar separados.

Uma textura RGBA8 4096² ocupa aproximadamente 64 MiB sem mipmaps e 85,3 MiB com a cadeia completa, se carregada nesse formato. O PNG pequeno no disco não implica textura pequena na GPU. Esses valores são **estimativas de formato**, não medição de VRAM total do processo.

### Estado observado da inferência

A consulta somente de leitura a `/api/nlf_status` retornou NLF-S, `smplx55`, `dense=false`, device `cuda` e backend de features **DirectML**. A baseline registrada pelo serviço era p50 **9,01 ms**, p95 **9,98 ms**. O cache listava candidatos TRT, DML, OpenVINO e ORT; o serviço também já tinha contador de rebalanceamento em execução.

Esses números são **metadados da calibração**, não uma nova medição da câmera até a tela. Não significam que a webcam entregue 111 poses novas/s, nem que a latência total seja de 9 ms.

### Limites da evidência

Não foram medidos nesta revisão: sessão humana de webcam, GPU integrada, celular, Safari/Firefox, uso térmico prolongado, consumo elétrico, temporização GPU por queries, latência multiplayer pela internet e comparação executável WebGPU × WebGL. O relatório distingue fatos do código, medições locais e hipóteses de ganho. A configuração completa e os resultados brutos estão em `experiments/performance_audit_20261003`.

## 3. Melhorias já existentes — não contar duas vezes

| Área | Implementação atual confirmada |
|---|---|
| Arena | Torcida usa `InstancedMesh`; atualização limitada a 20/30 Hz conforme perfil. |
| Qualidade | Alta/balanceada/baixa já alteram pixel ratio, sombras, torcida e efeitos. |
| Sombras | Principal 2048 no alto, 1024 no balanceado; baixa desliga sombras. |
| Placar 3D | Redesenha a textura apenas quando o estado muda, com chave de cache. |
| Efeitos | Partículas usam buffers/pools limitados e geometria instanciada; não há obrigação de criar uma mesh por partícula. |
| Inferência | NLF-S rápido, query de 55 juntas, crop 256² e sem ajuste denso iterativo no caminho normal. |
| Backends | TRT FP16, DML, OpenVINO CPU e ORT CPU; calibração, cache, warmup, fallback e rebalanceamento já existem. |
| Detector | YOLO periódico, tracking de caixa e worker separado; não detecta do zero a cada apresentação. |
| Filas | Política de manter frames recentes, filas limitadas e no máximo dois pedidos em voo no browser. |
| Tracker embutido | Renderização de laboratório já suspensa no modo `gameBridge`; não existe ganho novo em “desligar o segundo render”. |
| Rede | Poses/estado em vez de vídeo, aproximadamente 30 Hz, limite de buffer e canal WebRTC não ordenado/sem retransmissão quando usado. |
| Combate | Simulação em passos de 1/60 s separada da suavização de apresentação. |
| Diagnóstico | Gravação detalhada tem guardas e amostragem; não fica coletando todos os estágios quando está desligada. |

Documentos anteriores são úteis, mas algumas propostas deles já foram implementadas. Por exemplo, seleção adaptativa de backend e perfis gráficos devem ser aperfeiçoados, não apresentados como recursos ausentes.

## 4. Carteira de melhorias sem gasto recorrente

Prioridade **P0**: base de medição/proteção contra regressão. **P1**: primeiro investimento recomendado. **P2**: depende de um gargalo confirmado ou tem maior esforço. **P3**: arquitetura/experimentação. Esforço **B**: localizado; **M**: vários componentes; **A**: projeto maior. Potencial é qualitativo e específico ao recurso afetado; não é promessa de FPS.

### 4.1 Geometria, texturas, memória e carregamento

| ID / prioridade | Mudança proposta | Benefício esperado | Esforço / risco visual |
|---|---|---|---|
| G1 / P1 | Produzir versões otimizadas dos dois GLBs com simplificação consciente de skin/UV. Testar degraus como 300k, 150k e 75k triângulos no Prism. | Alto potencial em GPU, skinning, memória, download e preparação. | M; revisar de perto rosto, dedos, luvas, ombros e joelhos. Metas de triângulos são candidatos, não qualidade aprovada. |
| G2 / P1 | Remover dados não referenciados e fundir somente vértices equivalentes em todos os atributos. | Menos bytes e vértices, especialmente onde há duplicação real. | B/M; preservar normais, pesos e costuras. |
| G3 / P1 | Ordenar índices/vértices para cache e aplicar compressão Meshopt ou Draco ao GLB. Comparar custo de decodificação. | Download menor; ordenação pode melhorar reutilização de vértices. | M; compressão sozinha não reduz o número de triângulos renderizados. Configurar o decoder no loader. |
| G4 / P1 | Avaliar KTX2/Basis, preferindo candidato de maior qualidade nos rostos e luvas. | Potencial alto de redução de VRAM e largura de banda de textura. | M; conferir cor, detalhes e formato transcodificado no dispositivo. |
| G5 / P2 | Separar detalhe de geometria e detalhe de superfície: preservar silhueta, transferir relevo fino para normal map. | Permite malhas muito menores mantendo aparência. | M/A; bake e revisão artística, sem achatamento do rosto. |
| G6 / P2 | LOD por tamanho na tela: modelo mais detalhado no close e reduzido no plano geral. | Reduz custo quando o detalhe seria invisível. | M; evitar saltos perceptíveis e manter rig/contatos compatíveis. |
| G7 / P1 | Carregar primeiro o personagem selecionado; adiar adversário/alternativas até serem necessários, com pré-carga oportuna. | Entrada mais rápida, menos pico de memória no lobby. | M; evitar iniciar uma luta antes de completar os recursos necessários. |
| G8 / P1 | Guardar modelo-base e clonar esqueleto corretamente; compartilhar texturas/geometria quando seguro, com contagem de referências. | Evita download, parse e recursos duplicados ao repetir/trocar personagem. | M; não compartilhar pose viva nem destruir recursos ainda usados. |
| G9 / P2 | Auditar descarte de texturas e materiais substituídos e cancelamento de trocas assíncronas. | Reduz crescimento de memória em sessões longas. | B/M; descarte atual cobre geometria/material, mas textura compartilhada exige propriedade explícita. |
| G10 / P1 | Pré-calcular suportes de pés, cabeça, luvas, legendas e KO no pipeline dos assets; persistir metadados por hash de asset. | Evita varrer centenas de milhares de vértices a cada criação do avatar. | M; invalidar os dados quando malha, escala ou rig mudar. |
| G11 / P2 | Cache HTTP com nomes versionados, compressão adequada e distribuição local das dependências fixadas. | Menos downloads repetidos e menor dependência de CDN no início. | B/M; evita principalmente espera, não acelera automaticamente o quadro já carregado. |
| G12 / P2 | Converter o FBX usado no jogo para GLB validado, mantendo materiais/rig. | Pipeline único e possibilidade de aplicar as mesmas otimizações. | M; benefício deve ser medido, pois esse FBX já é muito menor que os GLBs densos. |

Ferramentas candidatas: Blender, glTF Transform e meshoptimizer. A CLI do glTF Transform oferece inspeção, deduplicação, remoção de dados, simplificação, ordenação e compressão; seus presets devem ser avaliados para cada asset. [Documentação oficial](https://gltf-transform.dev/cli).

**Aceite de G1–G6:** comparar os três ângulos de câmera em resolução final, guarda encostada no rosto, braço estendido, hook, pescoço girado e KO. A comparação deve avaliar silhueta, deformação e contatos, além de imagens estáticas. As amostras de colisão derivadas da malha precisam ser regeneradas. Preservar os originais e permitir troca imediata entre candidato e referência.

### 4.2 CPU, retarget e contato

| ID / prioridade | Mudança proposta | Benefício esperado | Esforço / risco |
|---|---|---|---|
| C1 / P0 | Instrumentar fases: simulação, retarget, mãos, solo, autocontato, legenda, submissão e captura. | Identifica onde vale investir; separa pico e custo sustentado. | B/M; amostrar para não transformar medição em gargalo. |
| C2 / P1 | Reutilizar vetores, quaternions, arrays e matrizes nos caminhos quentes. | Menos alocações/GC e possíveis travadinhas. | M; cuidado com valores temporários retidos por outros componentes. |
| C3 / P1 | Atualizar matrizes por etapa e cachear posições/quaternions mundiais usados repetidamente. | Evita percorrer hierarquias repetidas vezes para obter a mesma informação. | M; invalidar após cada IK/correção que realmente altera o rig. |
| C4 / P1 | Compartilhar atualização de esqueleto e buffers temporários entre as consultas das duas solas, hitboxes e contatos. | Menos skinning CPU e objetos temporários. | M; preservar resultado com deslocamento final de grupo. |
| C5 / P1 | Colocar broad phase no contato luva–rosto e parar passes quando o erro já estiver abaixo da tolerância. | Economiza trabalho quando mãos estão longe ou o contato já convergiu. | M; manter sweep para socos rápidos e casos de oclusão. |
| C6 / P1 | Revisar os quatro passes externos de autocontato, os loops internos e três passes de separação corporal com métricas de erro. | Potencial relevante nos piores quadros de guarda fechada. | M; reduzir cegamente para um passe pode reintroduzir penetração. |
| C7 / P2 | Resolver parte do retarget por nova amostra e interpolar a apresentação a cada frame. | Menos trabalho redundante quando render > inferência. | A; não acrescentar latência a mãos/cabeça nem alterar o detector de golpes. |
| C8 / P1 | No lobby, interromper atualização do ator que ficará invisível naquele quadro. | Remove retarget, chão e contato sem efeito visual útil. | B/M; reativar e atualizar antes de mostrá-lo. Hoje a visibilidade é decidida depois desses cálculos. |
| C9 / P1 | Aplicar flags de material, visibilidade e sombras apenas nas transições de câmera/estado. | Evita `traverse` e escritas de estado por frame para valores invariáveis. | B; garantir primeiro frame correto ao alternar primeira/terceira pessoa. |
| C10 / P2 | Usar buffers tipados para poses e reduzir serialização/recriação de `Vector3` na ponte. | Menor lixo e custo de cópia. | M; a pose atual é pequena, portanto medir antes de trocar todos os formatos. |
| C11 / P2 | Worker para tarefas independentes de preparo/decodificação; OffscreenCanvas somente com perfil justificando mover o renderer. | Melhor resposta da thread principal. | A; transferências e sincronização têm custo; não reduzem o trabalho total por magia. |

Referências locais principais: `renderActor`, `frame` e `separateBodies` em `viewer/boxing.js`; `soleBottom` em `boxing_feet.js`; `NativeGuardContact.apply/sweep` em `avatar_self_contact.js`; `updateAvatarPose` em `mikapo_mixamo_solver.js`.

### 4.3 GPU, luz, efeitos e qualidade adaptativa

| ID / prioridade | Mudança proposta | Benefício esperado | Esforço / risco visual |
|---|---|---|---|
| R1 / P1 | Perfil automático baseado em frame time sustentado, com histerese e recuperação lenta. | Mantém fluidez sem obrigar o jogador a configurar manualmente. | M; aproveitar os três perfis que já existem e permitir escolha manual. |
| R2 / P1 | Ajustar resolução interna dinamicamente em passos pequenos, preservando HTML/HUD nítidos. | Alto potencial se o limite for pixels/sombreamento. | M; evitar oscilação e borrar luvas/rosto em momentos importantes. |
| R3 / P2 | Restringir casters da sombra dinâmica, estabilizar frustum e combinar iluminação estática com sombra dinâmica dos lutadores. | Menos geometria/sombreamento nos mapas de sombra. | M; conservar contato dos pés e leitura espacial. Não congelar a sombra inteira enquanto os lutadores se movem. |
| R4 / P2 | Representação simplificada dos personagens na passagem de sombra. | Reduz custo de sombras das malhas densas. | M; validar correspondência visual e skinning. |
| R5 / P2 | Agrupar apenas objetos estáticos compatíveis da arena, por material e região de visibilidade. | Menos draw calls de objetos pequenos. | M; o benchmark tem ~70 calls, então este não é o primeiro alvo. |
| R6 / P2 | Medir transparência/overdraw dos cones de luz, rastros, brilho e partículas. Reduzir área vazia e resolver efeitos em menor resolução, se necessário. | Economia de pixels preservando impacto visual. | M; partículas já são instanciadas. |
| R7 / P2 | Para futuras arenas grandes, animar torcida na GPU ou usar sprites/impostores distantes. | Mais escala sem aumentar trabalho JS proporcionalmente. | M/A; a torcida atual já está instanciada e limitada a 20/30 Hz. |
| R8 / P1 | Pré-aquecer shaders e variantes realmente utilizadas antes da luta. | Menos engasgos na primeira ocorrência de sombra/material/efeito. | B/M; evitar compilar todas as combinações possíveis sem necessidade. |
| R9 / P2 | Primeira pessoa: comparar mesh específica de braços/torso ou recorte estrutural contra descarte por shader. | Pode evitar processar regiões invisíveis da malha. | A; preservar sombras, luvas, identidade e troca de câmera. |
| R10 / P2 | Auditar culling/bounding volumes dos skinned meshes e instâncias. | Evita desenhar objetos fora da câmera sem fazê-los desaparecer indevidamente. | M; um bounding box estático incorreto pode cortar braços em movimento. |

Exemplo calculado: num aparelho cujo perfil alto usa DPR 1,7, passar a 1,25 reduz pixels para **54,1%** do original; passar a 1,0 reduz para **34,6%**. São reduções de pixels, **não de tempo total de frame**. No teste com DPR 1,5, o alto já estava limitado a 1,5. Os valores não devem ser misturados.

A baixa qualidade do teste reduziu somente cerca de 4,3% dos triângulos em relação à alta, porque os personagens continuam iguais. É por isso que resolução adaptativa e otimização de malhas se complementam.

### 4.4 Captura, inferência e latência de movimento

| ID / prioridade | Mudança proposta | Benefício esperado | Esforço / risco de qualidade |
|---|---|---|---|
| M1 / P0 | Medir captura → encode → fila → decode → detector → warp → features → reconstrução → entrega → apresentação. | Localiza atraso percebido e jitter. | M; usar identidade de frame e relógios compatíveis, não subtrair relógios sem sincronização. |
| M2 / P1 | Completar saída antecipada do `gameBridge` após produzir os dados necessários, evitando UI/debug do laboratório sem uso. | Menos trabalho por pose na iframe. | M; o render dela já está desligado. |
| M3 / P2 | Avaliar callback de novo frame de vídeo com fallback ao timer atual. | Menos polling e alinhamento com imagens novas. | M; iframe oculta pode ter comportamento diferente. O código já verifica `currentTime` para evitar duplicatas. |
| M4 / P1 | Medir encode JPEG, cópias e decodificação; comparar worker/OffscreenCanvas, resolução e qualidade de transporte. | Redução de atraso anterior à rede neural. | M; preservar detalhes de mãos/rosto e fechar recursos transferíveis. |
| M5 / P1 | Reusar buffers/tensores de forma fixa e constantes do warp, em especial saída TRT alocada por chamada. | Menos alocações e possíveis sincronizações. | M; respeitar concorrência, ownership e vida útil da saída. |
| M6 / P1 | Reduzir o vai-e-volta CUDA → CPU → DML → CPU → decode; comparar backend completo sob carga do jogo. | Potencial relevante quando cópias dominam. | A; não assumir compartilhamento zero-copy entre CUDA e DirectML. |
| M7 / P2 | Medir e restringir sincronizações globais; usar eventos/streams e locks com responsabilidades explícitas. | Evita esperar trabalho de GPU não relacionado. | A; não remover o `stream.synchronize()` TRT indiscriminadamente: o código explica que protege reutilização concorrente do contexto. |
| M8 / P2 | Detector adaptativo à estabilidade da caixa, com redetecção rápida em perda/extensão de braço. | Menos inferências YOLO quando o alvo é estável. | M; detector periódico e worker já existem; não cortar mãos em hooks. |
| M9 / P1 | Aperfeiçoar o rebalanceamento existente com teste conjunto render + NLF, histerese e cache com fingerprint robusto. | Escolhe o backend que melhora a experiência inteira. | M; evitar trocas repetidas e benchmark pesado durante um golpe. |
| M10 / P2 | Ajustar número de threads e afinidade/política de CPU conforme dispositivo. | Menos competição entre browser, detector e inferência. | M; testar latência e potência, não escolher “todas as threads” por padrão. |
| M11 / P2 | Candidato OpenVINO GPU para Intel, com descoberta e fallback; hoje o caminho OV compila em CPU. | Pode ampliar desempenho em iGPU compatível. | M/A; precisa de hardware real e comparação com DML. |
| M12 / P2 | Validar INT8, quantização seletiva e/ou gráficos de execução onde operadores e shapes permitirem. | Potencial alto em hardware específico. | A; erro de punho/cabeça e perda de socos são regressões mesmo com FPS maior. |
| M13 / P3 | Portar o pipeline NLF completo para browser/WebGPU ou outro runtime unificado. | Possível simplificação de instalação e cópias. | A; não basta converter o backbone: crop, detector, reconstrução, query de juntas e precisão também precisam funcionar. |

Baixar webcam de 960 para 640 não altera automaticamente os **256 × 256 de entrada do backbone**. Pode economizar captura/encode/warp e perder observabilidade das mãos; essa troca exige validação de reconhecimento. Aumentar a suavização também não acelera o modelo: geralmente acrescenta atraso.

DirectML exige configuração e controle de concorrência próprios; o projeto já serializa o despacho da sessão. Ajustes de threads devem ser medidos por dispositivo. [DirectML oficial](https://onnxruntime.ai/docs/execution-providers/DirectML-ExecutionProvider.html), [threads no ONNX Runtime](https://onnxruntime.ai/docs/performance/tune-performance/threading.html).

### 4.5 Interface, áudio, rede e sessões longas

| ID / prioridade | Mudança proposta | Benefício esperado | Esforço / risco |
|---|---|---|---|
| U1 / P1 | Guardar referências DOM e atualizar textos/classes/barras apenas quando mudarem; timer quando o segundo mudar. | Menos trabalho de estilo/layout e alocações. | B; vida/impacto continuam responsivos. |
| U2 / P1 | Separar leitura de geometria DOM e escrita de estilos nas legendas; cachear dimensões até mudar texto/viewport. | Evita layout forçado e repetição durante anúncios. | M; manter legenda fora do avatar em movimento. |
| U3 / P2 | Otimizar envelopes de legenda com fase ampla antes do refinamento skinned perto da câmera. | Menos transformação exata de vértices durante voz. | M; não substituir por uma caixa tão ampla que esconda todas as legendas. |
| U4 / P2 | Pré-calcular onset/normalização de som offline e carregar falas conforme prioridade. | Menos download/decodificação/pico no início do treino. | M; preservar início imediato dos sons de impacto. Buffers de áudio já são reutilizados. |
| U5 / P1 | Reduzir atividades de lobby/resultado/aba oculta; coordenar captura e pausa com multiplayer. | Menos uso térmico, CPU/GPU e bateria sem jogo ativo. | M; não interromper reparação de histórico, keepalive ou comunicação de pausa. |
| N1 / P2 | Medir tamanho real de pacotes e comparar float32/binário com JSON atual. | Menor banda, parse e lixo em rede. | M; benefício limitado se o gargalo principal estiver na malha ou inferência. |
| N2 / P2 | Reduzir metadados/journal repetidos com deltas e ressincronização confiável. | Menos tráfego sem perder resultado autoritativo. | M/A; preservar entrega após KO e recuperação de perdas. |
| N3 / P2 | Aperfeiçoar buffer remoto conforme jitter observado, com extrapolação curta e limitada. | Movimento remoto mais consistente. | M; extrapolação não pode inventar golpes/dano nem antecipar indefinidamente. |
| N4 / P1 | Testes de perda, jitter, reconexão, cache e troca de personagem durante sessões longas. | Menos engasgos/degradação e maior previsibilidade. | M; inclui crescimento de memória e limites de buffer já existentes. |

Servidores gratuitos de terceiros não são uma base garantida para infraestrutura permanente. A primeira economia em rede é enviar menos estado redundante e manter inferência local. O jogo já evita mandar vídeo da webcam para o adversário.

## 5. WebGPU: onde ajuda e onde não resolve

WebGPU é uma API, não uma substituta obrigatória do Three.js. É possível continuar no Three.js e usar `WebGPURenderer`. Isso preserva mais da estrutura atual do que migrar para outra engine.

Potenciais benefícios incluem menor overhead de submissão em certos cenários, recursos de computação GPU e caminhos modernos de renderização. Porém, **não remove automaticamente os 1,49 milhão de triângulos do Prism, o skinning CPU de contatos, o encode JPEG ou as cópias do NLF**. Com aproximadamente 70 draw calls nesta cena, a justificativa “muitos draw calls” precisa de evidência melhor.

O código atual tem obstáculos concretos:

1. Three.js r160: primeiro é necessário atualizar e validar uma versão fixada adequada ao novo renderer.
2. `onBeforeCompile` em `boxing.js`: recorte da cabeça em primeira pessoa, flash e hematomas.
3. `ShaderMaterial` em `boxing_fx.js` e `boxing_arena.js`: rastros/partículas, céu e cones de luz.
4. Inicialização, aquecimento, materiais, sombras, captura e diagnóstico precisam ser testados nos dois backends.

A documentação atual orienta portar customizações GLSL para materiais de nodes/TSL; o novo renderer tem fallback WebGL2 e ainda pode apresentar diferenças ou desempenho inferior em determinadas cenas. **Não é uma troca de uma linha.** [Guia oficial de migração](https://threejs.org/manual/pages/webgpurenderer).

Experimento recomendado: separar renderização do estado do combate; portar uma cena representativa com os dois avatares, sombra, recorte de primeira pessoa, hematomas e efeitos; comparar WebGL atual, WebGL atualizado e WebGPU na mesma máquina. Manter caminho de recuperação quando WebGPU não estiver disponível ou falhar.

Critérios propostos para adoção: redução repetível de pelo menos 15% no recurso efetivamente limitante **ou** melhoria relevante de p95/consumo; nenhuma regressão visual/latência de pose; inicialização e memória aceitáveis; funcionamento nos dispositivos-alvo. O limiar de 15% é um critério sugerido de decisão, não resultado obtido.

**WebGPU para inferência é outro projeto.** ONNX Runtime Web permite execução WebGPU, I/O binding e graph capture sob condições específicas. O ganho depende de operadores suportados, shapes e dados permanecerem no dispositivo; não garante que nosso NLF-S completo seja compatível. [ONNX Runtime WebGPU](https://onnxruntime.ai/docs/tutorials/web/ep-webgpu.html).

## 6. Vale trocar Three.js por outra biblioteca?

| Opção | Vantagem potencial neste jogo | Custo de migração | Parecer |
|---|---|---|---|
| Three.js atual otimizado | Reaproveita todo o retarget, contatos, shaders e testes. | Baixo/médio. | **Primeira escolha.** |
| Three.js atualizado + WebGPU | Evolui backend mantendo boa parte da arquitetura. | Médio/alto, principalmente shaders e regressões. | Melhor primeira experiência de mudança de renderer. |
| Babylon.js | Engine mais integrada; WebGPU e ferramentas de cena, com opções como snapshot rendering. | Alto: materiais, rig, efeitos, câmera, contatos e instrumentação. | Candidato se a integração de engine também for desejada; ganho de FPS precisa ser medido. |
| PlayCanvas Engine | Motor web com batching e ferramentas de otimização; pode ser usado standalone. | Alto, pelas mesmas integrações específicas. | Candidato para projeto maior de arquitetura/produção, não atalho comprovado para esta cena. |
| Godot | Ferramentas de produção e opção de build nativo. | Muito alto; reimplementar integração web e retarget. | Considerar se a estratégia virar jogo nativo. O export web estável documentado usa WebGL2/Compatibility, não é migração automática para WebGPU. |
| Renderer WebGPU próprio | Controle máximo da pipeline. | Muito alto e manutenção contínua. | Desproporcional para dois lutadores e esta equipe/projeto. |

Three.js e PlayCanvas Engine usam MIT; Babylon.js usa Apache-2.0. O uso das engines não exige comprar uma licença proprietária, mas serviços de editor/hospedagem e os próprios assets são itens separados. [Three.js](https://github.com/mrdoob/three.js/blob/dev/LICENSE), [PlayCanvas Engine](https://github.com/playcanvas/engine/blob/main/LICENSE), [Babylon.js](https://github.com/BabylonJS/Babylon.js/blob/master/license.md).

O snapshot rendering do Babylon reaproveita comandos em condições específicas, principalmente beneficiando CPU; alterações de meshes/estado podem exigir novo snapshot. Não elimina trabalho de GPU. [Documentação oficial](https://github.com/BabylonJS/Documentation/blob/master/content/setup/support/webGPU/webGPUOptimization/webGPUSnapshotRendering.md). PlayCanvas fornece batching, sujeito a compatibilidade de materiais e grupos; nossa torcida já usa uma solução equivalente de instanciamento. [Batching](https://developer.playcanvas.com/user-manual/graphics/advanced-rendering/batching/), [engine standalone](https://developer.playcanvas.com/user-manual/engine/standalone/). As limitações atuais de exportação do Godot estão na [documentação oficial](https://docs.godotengine.org/en/stable/tutorials/export/exporting_for_web.html).

## 7. Nocaute: comportamento implementado

O comportamento anterior continuava aplicando retarget, alinhamento das mãos e guarda enquanto girava o grupo inteiro até aproximadamente 85°. Resultado: o corpo tombava, mas preservava a postura de luta.

A implementação atual é um **ragdoll articulado de corpos rígidos** usando o `cannon-es` já servido pelo projeto. Ela cria 18 corpos simplificados, juntas limitadas, gravidade, amortecimento, piso, paredes do ringue, substeps fixos de 120 Hz e sleep quando o conjunto estabiliza. O esqueleto visível apenas apresenta o resultado desses corpos; o mocap deixa de dirigir a vítima durante o KO.

| Fase, em tempo da apresentação | Comportamento |
|---|---|
| Instante do KO | Captura as transformações visíveis e desliga o controle do mocap para a vítima. |
| Instante do impacto | Calcula a direção do último soco. Aplica um único impulso limitado na cabeça, no ponto do contato, e deixa pescoço, coluna e quadril receberem a transferência pelas juntas. Não injeta `velocity` em todas as partes. |
| 0–2 s | Gravidade, limites de junta, amortecimento e torque finito nos joelhos produzem o colapso. A velocidade angular e linear têm limites de segurança. |
| Estabilização | Após mais de 2 s e baixa velocidade articular por 0,6 s, os corpos dormem e a simulação deixa de consumir passos. |
| Reinício | Restaura o estado capturado, descarta a queda e retorna ao retarget normal. |

Os tempos usam o relógio visual do jogo: hit-stop e câmera lenta alteram sua duração em segundos reais. Os ossos mantêm comprimentos e hierarquia; não são separados uns dos outros. A solução não aplica impulso ao adversário nem muda regras de dano, força ou resultado. O impulso da cabeça varia de 0,50 a 0,83 N·s conforme a potência, com 18% desse valor aplicado no `spine2` para melhorar a transferência pelo tronco. O ponto de aplicação na cabeça é limitado para evitar uma rotação exagerada.

**Limites deliberados:** as formas físicas são caixas aproximadas, não a malha renderizada; não há interação física entre os dois lutadores durante a transição; e cordas, mãos e pés não têm colisão anatômica detalhada. Isso reduz custo e evita energia artificial causada por penetração inicial. A raiz fica limitada à área do ringue, mas a extensão de um corpo deitado ainda precisa ser revisada perto das cordas.

### Validação do nocaute

O teste `scripts/test_boxing_knockout.py` usa os três assets reais, diferentes direções, passos de apresentação de 30/60/144 Hz e os dois lados como vítima. Verifica transformações finitas, preservação de posições locais/comprimentos, limites de articulação, translação, elevação, estabilização e reinício. A pose de entrada continua sendo alterada após o KO para exercitar a tomada de controle.

O teste focado `scripts/test_boxing_ragdoll_push.py` verifica que o impulso nasce na cabeça, que a velocidade chega ao quadril pelas restrições, que a direção horizontal é preservada, que as âncoras permanecem estáveis e que o conjunto entra em sleep. Uma varredura independente de **todos os vértices na pose final** verifica o contato, em vez de testar somente as mesmas amostras do algoritmo. Ela não certifica toda pose intermediária nem todas as posições possíveis de webcam.

Resultados completos, números finais e screenshots históricos: `experiments/performance_audit_20261003/knockout-validation.json` e `ko-*.png`. A avaliação subjetiva em movimento com webcam continua necessária para ajustar sensação e rigidez ao gosto do jogo.

**Resultado da validação física atual:** o teste do impulso passou. O impulso foi aplicado somente à cabeça, o quadril recebeu velocidade pelas restrições em poucos substeps, o erro máximo de âncora ficou abaixo de 0,001 m e o conjunto entrou em sleep após a queda.

**Verificações adicionais:** sintaxe JavaScript e `test_boxing_core.mjs` passaram. O teste geral `test_boxing_combat_e2e.py` **não passou**: a fixture `chin_fast_open` registrou golpe `clean`, sem tontura, enquanto espera `chin` com tontura. Bloqueio, diferenciação de dano, golpe no corpo e abertura do resultado ocorreram sem erros JavaScript. A mesma divergência, com os mesmos números, foi reproduzida em controle que desativa a nova extensão de KO e restaura o reset anterior, por rota de teste no navegador. O script `check_boxing_combat_control.py` preserva essa reprodução. Portanto, a suíte geral não está totalmente verde; essa pendência de golpe/fixture não foi alterada para fazer o teste passar.

## 8. Sequência de execução recomendada

| Etapa | Escopo | Ordem de grandeza de esforço de engenharia* | Saída que permite decidir |
|---|---|---|---|
| 1 | Medição ponta a ponta + replay controlado, usando instrumentos existentes. | 1–3 dias | Separação de CPU/GPU/inferência/captura; p50/p95 e idade da pose. |
| 2 | GLBs otimizados, compressão/texturas e metadados offline. | 3–7 dias | A/B visual, memória, carregamento e GPU; preservar originais. |
| 3 | Caches/matrizes/contatos, DOM e atualização de ator invisível. | 2–5 dias | Mesmas poses/colisões, menor CPU/picos; nenhuma mudança no dano. |
| 4 | Qualidade automática e melhoria de cópias/backend sob carga conjunta. | 3–8 dias | Fluidez e menor atraso sustentados em hardware alvo. |
| 5 | Protótipo Three.js WebGPU com paridade visual. | 1–3 semanas | Comparação justa e decisão de manter ou descartar o protótipo. |
| 6 | Outra engine, caso as etapas anteriores deixem uma limitação demonstrável. | Várias semanas; estimativa detalhada só após protótipo. | Ganho comprovado que compense manutenção/migração. |

*Estimativas aproximadas para planejamento, não orçamento ou prazo garantido; incluem implementação e parte da validação, e variam com familiaridade e acesso aos dispositivos. Não devem ser somadas como compromisso de entrega.

Minha ordem prática: **G1–G4/G10, C1–C6/C8–C9, U1–U2, M1/M4–M6/M9, R1–R3, depois WebGPU**. A medição P0 acompanha todas as etapas. Se o perfil mostrar captura/inferência dominando a latência, antecipar M4–M9 em relação ao refinamento gráfico.

## 9. Como aceitar ganho real sem piorar o jogo

1. **Cenários fixos:** lobby, webcam em guarda, jab/cross/hook, braços passando diante do rosto, primeira/terceira pessoa, KO, resultado e online com perda/jitter. Gravação diagnóstica deve ser um cenário separado porque também consome recursos.
2. **Hardware:** RTX 3060 como referência já medida; pelo menos uma iGPU e uma máquina mais fraca antes de declarar benefício amplo. Celular só entra nas promessas após teste próprio.
3. **Experimento:** aquecimento, execuções alternadas A/B e B/A, mesmas poses, câmera, resolução, perfil e versão; sessões de 60–120 s e teste térmico mais longo, por exemplo 15 minutos.
4. **Métricas:** frame time p50/p95/p99, quadros acima de 33/50 ms, tempo real de GPU quando disponível, CPU por fase, idade da pose p50/p95, poses únicas/s, perdas, pico/estabilidade de memória, bytes transferidos e tempo até poder jogar.
5. **Orçamento:** 60 FPS corresponde a 16,67 ms entre apresentações; 30 FPS, a 33,33 ms. CPU e GPU podem se sobrepor, então não somar indiscriminadamente duração de fases concorrentes. Melhorar folga e bateria é válido mesmo com FPS travado em 60.
6. **Fidelidade:** comparar trajetória de pulsos/cabeça, jitter parado, atraso no movimento, reconhecimento/força dos golpes e contato luva–rosto. Nenhuma alteração na contagem de golpes por causa de mudança gráfica.
7. **Critério de retenção:** aceitar ganho acima da variabilidade das repetições, acompanhado de ausência de regressão relevante. Um único pico favorável ou screenshot bonito não basta. Guardar dados brutos e permitir rollback por opção/asset.

Não recomendo como primeiros passos: diminuir a taxa de combate; adicionar mais suavização para esconder lentidão; trocar NLF por outro modelo sem teste de fidelidade; desativar contatos importantes; remover sombras/feedback indiscriminadamente; renderizar tudo em WebGPU próprio; ou contratar GPU remota para compensar desperdício local.

## 10. Artefatos e reprodução

- `scripts/audit_boxing_performance.py`: seis medições dos perfis atuais e perfil CPU, sem webcam.
- `experiments/performance_audit_20261003/baseline.json`: ambiente, inventário em runtime, contadores e tempos.
- `experiments/performance_audit_20261003/baseline.cpuprofile`: perfil de amostragem para abrir no DevTools.
- `experiments/performance_audit_20261003/assets.json`: inspeção estrutural dos GLBs e texturas.
- `experiments/performance_audit_20261003/nlf-status.json`: status/calibração observados, sem tratar como benchmark novo.
- `viewer/boxing_knockout.js`: preparo de contatos, relaxamento, chão e estabilização da queda.
- `viewer/boxing.js`: integração da tomada de controle no KO e restauração no reinício.
- `scripts/test_boxing_knockout.py`: regressões específicas do KO.

Com o servidor do jogo já ativo em `http://127.0.0.1:8780`, executar na pasta `pose_corrector_lab`:

```powershell
python scripts/audit_boxing_performance.py
python scripts/test_boxing_knockout.py
node scripts/test_boxing_core.mjs
```

O benchmark usa uma página de teste isolada, não conecta uma sala pública e não precisa ativar a webcam. Não representa a sessão completa de captura. Os arquivos de saída são regenerados ao executar os scripts.
