# Validação visual do caminho live — 30/09/2026

Agora houve inferência nova, renderização do mesh e inspeção das imagens. Os renders antigos em `src/benchmark_images/avatar_dev` não foram usados como resultado desta validação.

## Procedimento

As 13 fotos de benchmark foram reduzidas de 3840×2160 para uma webcam simulada de 960×540, 30 FPS. Cada foto permaneceu por 6 segundos. Chromium/Playwright abriu a página original `/live`, selecionou NLF-S e Avatar 3D, capturou JPEG e enviou os frames ao servidor pelo WebSocket binário. O servidor executou NLF-S x55/TensorRT na RTX 3060. O cliente aplicou espelhamento selfie, plantFeet, o solver compartilhado e seus filtros nas cadências reais de chegada.

Foram adicionados somente hooks de observação no HTML servido ao navegador e uma câmera frontal para revisão. O servidor de diagnóstico também registrou chamadas do detector e stacks das threads. Não houve alteração do solver, de seus parâmetros, dos pesos ou do algoritmo de inferência. Configuração de mãos: padrões de uma sessão nova, selfie ligado, palm ligada, sem fitPalm/fit/teacher/surface1024.

O Chromium de teste precisou permitir o WebSocket local: inicialmente sua proteção de rede local bloqueava a conexão. Essa falha do ambiente de automação foi identificada e removida antes das rodadas válidas. A webcam física não foi ativada.

## Resultado visual e interpretação

1. **A rodada aquecida produz poses reconhecíveis.** Guarda, inclinação e braço elevado aparecem nos dois personagens. Existem diferenças de posição, postura e aparência das mãos em relação à foto, mas isso não significa que toda diferença venha do retarget: estimativa monocular, proporções do personagem e perspectiva também participam.
2. **A direção dos braços é transferida com boa fidelidade aos pontos recebidos.** Na rodada Fighter Web, nas janelas de foto parada de 2 a 5,8 segundos, o maior desvio entre ombro→cotovelo/cotovelo→punho do NLF e os segmentos correspondentes do rig foi 0,376°. É uma medida de transferência de direção, não uma medida de precisão anatômica contra a pessoa da foto. Não verifica roll da palma, posição absoluta das mãos ou contatos.
3. **O fechamento dos dedos não é retargetado nesse caminho.** O solver orienta antebraço e osso Hand; os pontos dos dedos ajudam a construir a orientação da palma. Ele não aplica as articulações dos dedos para reconstruir o punho fechado. Isso é visível principalmente no Fighter Web e limita a fidelidade para boxe, independentemente de acertar a pronação.
4. **Não foi reproduzido giro contínuo das mãos nas fotos estáticas aquecidas.** No Fighter Web, o maior salto de orientação mundial de Hand entre resultados consecutivos das janelas paradas foi 0,133°. Isso não invalida os casos de descontinuidade reproduzidos nos probes anteriores: imagens constantes não atravessam a fronteira de roll de 89°→91° nem simulam movimento contínuo acima da cabeça.
5. **A inicialização/recorte merece uma investigação própria.** Na primeira rodada válida (`boxeador`), várias poses ficaram invertidas ou abaixo do chão. O ponto de entrada já estava errado. O recorte ficou aproximadamente `[192,13,155,275]` por boa parte da sequência de 960×540. Esse retângulo veio do estado anterior da rota HTTP, que reduz a imagem para no máximo 512 px, enquanto o WebSocket admite 960 px e reutiliza o mesmo tracker. Não há tratamento de mudança de resolução no StickyBBox. A thread YOLO demorou para produzir novas detecções; o servidor de rastreamento registrou a primeira detecção ainda dentro do warmup de convoluções. A rodada com conexão/detector aquecidos e coordenadas coerentes eliminou as inversões extremas. Isso evidencia um problema de robustez do pipeline, sem provar que essa duração se repetirá em toda inicialização.

## Cadência e latência observadas

| Rodada | Resultados aplicados | Atualizações/s da rodada | Servidor p50/p95 | Envio→resposta p50/p95 |
|---|---:|---:|---:|---:|
| Boxeador, estado inicial problemático | 1452 | 18,99 | 16,59 / 24,24 ms | 22,80 / 32,20 ms |
| Boxeador, conexão aquecida | 1478 | 19,32 | 15,79 / 24,03 ms | 22,10 / 31,82 ms |
| Fighter Web, conexão e detector aquecidos | 2284 | 29,83 | 14,53 / 22,63 ms | 21,40 / 34,10 ms |

As duas rodadas Boxeador ocorreram durante parte da investigação com outros processos de modelo carregados; eles foram encerrados antes da rodada Fighter Web. Portanto, essas taxas não são uma comparação controlada de desempenho entre os personagens. As capturas de tela, o navegador headless e os hooks também têm custo. As latências do servidor não são latência câmera→tela completa. Houve outliers, registrados nos JSONs.

## Até onde a conclusão sobre live vs. offline vai

Os probes anteriores mostraram maior instabilidade do caminho live em uma sequência existente, além de falhas geométricas reproduzíveis. Este teste visual confirma limitações do live e uma falha de inicialização/recorte, mas **não é uma comparação visual A/B com o offline** e não demonstra que o live seja pior em todas as poses. Não houve captura nova de uma pessoa em movimento: as transições entre fotos são cortes abruptos. Nenhuma foto mostra duas mãos completamente acima da cabeça. Esse caso específico e a continuidade da pronação continuam exigindo vídeo de movimento contínuo.

## Artefatos

- `galeria.html`: 13 fotos e os dois avatares, mais o caso de inicialização.
- `boxeador_warm/*_compare.png` e `fighter-web_warm/*_compare.png`: comparações individuais, foto espelhada como na interface.
- `*_live.png`: screenshot da página com o vídeo de entrada realmente usado, avatar e HUD.
- `summary.json`: snapshot das capturas, configuração e erros do navegador.
- `frames.json`: todos os resultados novos de inferência e posições/quaternions observados no rig.
- `metrics.json`: métricas por janela estática; excluem o início de cada corte de foto.
- `trace_stderr.log`: stack do detector durante inicialização.
- `test_live_visual.py`, `analyze_live.py` e `trace_server.py`: reprodução e diagnóstico.

SHA-256 do solver usado: `1631419293ff38210727f1d2beb1844b05a66d32aa7a3b58087cfc5c677d1f84`, igual ao da análise anterior. Os arquivos originais do algoritmo permaneceram intactos nesta validação.
