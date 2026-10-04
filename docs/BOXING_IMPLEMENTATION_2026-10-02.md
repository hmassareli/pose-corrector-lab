# HEAVY HANDS — implementação e gauntlet, 02/10/2026

> **Nota de revisão — 03/10/2026:** este relatório preserva evidência histórica. A nota 9,18 e os testes desta rodada não certificam versões posteriores nem excluem o conflito de chão/pivô depois admitido pelo assistente. A avaliação das solas não detectou offsets internos que se cancelavam. Consulte a [coletânea de pedidos e erros](COLETANEA_PEDIDOS_ENTREGAS_E_ERROS_2026-10-03.md), especialmente E4/E5, antes de reutilizar esta aprovação.

**Parecer independente: 9,18/10.** A sequência de avaliações foi 0,9 → 8,25 → 9,15 → 9,18. O avaliador encontrou falhas concretas, corrigidas antes da aprovação. O [parecer completo](BOXING_GAUNTLET_REVIEW_2026-10-02.md) conserva os pesos e os descontos por evidência parcial.

## Jogar

[Abra HEAVY HANDS](http://127.0.0.1:8780/static/boxing.html). O serviço local está iniciado. Ligue a webcam no indicador do menu, fique parado por um instante e aguarde a calibração estável e entre no treino. [Instruções de execução](BOXING_GAME_RUN.md).

## O que mudou

| Requisito | Implementação |
| --- | --- |
| 0 — Inicialização | Crop por conexão, detecção síncrona do primeiro frame e YOLO aquecido no carregamento. Calibração exige altura de 1,3–2,1 m e pelo menos 500 ms estáveis. |
| A/B — Pernas e chão | Passos inferidos, footContacts, visibilidade e IK extra de pernas removidos. Retarget conserva rotações; o chão move apenas a raiz a partir das solas nativas. |
| C/D — Guarda e mãos | Contato firme sem faixa macia de 2 cm; rosto sem orelhas. Base de mão destrogira, punho alinhado e palma no bissetor dos raios projetados. Projeção respeita alcance nativo. |
| E/F — Colisão | Cápsulas dos troncos renderizados, reparação nas bordas e distância de jab. Defesa exige interceptar luva/antebraço visível antes do alvo. |
| G — Física | Metros raw antes de escala/centralização; regressão de 150 ms, extensão ≥1 m/s, alcance de 40 cm, massas especificadas, contato de 15 ms e massa corporal configurável, inicialmente 80 kg. Apenas momentum frontal; movimento carregado pela guarda não gera socos. Força calculada após detecção. |
| Dano e faixas | Dano linear N/85 na cabeça e N/120 no corpo; mínimo de 80 N, teto de 2500 N e 30 HP; multiplicadores de contexto. Faixas independentes na escala de 1200 N. |
| H — Impacto | Contato por 110 ms e liberação em 80 ms; compressão/cedência dos braços, empurrão por força e queda orientada com gravidade. VFX graduais, trilhas e tags sérias em inglês. |
| I — Victor | 37 WAVs, prioridade por evento, uma fala ordinária a cada ≥3,2 s, KO prioritário e aviso ao cruzar 25 HP uma vez por lutador/round. Reverb de 1,4 s, pré-delay de 35 ms, wet de 20%, graves +3 dB e dobra de 18 ms/−12 cents. |
| J — Outline | Outline skinned, worker, opção e referências por avatar removidos; cenário estático conserva linhas. |
| K/UI | HEAVY HANDS, sala HEAVY1, menus PT/EN por tabela única com troca ao vivo. HUD de luta em EN. Treino exige rastreamento; seleção minimalista, recorde persistente e ajustes legíveis. |
| PEAK/Estatísticas | Tentativas no detector, acertos na colisão; ar/defesa/toque não aumentam recorde. PEAK em N/kgf, TOTAL em kN, média, precisão e dados de apoio; timeline por tempo/força/faixa e NEW PEAK. |
| KO — Áudio | Música, torcida, SFX e voz no barramento world. Perder por KO fecha LPF em ≈80 ms; ring de 3900 Hz e batimentos fora do world; voz +6 dB; restauração em até 4 s. Opção reduzida cancela nós/curvas e conserva KO normal. Heavy/super substituem samples somente nas faixas superiores. |
| Online | IDs evitam duplicação; força/histórico/recorde replicados. Histórico absoluto reparado em blocos de 16, inclusive após KO, até ACK completo. Slots esparsos preservados e resultado tolera histórico parcial durante reparação. |

## Evidências executadas

Artefatos em [experiments/heavy_hands_gauntlet](../experiments/heavy_hands_gauntlet/).

- **Benchmark atual, cache e captura nova:** 64/67, um falso positivo, punho isolado 10,55/10,53%. Matching cronológico um-para-um com ±350 ms documentados. Retração obrigatória, cooldown de 270 ms e tolerância de 0,1 mm no limite de 40 cm. Experimentos preservados em `detector_experiments.json`; 200/225 ms produziram falsos eventos demais e foram descartados.
- **Inicialização:** duas sessões WS novas, primeiro frame da mesma pessoa, sem priming. Alturas de 1,52296 m nas duas sessões, diferença zero; desvio/jitter zero em entrada estática controlada.
- **Replay de 11 minutos:** 17.696 samples raw; 17.641 aceitos, calibração em 2,2 s e 218 tentativas. Geometria em todos os 17.641 quadros: zero sobreposição, 100% das solas dentro de ±2 cm, erro máximo de 8,016 mm, punho máximo de 0,000153° e contato mínimo de +3,999 mm. Componentes de quaternion das pernas: alteração exata zero depois do retarget. Cinco bordas/cantos adicionais sem penetração.
- **Avaliador:** 185 poses por avatar, 555 medições totais; três modelos com punhos/palmas/contato/chão aprovados; screenshots de menu sem torções óbvias.
- **Combate:** queixo/tontura, dano proporcional, defesa real sem dano, abertura da guarda recebe golpe, corpo, KO/resultados; sem erros JS.
- **Webcam gravada:** fluxo real câmera → JPEG → NLF → bridge → jogo; reteste original contínuo com 553 poses e mediana de 15,337 Hz; teste com pausa inicial de calibração também aprovado; terceira/primeira pessoa e pausa sem câmera. Entrada gravada, não ensaio humano novo.
- **Online relay e P2P:** dois browsers, força/movimento, duplicatas/ar/recorde. Perda de 60 entradas quando KO acontece recuperada; host/guest com 61 tentativas/60 acertos, TOTAL de 36.000 N, PEAK de 600 N, sem NaN/erros. A bateria final repete a reparação nos dois transportes.
- **Áudio:** DSP world a 4 kHz com −63,43 dB aos 100 ms e retorno em 4 s; opção reduzida equivalente ao baseline, cancelando oito nós; 37 vozes decodificadas, prioridade e intervalo. Heavy: 1,3 s/44,1 kHz, RMS de −17,16 dB e peak de −1 dB; super: 0,8 s, RMS de −17 dB e peak de −2,29 dB.
- **Performance:** toon 60,0 → 60,3 FPS; original 60,3 → 60,3 FPS; aproximadamente 1,879 milhão de triângulos em ambos. Não houve comparação controlada de cadência NLF antes/depois.
- **Regressões:** core, clips mocap, UI em duas línguas/persistência, footwork, combate, relay, P2P, encoders ZIP/CRC/gravação e geometria. Scripts e logs preservados; nenhum reset/stash/commit sobre o trabalho prévio.

## Limites que não foram tratados como PASS

A tabela D2 original usa magnitude na direção da velocidade da mão; o jogo agora exige projeção para o alvo. Médias por fase com cache: 224/450/412/543/127 N; captura nova: 299/801/412/543/126 N; referência: aproximadamente 270/613/599/683/136 N. Algumas diferenças chegam a 31%. Não alterei massas/tempo de contato para forçar coincidência. Força continua sendo uma estimativa de câmera.

Startup foi medido com entrada estática. O replay usa NLF antigo, sem reprocessar o vídeo completo com novo crop. O teste geométrico avalia todos os samples aceitos, com desenho GPU desligado e posições do adversário mantidas entre 60 snapshots; não representa combate/narrador completo anotado. A fração de defesas no vídeo e a cedência de 6–8° dos dois cotovelos não receberam medição dinâmica exaustiva.

Audição humana das frases e do mix ainda é necessária. Deixei 25 exports do grafo real para cinco frases com 15/20/25/35% de reverb e 20% com música em [comparação de voz](../experiments/heavy_hands_gauntlet/voice_audition/index.html). Não declarei ter ouvido os sons. A disponibilidade jurídica do nome também não foi verificada.

## Repetir

Com lab na porta 8780 e relay na 8790 já ativos:

```powershell
python scripts/run_heavy_hands_gauntlet.py --full-replay
# Inclui a webcam gravada conhecida, sem ativar uma webcam humana:
python scripts/run_heavy_hands_gauntlet.py --full-replay --recorded-camera --backend-rebalance
# Benchmark original agora também executa o JavaScript de produção:
python scripts/benchmark_punch_power.py benchmarks/punch_cadence_20261002.mp4 80
# Captura nova, sem cache/priming:
python scripts/benchmark_punch_power.py benchmarks/punch_cadence_20261002.mp4 80 --fresh
```

Os fingerprints das fontes/sons estão em `handoff.json`; o resultado consolidado da bateria final, em `suite-result.json`. Backup anterior em `experiments/heavy_hands_gauntlet/before`. Scripts de migração únicos estão arquivados em `implementation_scripts`; testes reutilizáveis permanecem em `scripts`.

## Dobras da malha

É possível detectar e corrigir automaticamente boa parte delas. Um módulo pode medir triângulos invertidos/colapsados, estiramento e auto-interseções da malha deformada, exigir persistência por vários frames e corrigir com limites de junta/IK e distribuição de twist. Casos ligados a pesos ruins exigem corrigir skin weights ou usar corrective shapes/dual-quaternion skinning. Seria um módulo futuro por avatar; nesta entrega os punhos e as poses foram validados, sem prometer um corretor universal de malha.

## Correção de estabilidade encontrada na bateria final

A primeira repetição consolidada expôs um crash nativo do servidor durante rebalanceamento: o Windows registrou corrupção de heap (`0xc0000374`). A aprovação foi reaberta até corrigir e revalidar. Os resultados daquela execução ficam em `suite-first-run-with-failures.json`; o adendo do avaliador conserva o diagnóstico.

O runner criava logger/runtime TensorRT como variáveis locais. Agora há um logger único com duração do processo e o runtime é conservado junto ao engine. A [documentação NVIDIA](https://docs.nvidia.com/deeplearning/tensorrt/latest/architecture/how-trt-works.html) exige que o logger sobreviva aos objetos TensorRT. Esta era uma violação concreta; a causa exata da corrupção nativa é inferida do encerramento durante a criação de outro runtime, não de um dump completo de memória.

Também foram corrigidas concorrência do mesmo provider/contexto, reutilização do contexto antes de concluir CUDA, troca de pesos durante inferência e warm-up concorrente com carregamento. A reavaliação de backends passa pelo mesmo bloqueio nativo da inferência, tem proteção contra duplicação e só dispara com mediana e p95 persistentemente lentos; drops ou um pico inicial isolado não bastam. `--backend` explícito conserva a escolha. Uma reavaliação legítima pode pausar poses; HTTP continua disponível. O fallback TorchScript frio não é reavaliado durante a operação de um backend acelerado.

`backend-stability-test.json` registra 80 inferências concorrentes reais TensorRT após coleta de lixo, com diferença máxima zero para a referência, recriação de runtime, exclusão mútua dos providers e regressão de um pico de 50 s. O teste de combate agora congela a AI antes do setup e exige literalmente queixo com tontura; não aceita um acerto comum como equivalente. A posição de jab é controlada, mas luvas, braços e alvos continuam sendo os volumes dos avatares renderizados.

A câmera contínua original também foi revalidada depois das correções: `recorded-webcam-raw-final.json`, 553 poses, mediana de 15,337 Hz, maior intervalo de 270,8 ms, sem erros e sem descarte da escala calibrada ao entrar no treino. A primeira repetição desse vídeo sem pausa não completou a calibração em 120 s; o servidor permaneceu ativo. O teste padrão agora repete por dois segundos a primeira imagem real, antes de conservar todos os frames móveis originais. Isso representa a instrução de ficar parado durante a calibração; a regra de estabilidade da produção não foi relaxada. `raw-recorded` conserva a variante contínua.

`backend-rebalance-test.json` usa o método de produção com dois backends GPU reais (TRT/DML), 14 inferências antes/durante/depois e nenhum encerramento. Os backends CPU não foram certificados nesse teste. Reavaliação e calibração inicial usam a mesma preferência por TRT quando os tempos estão dentro de 20% do mais rápido, para reduzir trocas por ruído.


**Encerramento:** aprovação independente restabelecida em **9,18/10** (91,75/100). A bateria consolidada passou **17/17 verificações**, em 291,17 s. O adendo conserva o crash encontrado, as correções e os descontos que permanecem.
