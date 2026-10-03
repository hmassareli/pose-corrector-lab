# Veredito da tradução de movimento para os avatares 3D

> Auditoria histórica, anterior às correções de 2 de outubro de 2026. A implementação e sua validação estão em [AVATAR_POSE_FIXES.md](AVATAR_POSE_FIXES.md). As notas abaixo descrevem o estado auditado antes das correções; não foram recalculadas automaticamente.

## Conclusão

**Nota subjetiva geral: 7/10. Cabeça: 5,5/10. Pescoço: 6,5/10.** Há uma boa base de retarget corporal, especialmente nos braços e nas pernas, mas a orientação completa da cabeça ainda não está bem resolvida. Não atribuir a este sistema a nota visual/UX anterior do jogo: são avaliações diferentes.

Estas notas são um julgamento de engenharia para o jogo, não uma métrica científica nem uma média calculada dos ângulos. Todas as 20 entradas esperadas do rig estão presentes nos três avatares. Os problemas principais são geométricos e de tratamento do sinal, não falta dos ossos de cabeça/pescoço nos assets.

## Evidência e limites

- Solver atual e os três modelos reais: Prism, Titan/boxeador e Fighter Web.
- Reproduzida a criação/calibração do rig do jogo em um harness isolado; nenhuma alteração no solver, nos assets ou no movimento de produção nesta auditoria.
- Replay dos 1.056 frames x55 crus já existentes do vídeo do usuário; 264 frames medidos por avatar. Invocação a 30 Hz, suavização 50%, braços com override responsivo 4/4. Aplicado o alinhamento de quadril do jogo.
- Direções medidas após o retarget e antes do IK de contato do jogo. O IK posterior altera pernas/pés por necessidade de chão; os testes recentes de apoio estão em `experiments/boxing_review/footwork-*-test.json`.
- Probes independentes de yaw/pitch/roll faciais, sem suavização, repetidos em cada modelo. Posição do crânio/pescoço fica fixa e olhos/mandíbula giram em torno da junta da cabeça: isto isola a rotação da cabeça, que uma hierarquia de ossos precisa representar.
- Concordância com pontos NLF não é precisão contra a pessoa real. Não houve nova gravação humana, avaliação de novos usuários, medição de latência ponta a ponta ou certificação de todas as oclusões.
- Capturas próprias com os modelos renderizados e indicadores de orientação em `experiments/retarget_audit_current/`.

## Cabeça — o principal problema

| Movimento facial solicitado | Resposta da cabeça nos três modelos | Leitura |
|---|---:|---|
| Giro lateral ±45° | ~40,5° | Bom acompanhamento, atenuado pelo ganho 0,9 |
| Olhar acima/abaixo ±30°, sem deslocar a junta do crânio | ~0° | Grau de liberdade perdido |
| Inclinar a cabeça ±25°, sem deslocar a junta do crânio | ~0° | Grau de liberdade perdido |
| Retirar os olhos da entrada neutra | Giro indevido de 33,5–34,4° | Fallback muda a orientação sem movimento solicitado |
| Colapsar os olhos no mesmo ponto | Mesmo giro de 33,5–34,4° | Recuperação não mantém uma pose facial confiável |
| Linha dos olhos de 2 mm com direção errada | ~81° na cabeça; ~67,5° no pescoço | Stress test de confiança; não observado no replay |

O retarget SMPL usa `head−neck` como direção vertical da cabeça e `right_eye−left_eye` para o twist. Não usa o ponto médio dos olhos ou a mandíbula para completar a base facial. Uma rotação craniana independente pode preservar `head−neck`; pitch preserva também a linha transversal dos olhos e roll tem a componente vertical retirada pela projeção do across. Assim, o sinal facial existe na entrada, mas parte dele não chega à orientação da cabeça.

Isso **não significa que a cabeça jamais se incline**: inclinações que também movem a junta da cabeça e o pescoço podem aparecer. O defeito é perder movimentos independentes, o que impede uma cópia completa e pode dar sensação de cabeça rígida.

O fallback sem olhos deriva o forward de ombros × up, aplica um yaw limitado e muda a orientação até na pose neutra destes rigs. O teste reproduziu a mudança nos três modelos; não é hipótese baseada em screenshot.

Outro ponto é confiança: o across dos olhos é normalizado e aumentado para 0,4, praticamente garantindo peso completo. Anatomia com distância ocular relativamente fixa não implica que pontos inferidos sob oclusão sejam confiáveis. No replay real, a separação dos olhos foi 48–78 mm; o exemplo de 2 mm é uma entrada adversa controlada, não um diagnóstico de ocorrência frequente.

No replay, a orientação da cabeça comparada a uma base facial independente dos olhos/ponto médio/crânio, removendo apenas um offset constante do rig, teve residual mediano ~5,9–6,0° e p95 ~13,6°. Essa sequência tem principalmente movimentos corporais acoplados; esse resultado não invalida a falha nos graus de liberdade isolados.

O caminho secundário Pose-33 também merece revisão: manda alinhar o eixo longitudinal do crânio ao forward facial. No probe neutro, a orientação mudou ~61–62° em relação ao neutro SMPL. Isso revela incompatibilidade entre os caminhos; não quer dizer que o avatar esteja sempre com esse erro durante NLF-S.

Referências: `viewer/mikapo_mixamo_solver.js`, `smplHeadBasis`, `applyHeadFromSmpl`, `applyHeadFromAux`.

## Pescoço — melhor que a cabeça, mas aproximado

A direção do segmento cervical divergiu da direção pescoço→cabeça recebida em ~11,7–12,1° na mediana e ~15,7–16,0° no p95. Parte é deliberada: o alvo cervical mistura 50% da continuação da coluna com 50% do eixo pescoço→cabeça e depois usa força 0,75 contra uma referência ereta. Isso melhora uma silhueta torta, mas reduz fidelidade.

O yaw facial de 45° produziu 33,75° no pescoço e 40,5° de orientação final da cabeça. São orientações globais da cadeia, não dois ângulos que devem ser somados. Essa distribuição fixa é plausível para um jogo, mas não mede a contribuição cervical real.

Há boa preocupação com pose neutra e diferenças dos modelos: a referência ereta evita herdar a inclinação autoral grande do Fighter Web. Porém, a continuação usada pelo pescoço vem dos pontos originais da coluna enquanto o tronco usa waypoints suavizados geometricamente. Não é a mesma cadeia final; isso pode deixar a junção menos coerente. Também faltam limites articulares explícitos relativos ao tronco para impedir posturas cervicais implausíveis em entradas adversas.

## Veredito por região

| Região | Qualidade atual | Observação principal |
|---|---|---|
| Pelve/quadril | Razoável a boa | Translação absoluta foi recuperada; orientação ao adversário é uma restrição deliberada do jogo. Offset dos pivôs ainda depende da primeira pose e pode misturar rotação corporal com deformação. |
| Coluna inferior/média/superior | Boa para aparência; fidelidade parcial | Cadeia foi corretamente subdividida e suavizada para remover zig-zag do NLF. Não é cópia exata das curvaturas de cada junta. |
| Clavículas esquerda/direita | Boa, estilizada | Movimento é transferido como desvio em relação à postura do modelo. Ângulo absoluto alto contra SMPL não prova ombro errado; a anatomia e a pose de repouso diferem. |
| Braços esquerdo/direito | Muito boa na direção | Medianas ~2,2–2,6°; os extremos do replay chegam a ~8° no p95. Twist usa witness do cotovelo e perde observabilidade com braço muito reto. |
| Cotovelos/antebraços esquerdo/direito | Muito boa na direção | Medianas ~1,9–2,0°; p95 até ~10,8°. Isso não certifica pronação da mão contra vídeo real. |
| Punhos/mãos esquerdo/direito | Boa, dependente dos dedos inferidos | Direção ~2,2–2,5° na mediana. Palma tem tratamento de polaridade/continuidade já melhorado; confiança dos pontos continua relevante. |
| Coxas esquerda/direita | Muito boa antes do contato | Medianas ~2,5–3,2°. Retarget direcional não equivale a dinâmica real de transferência de peso. |
| Joelhos/pernas esquerda/direita | Muito boa antes do contato | Medianas ~1,8–2,3°. IK de chão modifica a pose final para manter apoio. |
| Tornozelos/pés esquerdo/direito | Boa para o jogo; parcialmente estimada | Direção ~5,1–6,5° na mediana. Apoio, swing e sola nativa têm solver próprio. Quando os pés estão fora da imagem, é animação inferida pelo corpo; não recuperação do passo real. Roll do tornozelo não é transferido integralmente. |
| Pescoço | Razoável | Melhora visual existe; amplitude e distribuição seguem heurísticas, com residual maior que os membros. |
| Cabeça | Incompleta | Yaw bom; pitch/roll cranianos independentes falham; fallback dos olhos provoca giro indevido. |
| Dedos e articulações da mão | Não capturados individualmente | Pontos de dedos orientam a palma; falanges não estão entre os 20 ossos acionados. Luvas fechadas podem esconder essa limitação. |
| Mandíbula, olhos e expressões | Não animados como face | Olhos servem ao yaw; mandíbula recebida não participa da base facial principal e não há animação facial completa. |

## Ângulos por junta

Cada célula: mediana / p95 do ângulo entre o segmento do avatar e o segmento fonte. Isto mede direção, não posição do punho no espaço nem orientação completa. Clavículas e segmentos internos de coluna incluem diferenças de definição e ajustes deliberados; não transformar estes valores brutos diretamente em nota de qualidade.

| Junta / segmento | Prism | Boxeador | Fighter Web |
|---|---:|---:|---:|
| Pelve / quadril | 13.6° / 21.5° | 13.7° / 22.1° | 13.6° / 21.8° |
| Coluna inferior | 14.6° / 25.3° | 14.6° / 25.4° | 14.6° / 25.3° |
| Coluna média | 32.5° / 41.1° | 32.4° / 41.1° | 32.5° / 41.1° |
| Coluna superior | 1.8° / 3.8° | 1.8° / 3.9° | 1.8° / 3.8° |
| Pescoço | 12.1° / 16.0° | 12.1° / 16.0° | 11.7° / 15.7° |
| Clavícula esquerda | 19.6° / 21.5° | 33.4° / 35.3° | 18.1° / 20.3° |
| Clavícula direita | 18.9° / 21.4° | 32.9° / 35.3° | 28.3° / 30.0° |
| Braço esquerdo | 2.3° / 7.7° | 2.2° / 7.9° | 2.2° / 7.3° |
| Braço direito | 2.6° / 8.1° | 2.5° / 7.5° | 2.6° / 7.8° |
| Antebraço esquerdo / cotovelo | 1.9° / 10.4° | 1.9° / 10.3° | 1.9° / 10.2° |
| Antebraço direito / cotovelo | 2.0° / 10.8° | 2.0° / 10.8° | 2.0° / 10.7° |
| Mão esquerda / punho | 2.2° / 7.7° | 2.3° / 7.9° | 2.2° / 8.1° |
| Mão direita / punho | 2.5° / 9.3° | 2.5° / 9.2° | 2.5° / 8.7° |
| Coxa esquerda | 2.5° / 6.2° | 2.5° / 6.1° | 2.5° / 6.2° |
| Coxa direita | 3.1° / 6.8° | 3.2° / 6.8° | 3.1° / 6.8° |
| Perna esquerda / joelho | 1.8° / 4.5° | 1.8° / 4.5° | 1.8° / 4.7° |
| Perna direita / joelho | 2.2° / 5.6° | 2.2° / 5.6° | 2.2° / 5.6° |
| Pé esquerdo / tornozelo | 5.1° / 8.9° | 5.5° / 9.4° | 5.1° / 9.1° |
| Pé direito / tornozelo | 6.1° / 10.9° | 6.5° / 11.6° | 6.4° / 11.4° |
| Cabeça | Probes faciais acima | Probes faciais acima | Probes faciais acima |

## Prioridades para melhorar

1. Construir uma base facial completa, com forward/up/across distintos, usando olhos + ponto médio facial/crânio/mandíbula; calibrar a face neutra de cada rig. Não trocar o eixo longitudinal do osso pelo forward sem compensação de repouso.
2. Distribuir cabeça/pescoço em relação à cadeia torácica final e colocar limites anatômicos relativos ao pai; decidir qual atenuação é desejada e medir a amplitude preservada.
3. Avaliar plausibilidade/condicionamento da face; manter a última orientação confiável durante falha dos olhos e recuperar continuamente, corrigindo o fallback que gira a pose neutra.
4. Verificar cabeça com cabeça parada + face girando, olhar para cima/baixo, inclinação lateral, guarda cobrindo o rosto, perfil, retorno de oclusão e diferentes cadências. Verificar os três modelos, a malha renderizada e os quaternions.
5. Depois, refinar confiança da palma, degeneração com braços/pernas retos, neutralização de offsets e transição de pés observados/estimados. Aumentar suavização global não recupera informação descartada da cabeça.

## Reprodução e artefatos

Execute `python scripts/audit_avatar_retarget.py` com o servidor local do laboratório em 8780. O script só cria evidências de auditoria, sem editar produção. `--visual-only` atualiza apenas as capturas. Requer os assets, Three.js 0.160.0 e a sequência já existentes.

Relatório: `experiments/retarget_audit_current/report.json`; amostras por avatar, capturas yaw/pitch/roll/fallback e script de reprodução estão preservados. Durante uma primeira carga da página do jogo foi observado `sparks is not defined`; a avaliação geométrica foi isolada do loop do jogo e não demonstra estabilidade desse loop. Esse erro não explica os graus de liberdade perdidos, que foram reproduzidos pela API do solver sem o jogo.

SHA-256 do solver analisado: `b9d97355a288107961dc2f09fb6815c426e66b527ae14d1b834804e4047620fc`.
