# Correções do adaptador pose → avatar — 30/09/2026

Foram corrigidos os três problemas autorizados em
`viewer/mikapo_mixamo_solver.js`. O arquivo anterior à intervenção foi
preservado em `solver_before.js`; as modificações anteriores do usuário
permanecem no solver. O modelo NLF, o enquadramento e o processamento temporal
dos pontos não foram alterados.

## Mudanças

1. Removida a inversão do eixo da palma ao cruzar 90°. O sinal de index/pinky
   é anatômico e precisa ser preservado. A interpolação das mãos parte da
   orientação anterior para também evitar uma nova descontinuidade em ±180°.
2. Twist e roll witness usam ângulo orientado com `atan2` e rotação sobre o
   eixo longitudinal explícito. O alinhamento de vetores antiparalelos não
   escolhe mais um eixo arbitrário que desvie a direção primária do membro.
3. Pontos e quaternions não finitos são rejeitados antes de alimentar filtros.
   Segmentos degenerados e observações ausentes conservam a última rotação
   local válida. A restauração percorre a hierarquia, preservando os alvos
   mundo dos filhos que receberam observações válidas. Referências corporais
   inválidas rejeitam o frame antes de mudar pose, posição ou estado.
   Ausência do eixo lateral da palma conserva o roll anterior enquanto a
   direção longitudinal pode continuar sendo atualizada. Auxiliares parciais
   não exigem coluna ou collar que estejam ausentes.

Os modos explícitos de pé em repouso e palma desabilitada continuam colocando
esses ossos no repouso. A retenção não congela o avatar inteiro: um osso sem
observação acompanha seu pai com a rotação local conservada.

## Regressões reproduzíveis

`regression.mjs` executa os dois solvers com Three.js 0.160.0 real e o esqueleto
real do GLB do boxeador, reconstruído de seus nós e transformações. As direções
são medidas pela posição mundo de osso e filho; não pelo eixo-alvo do solver.

| Caso | Antes | Depois |
|---|---:|---:|
| Entrada 89° → 91°, saída sem filtro | 178° | 2° |
| Mesmo caso com filtro | 135,89° | 0,50° |
| Mesmo caso nos dois antebraços e mãos do GLB | ~178° | ~2° |
| Desvio do eixo ao aplicar twist de 180°, GLB | 28,96°–76,57° | <0,001° |
| Desvio do eixo no witness antiparalelo sintético | 70,53° | 0° |
| Segmento do antebraço zerado ou ausente | Salto local de 144,02° | 0° |
| NaN/infinito em ponto do punho | Quaternion e filtro contaminados | Pose finita e recuperação |

Também passam os testes de dois giros completos com passos de 2°, força 1 e
força live 0,85; referência corporal inválida; auxiliares parciais; retenção do
roll sem across; e retenção de antebraço sem girar uma mão com observação válida.

Reprodução:

```powershell
node experiments/review_20260930/solver_fixes/regression.mjs --sequences
```

## Sequências reais e renderização

Os mesmos 1.056 frames de cada sequência foram processados antes/depois,
com filtro e rig real. Todos os quaternions permaneceram finitos após as
correções. São replays de dados salvos, sem nova inferência do NLF.

| Sequência | Saltos de mão >90° antes/depois | Saltos de antebraço >90° antes/depois |
|---|---|---|
| `top_frames.json` | 0 → 0 | 0 → 0 |
| `raw_x55_frames.json` | 22 → 0 | 16 → 0 |

Isso não implica ausência de jitter: a entrada continua ruidosa e o filtro
continua introduzindo atraso. Os resultados detalhados estão em
`sequence_results.json` e `regression_results.json`.

O gate independente `absolute_palm_error.py`, com orientação medida no
avatar renderizado e referência anatômica separada, permaneceu semelhante à
referência existente `final`: mediana esquerda/direita 8,3°/8,4° na referência
e 8,4°/8,3° após a correção, em 264 frames amostrados do fit. O p95 mudou de
15,9°/18,6° para 16,1°/18,7°. No trecho do soco, a diferença média do componente
vertical da normal permaneceu 0,03/0,04. Não houve regressão material nesse gate.
Essa referência `final` é um artefato anterior existente, não uma nova execução
do snapshot `solver_before.js`.

```powershell
python scripts/check_palm_fidelity.py --tag solver_fixes_20260930 --step 4
python scripts/absolute_palm_error.py final solver_fixes_20260930
```

Foi gerado e inspecionado o A/B visual das seis fotos, nos avatares Boxeador e
Fighter Web: 24 capturas de mãos, com os mesmos pontos gravados do NLF e a
mesma câmera relativa ao punho. A pose foi repetida por 40 frames para observar
o resultado estabilizado. `render_ab.py` reproduz as capturas, e
`render_ab_measurements.json` guarda os quaternions mundo e hashes do texto
do solver servido em cada versão. Os PNGs `*_compare.png` mostram foto,
adaptador anterior e adaptador corrigido.

As fotos de palma para cima continuam limitadas pela orientação errada
produzida pelo NLF. Estas correções removem erros adicionais da tradução;
não recuperam a orientação que falta na entrada nem animam os dedos.

## Uso no live

O servidor em `http://127.0.0.1:8780/live` já serve o novo arquivo JavaScript.
Recarregue a página ao terminar uma gravação para carregar o solver corrigido;
uma página aberta anteriormente continua executando sua versão já importada.
