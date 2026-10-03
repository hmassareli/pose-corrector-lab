# Benchmark de orientação da palma

Seis fotografias originais 3840×2160, importadas dos 18 anexos enviados em
30/09/2026. Cada fotografia foi enviada três vezes com pixels RGB idênticos.
`labels.json` preserva os hashes, os números dos anexos e seus agrupamentos.
As cópias canônicas conservam os bytes JPEG originais.

| Foto | Mão avaliada | Direção da palma | Estado |
|---|---|---|---|
| 01 | Ambas | Cima | Aberta |
| 02 | Ambas | Lado interno, uma para a outra | Aberta |
| 03 | Direita | Cima | Fechada, polegar estendido |
| 04 | Ambas | Baixo | Aberta |
| 05 | Direita | Lado interno | Fechada |
| 06 | Direita | Baixo | Fechada |

Direita/esquerda são lados **anatômicos da pessoa**. A mão direita está à
esquerda da foto original, que não está espelhada. O live usa espelhamento
e troca L/R por padrão; o teste deve considerar essa transformação.
Direção significa a normal da superfície da palma, não a direção dos dedos.

Os rótulos foram atribuídos por inspeção visual antes de rodar o modelo.
Nos punhos fechados, a orientação foi inferida pelo polegar e pelos dedos;
por isso a confiança é moderada. O braço esquerdo relaxado das fotos 03,
05 e 06 não é um alvo avaliado. Não há ângulo 3D medido, câmera calibrada
ou sequência de movimento. Não usar duplicatas como exemplos independentes.

O NLF e o solver não recebem estes rótulos. Para reproduzir a câmera simulada
de 960×540, mantendo cada foto por seis segundos no caminho real `/live`:

```powershell
python scripts/serve_lab.py --port 8780 --backend auto
python experiments/review_20260930/live_visual/test_live_visual.py --avatar fighter-web --wait-ws --limit 6 --warmup-seconds 60 --images-dir src/benchmark_images/palm_orientation --output-dir experiments/review_20260930/palm_live/fighter-web_settled
```

Os seis JPEGs residem em um subdiretório próprio para preservar o conjunto
corporal anterior. O teste aceita `--images-dir` para selecionar este conjunto.
