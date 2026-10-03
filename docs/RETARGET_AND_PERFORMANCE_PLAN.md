# Plano de retarget e desempenho — 2 de outubro de 2026

## Objetivo e estado

Plano solicitado por Henrique após a auditoria do avatar. R1–R4 foram implementadas em 2 de outubro de 2026; R5 recebeu probes, replay NLF e testes de integração nos assets reais. A confirmação subjetiva em uma nova sessão humana de webcam continua necessária. Implementação e evidências: [correções de poses](AVATAR_POSE_FIXES.md). Os experimentos P1–P5 de desempenho continuam como propostas: esta entrega não confirma ganho de 15% na inferência.

Prioridade: reconhecimento responsivo e movimento fiel. Desempenho gráfico vem depois, mas ambos devem ser medidos juntos porque disputam recursos do computador. Preservar NLF-S, SMPL-X55, os três avatares, luvas nativas, controle exclusivamente por webcam e o mesmo slider de suavização 0–100, com bypass em 0. Pés fora do enquadramento continuam permitidos.

## 1. Corrigir informação desperdiçada no retarget

Referência: [auditoria completa](AVATAR_RETARGET_VERDICT.md). A nota visual anterior do jogo não mede fidelidade do movimento.

### R1 — Orientação facial completa

- Substituir a dependência quase exclusiva de `head−neck` e da linha entre os olhos por uma base facial completa e calibrada: transversal dos olhos, ponto médio ocular e referências de crânio/mandíbula.
- Separar orientação do rosto, inclinação cervical e orientação do tronco. Corrigir os eixos de repouso de cada rig antes de transferir a rotação.
- Aproveitar pitch e roll independentes que hoje se perdem; não tentar recuperar informação descartada aumentando a suavização.
- Validar que esses vetores são observáveis na saída NLF real, especialmente em perfil e oclusão. O sucesso em probes geométricos não certifica a precisão do reconhecimento facial.
- Aceite: probes isolados de yaw ±45°, pitch ±30° e roll ±25° respondem no eixo e sentido corretos, nos três modelos, sem contaminação relevante entre eixos. Medir ganho e erro; amplitude reduzida deve ser uma escolha explícita.

### R2 — Perda e recuperação dos olhos

- Eliminar o giro neutro indevido de ~33–34° no fallback atual.
- Manter brevemente a última orientação facial confiável relativa ao tronco; durante a perda, acompanhar o corpo e reduzir gradualmente o componente facial desconhecido.
- Recuperar continuamente quando a observação volta, sem reset para repouso e sem congelamento prolongado.
- Usar consistência geométrica e temporal; distância ocular fixa não garante qualidade dos pontos inferidos.
- Aceite: remover/colapsar olhos em uma pose neutra não cria giro; perder olhos durante movimento não congela o corpo; recuperação não produz salto desproporcional.

### R3 — Uma orientação final e um filtro por atualização

- Consolidar as duas escritas/filtragens da cabeça no fallback sem olhos em uma orientação final. Hoje a segunda filtragem recebe o mesmo timestamp e reinicializa seu estado.
- Definir explicitamente o relógio de amostra e o de apresentação. Tratar amostras repetidas, intervalos variáveis e retomada após perda sem resets indevidos.
- Dar cabeça/pescoço parâmetros responsivos próprios, mantendo o slider existente como controle da intensidade. Comparar atraso e jitter com os parâmetros atuais; não remover todo o filtro por princípio.
- Aceite: em slider 0 não há filtro; em 50/100 movimentos rápidos passam com resposta medida e postura parada permanece estável.

### R4 — Pescoço relativo à cadeia final

- Derivar a continuação cervical do tronco já resolvido, em vez de misturar a coluna bruta com um tronco geometricamente suavizado.
- Distribuir rotação entre pescoço e cabeça em espaço relativo, com limites articulares e sem somar erroneamente orientações globais.
- Reavaliar os ganhos fixos atuais (pescoço 0,75; cabeça 0,9) e a mistura cervical 50/50. Atenuação de amplitude não é atraso temporal.
- Aceite: preservar orientação final do rosto, evitar dobra concentrada no pescoço e impedir torções implausíveis em entradas adversas.

### R5 — Validação antes de expandir

Replays e probes dos três avatares, seguidos de webcam humana: olhar lateral, assentir, inclinar, girar tronco mantendo rosto, guarda cobrindo o rosto, perfil, perda e recuperação. Registrar orientação completa, continuidade e latência, não apenas direção de segmentos. Depois revisar confiança da palma, braço reto e transição entre pés observados e inferidos.

## 2. Desempenho: o que já existe

Não contar como ganho novo recursos já implementados:

- NLF-S rápido, SMPL-X55, uma augmentação e sem fit iterativo de malha no caminho normal.
- Backbone exportado e opções TensorRT FP16, DirectML, OpenVINO e ONNX CPU.
- Seleção de backend por calibração, cache, warmup e alternativas de recuperação.
- Detector YOLOv8n a 320 px, detecção periódica e thread separada.
- Worker assíncrono, filas limitadas, descarte de frames antigos e até dois pedidos em voo no browser.
- Renderização do Live já suspensa no modo `gameBridge`; não alegar economia removendo um segundo render que já não ocorre.
- Recorte de entrada da rede fixo em 256×256: baixar a webcam de 960 para 640 px economiza captura/encode/transferência/warp, mas não reduz automaticamente o backbone e pode piorar mãos/rosto.

### Evidência disponível, sem misturar benchmarks

- Cache histórico da RTX 3060: pose sintética completa de warp/features/decode com p50 TRT 9,70 ms, DML 8,63 ms, OpenVINO CPU 30,03 ms e ONNX CPU 36,84 ms (`experiments/autoresearch/backend_choice.json`). Não são FPS do jogo nem medidas em notebooks fracos.
- Consulta do serviço ativo durante esta revisão: `device=cuda`, `backend=dml`, `nlf_query=smplx55`, baseline registrado p50 12,41 ms / p95 14,00 ms. É a baseline do serviço, não um benchmark novo nem latência da webcam até a tela.
- Documentos antigos que dizem que TensorRT não foi instalado ou que usam apenas 24 juntas estão históricos; não descrevem todo o caminho atual.

## 3. Meta de 15% e método de medição

Definir ganho como capacidade sustentada de processar poses novas por segundo: `fps_novo / fps_base ≥ 1,15` em carga sem limite artificial. O tempo por frame correspondente é `ms_novo ≤ ms_base / 1,15` (~13% menos tempo); não confundir com redução de 15% no tempo.

Medir também jogo + câmera reais: FPS de poses únicas, p50/p95 da idade da pose exibida, intervalos entre poses, drops, render frame time, uso de CPU/GPU e pico de VRAM. Uma câmera limitada a 30 FPS não produzirá 34,5 imagens novas por segundo; nesse caso procurar menor latência e mais folga, ou testar 60 FPS somente se a webcam suportar.

Benchmark por etapas: aquisição, desenho/encode JPEG, espera/transporte, decode, detector, warp/H2D, backbone, decode/reconstrução, D2H/serialização, bridge, retarget e render. Timestamp atual na bridge representa entrega, não captura: acrescentar identidade e relógios corretos para medir idade, mantendo domínios de relógio separados.

Executar baseline e candidato no mesmo vídeo, hardware, resoluções e parâmetros, após warmup, em repetições alternadas. Registrar ambiente e temperaturas/carga para não confundir oscilação com ganho. Guardrails de qualidade devem abranger cabeça, pulsos, cotovelos, oclusões e detecção de golpes; definir tolerâncias antes dos experimentos. Sem GPU fraca disponível, só afirmar o ganho no hardware realmente medido.

## 4. Experimentos de engenharia em ordem

### P1 — Captura e bridge mais enxutas

- No `gameBridge`, retornar após publicar a pose ao jogo, evitando atualizar esqueleto/debug/overlays e eventualmente um avatar do laboratório carregado por preferências salvas. Não interromper transformações necessárias à mensagem.
- Reduzir atualizações de texto/HUD invisíveis, mantendo erro e diagnóstico acessíveis.
- Avaliar captura sincronizada com frame real (`requestVideoFrameCallback`, se disponível/ativo na iframe) com fallback para o timer: o código atual já verifica `currentTime` para evitar duplicação.
- Medir encode JPEG/cópias; testar encoder em worker/OffscreenCanvas quando houver suporte e benefício real. Isso melhora concorrência, mas não elimina o custo do encode.
- Testar 960/640 px e qualidade JPEG controlada, aprovando apenas se mãos/rosto e golpes não regredirem. Não baixar a resolução interna do NLF como primeira intervenção.

### P2 — Cópias, buffers e sincronização

- Reutilizar tensores constantes do warp e buffers de formas estáveis. Testar upload com memória pinned e transferência assíncrona no caminho CUDA, se o perfil apontar custo relevante.
- TensorRT atualmente aloca o tensor de saída por chamada: testar buffers persistentes respeitando concorrência e vida útil dos resultados.
- DirectML com device CUDA faz warp em CUDA, traz crop para CPU, envia à GPU via runtime e devolve features à CPU para decode. Medir esse vai-e-volta antes de decidir entre binding de device ou um caminho CPU/GPU mais coerente. APIs e suporte real do provider devem ser verificados; não presumir zero-copy interoperável.
- Revisar `torch.cuda.synchronize()` global após inferência: a saída já é copiada para CPU, e a sincronização global pode esperar trabalho de outra thread, como detector. Comparar com sincronização estritamente necessária; preservar todos os eventos que evitam races.
- Avaliar CUDA Graphs só se houver gargalo de lançamento de kernels. Não prometem benefício quando o limite é trabalho pesado de GPU; manter caminhos independentes para GPUs não NVIDIA.

### P3 — Detector adaptativo e escolha de backend

- Detector já roda periodicamente. Testar periodicidade guiada por estabilidade/movimento do recorte, com redetecção imediata ao perder alvo. Executar menos detecções não pode cortar mãos em socos rápidos.
- Comparar backend com o jogo aberto e sob carga sustentada. A seleção atual usa pose sintética; o vencedor isolado pode perder quando disputa GPU com WebGL.
- Medir empate e histerese antes de alterar preferência TRT/DML; uma diferença pequena no cache não prova o vencedor real.
- Fortalecer fingerprint do cache para incluir CPU/iGPU e dispositivo/provider realmente selecionado; a chave atual usa contagem de CPUs e nome CUDA, que não distinguem todos os PCs sem NVIDIA.

### P4 — PCs com pouca ou nenhuma GPU dedicada

- OpenVINO atual compila explicitamente em `CPU`. Implementar/testar candidato `GPU` para iGPU Intel compatível, com enumeração do dispositivo e fallback; não assumir que `ov` já usa iGPU.
- Validar DirectML em AMD/Intel/NVIDIA compatíveis, observando eventuais operadores que caem para CPU e configuração específica de sessão.
- CPU: medir limites de threads, evitar competição excessiva entre runtime, detector e browser; testar precisão apropriada ao hardware. No warp CPU, revisar a conversão para fp16 antes de voltar a fp32, preservando equivalência geométrica.
- INT8 já tem export/experimentos no repositório, mas não é um backend integrado no seletor atual. Avaliar resultados existentes e calibrar com cenas reais antes de integrar. Velocidade e qualidade dependem dos operadores/hardware; não prometer ganho gratuito.
- Distribuir o serviço local e os pesos de forma simples. Melhorar o backend não transforma automaticamente o NLF em um modelo que roda em qualquer browser.

### P5 — Mudanças maiores apenas se necessário

Se não houver folga suficiente, investigar modelo destilado, pruning ou menor resolução interna. Essas opções exigem treino/export e validação de qualidade; não são ganhos gratuitos. Reconhecimento remoto exige servidor apropriado e medição da latência de upload; não presumir que o VPS Contabo tenha GPU nem enviar webcam como parte da rede normal do duelo.

## 5. Jogo — prioridade secundária, mas recurso compartilhado

Criar perfil econômico adaptativo: reduzir pixel ratio/resolução interna, sombra principal de 2048 para 1024 ou alternativa visual, custo dos contornos de meshes skinned e quantidade de partículas/torcida. Manter avatares legíveis, iluminação suave e feedback de impacto. No dispositivo em que pixel ratio chega a 1,7, passar para 1 reduz pixels para ~35% do anterior; isso não significa a mesma redução no tempo total de render.

Medir draw calls, triângulos e custo de materiais; agrupar/instanciar torcida e objetos repetidos quando aplicável. Preservar simulação de combate separada da taxa de render e não confundir render a 60 FPS com captura a 60 FPS. Avaliar novamente inferência com cada perfil gráfico: aliviar WebGL pode dar mais folga ao reconhecimento na mesma GPU.

## Fontes técnicas e arquivos

- `scripts/nlf_engine.py`, `scripts/serve_lab.py`, `scripts/nlf_bbox_track.py`, `viewer/live.html`, `viewer/boxing.js`, `viewer/boxing_arena.js`.
- [TensorRT: benchmarking e CUDA Graphs](https://docs.nvidia.com/deeplearning/tensorrt/latest/performance/benchmarking.html).
- [ONNX Runtime: DirectML e configuração de sessão](https://onnxruntime.ai/docs/execution-providers/DirectML-ExecutionProvider.html).
- [ONNX Runtime: threads](https://onnxruntime.ai/docs/performance/tune-performance/threading.html).
- [OpenVINO: GPU Intel integrada/dedicada](https://docs.openvino.ai/2024/openvino-workflow/running-inference/inference-devices-and-modes/gpu-device.html).

## Entrega e aceite

1. Completar e validar R1–R4 antes de atribuir rigidez facial ao modelo ou à taxa de captura.
2. Medir baseline atual ponta a ponta e selecionar o gargalo real.
3. Experimentar P1–P4 individualmente, registrar ganho e manter somente candidatos aprovados em velocidade, p95 e qualidade.
4. Considerar 15% alcançado apenas com comparação sustentada no mesmo hardware; publicar resultados por classe de dispositivo realmente testada.
5. Revisar o perfil gráfico com capturas e teste humano; uma máquina pode usar reconhecimento e render com frequências diferentes sem exigir teclado ou corpo inteiro visível.
