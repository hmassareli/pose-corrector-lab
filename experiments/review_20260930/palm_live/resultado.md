# Teste das fotografias de orientação da palma — 30/09/2026

As 18 imagens anexadas contêm seis fotografias únicas, cada uma repetida três
vezes com pixels RGB idênticos. Foram importadas sem recodificação para
`src/benchmark_images/palm_orientation`, com nomes descritivos, hashes e rótulos
visuais em `labels.json`. Os rótulos precedem a inferência e não são fornecidos
ao modelo ou ao retargeting. Direita/esquerda são lados anatômicos da pessoa;
lado interno significa palmas voltadas ao plano mediano do corpo.

## Resultado observado no live

Foi usado o caminho real `/live`: câmera simulada 960×540, JPEG, WebSocket,
NLF-S SMPL-X55, solver existente e avatar Fighter Web. Cada fotografia dura seis
segundos. A execução principal é `fighter-web_settled`, com 60 segundos de
aquecimento **na mesma conexão** antes do ciclo capturado (72–108 segundos).
São 2.851 respostas totais, incluindo aquecimento; a medição de cada foto
descarta seus primeiros dois segundos. Não houve erro de JavaScript registrado.

| Foto | Mão avaliada | Rótulo visual | NLF bruto, classe majoritária | Avatar, classe majoritária |
|---|---|---|---|---|
| 01 | Direita | Cima | Lado interno | Lado interno |
| 01 | Esquerda | Cima | Lado interno | Lado interno |
| 02 | Direita | Lado interno | Lado interno | Lado interno |
| 02 | Esquerda | Lado interno | Lado interno | Lado interno |
| 03 | Direita | Cima | Lado interno | Lado interno |
| 04 | Direita | Baixo | Baixo | Baixo |
| 04 | Esquerda | Baixo | Baixo | Baixo |
| 05 | Direita | Lado interno | Lado interno | Lado interno |
| 06 | Direita | Baixo | Baixo | Baixo |

As classes coincidiram em seis dos nove casos de mão avaliados, tanto no NLF
bruto quanto no avatar. Os três casos de palma para cima falharam já na entrada
do solver. Isso evidencia uma limitação do sinal entregue pelo pipeline live
nessas fotos. Corrigir apenas o retargeting não recuperaria a palma para cima
nesses casos, porque os pontos de entrada já indicam outra orientação.
Não demonstra que o modelo nunca reconhece supinação em outras imagens.

O avatar também mantém seus dedos em repouso: acertar a classe da normal da
palma não significa reproduzir mão aberta, punho fechado ou polegar estendido.
As seis imagens renderizadas foram inspecionadas visualmente e estão na galeria.

## Como foi medida a orientação

No NLF, a normal é o produto vetorial das posições previstas de punho,
index1 e pinky1, com sinal anatômico por lado e conversão de coordenadas.
No avatar, foi usada a mesma construção a partir das **posições reais dos
ossos dos dedos em espaço mundo**, sem usar `restAcrossInRoot` nem os eixos-alvo
do solver. A troca L/R e o espelhamento do modo selfie foram considerados.
O sinal é fixo pela anatomia; não foi ajustado usando os rótulos deste teste.

A classe é a direção cardinal de maior alinhamento: cima, baixo, lado interno,
lado externo, câmera ou longe da câmera. São descartados vetores quase colineares
com seno do ângulo entre punho→index1 e punho→pinky1 menor que 0,05.
Os resultados detalhados, normais, contagens e caixas estão em
`fighter-web_settled/palm_metrics.json`; os hashes do HTML e do solver e a
proveniência das entradas estão em `summary.json`.

## Cuidados de interpretação

Rótulos aproximados por inspeção visual; não há orientação 3D instrumental
ou câmera calibrada. O rótulo dos punhos fechados tem confiança moderada porque
a palma está escondida; o das mãos abertas tem confiança alta. Os frames
repetidos não constituem novas amostras independentes: são seis fotos e nove
casos de mão. Este resultado não é uma estimativa de acurácia geral nem de
erro angular em graus. Cortes entre fotos não testam continuidade de movimento.

Dois replays iniciais (`fighter-web` e `fighter-web_warm`) foram preservados
como diagnóstico, mas não devem fundamentar a conclusão: usaram enquadramento
inteiro durante a partida ou uma caixa antiga por grande parte do replay.
Somente aquecer o modelo ou abrir uma nova conexão não garantiu YOLO aquecido.
No replay principal, as caixas medianas mudaram por foto e abrangeram as mãos
avaliadas. O backend automático iniciou com TensorRT e seus logs registram
troca/rechecagem com DirectML ao longo da sessão; os dados brutos foram salvos.

Nenhum código de produção do modelo, filtro ou solver foi alterado neste teste.
Foram acrescentados dados rotulados e opções/instrumentação ao teste diagnóstico.

## Reprodução

```powershell
python scripts/serve_lab.py --port 8780 --backend auto
python experiments/review_20260930/live_visual/test_live_visual.py --avatar fighter-web --wait-ws --limit 6 --warmup-seconds 60 --images-dir src/benchmark_images/palm_orientation --output-dir experiments/review_20260930/palm_live/fighter-web_settled
python experiments/review_20260930/live_visual/analyze_palm_benchmark.py
python experiments/review_20260930/live_visual/build_palm_gallery.py
```

O Y4M intermediário pode ser regenerado; foi removido após os testes para
economizar espaço. Fotografias originais, capturas, respostas e métricas
permanecem salvas.
