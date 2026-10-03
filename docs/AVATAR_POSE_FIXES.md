# Correções de poses — 2 de outubro de 2026

Implementação do trecho R1–R5 de [RETARGET_AND_PERFORMANCE_PLAN.md](RETARGET_AND_PERFORMANCE_PLAN.md). NLF-S/SMPL-X55, os três avatares, luvas nativas, controles de webcam e slider 0–100 foram preservados. Os experimentos de aceleração da inferência não fazem parte desta entrega.

Complemento posterior: [guarda e contato com o próprio rosto](AVATAR_SELF_CONTACT.md). Corrige a penetração perto da face sem mudar novamente a orientação da cabeça.

## Cabeça e pescoço

- **R1:** a linha entre os olhos e o vetor crânio→ponto médio ocular formam uma orientação completa. Assim, olhar para cima/baixo e inclinar a cabeça não dependem de deslocar a junta do crânio. A mandíbula funciona como referência de consistência: a junta SMPL-X não é a ponta do queixo. A calibração retira o offset anatômico de pitch; não anula yaw/roll.
- **R2:** olhos ausentes, colapsados ou geometricamente incoerentes deixam de produzir orientação artificial. A última orientação confiável acompanha o tronco por 220 ms, depois relaxa progressivamente. A recuperação usa uma transição de 120 ms. Um salto isolado incompatível com o intervalo da amostra é rejeitado; observações seguintes coerentes podem confirmar movimento rápido. Repetir uma pose antiga na renderização não renova sua confiança facial.
- **R3:** cabeça e pescoço recebem uma escrita e uma filtragem por atualização. Timestamps repetidos mantêm o estado do filtro. A filtragem desses ossos usa velocidade angular e interpolação de quaternions, com parâmetros próprios vinculados ao slider existente; 0 continua sendo bypass. O tempo da amostra e o da apresentação são explícitos.
- **R4:** o pescoço continua a orientação do último osso torácico já resolvido e compartilha parte da orientação facial. Limites relativos entre tronco/pescoço e pescoço/cabeça evitam torções excessivas, sem a antiga redução fixa de amplitude da cabeça.

O Fighter Web não tem uma junta no topo do crânio. Seu eixo facial usa a orientação nativa do osso no FBX, em vez de interpretar pescoço→cabeça como orientação do rosto. Essa referência é preservada quando o rig é reconstruído para ajustar escala.

O bot agora posiciona olhos e mandíbula em relação ao crânio. A calibração do preview, da webcam, do sparring e do peer online tem identidade separada, evitando carregar a anatomia sintética do bot para a primeira pose real. O botão **Calibrar** também reinicia a referência facial e os filtros. Ao começar ou recalibrar, mantenha a cabeça naturalmente neutra: a primeira observação confiável estima o offset anatômico de pitch.

## Braços, mãos e apoio

Um braço esticado deixa de voltar abruptamente ao roll de repouso quando o cotovelo perde seu vetor de referência. O solver conserva a orientação anterior e retoma a referência quando ela volta a ser observável. O cache guarda a pose resolvida antes dos efeitos de impacto/IK, impedindo que esses efeitos contaminem a continuidade do frame seguinte.

A orientação transversal da palma é rejeitada quando os pontos são quase coincidentes ou desproporcionais ao alcance da mão. Isso mantém a direção do braço/mão sem transformar ruído de milímetros em uma torção grande.

Na marcha inferida com pés fora da câmera, o contato considera a sola deformada pelo skinning da malha nativa. O ajuste de alcance abaixa ligeiramente a pelve quando necessário, em vez de forçar uma perna a ultrapassar seu comprimento. A posição horizontal de apoio permanece ancorada; pés não observados continuam permitidos.

## Validação e limites

- `scripts/test_avatar_pose_fixes.py`: **57 verificações aprovadas**, 19 em cada avatar. Inclui orientação completa com sinal e eixos combinados, olhos ausentes/degenerados/NaN, oclusão, recuperação, flip isolado, relógios, limites articulares, braço reto, palma degenerada e separação da calibração preview/webcam.
- Nos probes sem filtro, yaw ±45°, pitch ±30° e roll ±25° são reproduzidos nos três rigs; o erro da orientação completa ficou abaixo de **0,02°**. O estado anterior perdia quase todo pitch/roll nesses mesmos probes.
- Em entrada sintética a 30 Hz, o filtro de cabeça atinge 90% de um giro rápido em **66,7 ms** nos sliders 50/100; 0 acompanha a primeira amostra. Um ruído parado de 0,8° pico a pico cai para aproximadamente 0,36°. Esses números medem o retarget, **não** a latência da webcam até a tela.
- `scripts/test_boxing_core.mjs`: testes de contato, hooks, movimento orbital, apoio, profundidade, pés recortados e guarda aprovados.
- `scripts/test_boxing_footwork.py`: os três avatares passaram. O corpo espera o apoio antes de transferir o passo; o apoio observado deriva menos de 0,001 mm no cenário controlado. Na marcha inferida, a sola de apoio acompanha o canvas de 0,026 m, com erro máximo positivo de aproximadamente 0,003 mm no teste. Não interpretar essa precisão sintética como precisão dos contatos estimados pela webcam.
- `scripts/test_avatar_game_integration.py`: orientação facial, alternância primeira/terceira pessoa, recalibração e ausência de erros de console aprovadas.
- `scripts/test_boxing_recorded_webcam.py`: vídeo gravado apresentado como webcam → JPEG → NLF-S → bridge → jogo aprovado, incluindo os dois modos de câmera e pausa ao desativar a captura. Espera a atualização real do recorte da cabeça antes da captura de primeira pessoa. O backend reportado nesta execução foi TensorRT/CUDA.
- No replay NLF, o erro residual facial mediano caiu de cerca de **5,9–6,0° para 0,90°**, e o percentil 95 de cerca de **13,6° para 2,12°**. A diferença mediana da direção cervical caiu de 11,7–12,1° para 8,3–8,5°. Nenhuma outra direção auditada piorou mais de 1° no percentil 95. A comparação remove um offset constante de rig e mede concordância com os pontos de entrada.

Relatórios: [regressão dos três rigs](../experiments/retarget_pose_fixes/regression.json), [replay NLF](../experiments/retarget_pose_fixes/after/report.json), [comparação antes/depois](../experiments/retarget_pose_fixes/comparison.json) e [integração do jogo](../experiments/retarget_pose_fixes/game-integration.json). O replay usa 1.056 frames NLF existentes, com 264 frames medidos por avatar; mede concordância com a estimativa de entrada, não com uma captura de movimento de referência.

Não foi atribuída uma nova nota subjetiva nem certificado ganho de FPS do reconhecimento. A avaliação humana restante é testar olhando para os lados, assentindo, inclinando, girando o tronco com rosto fixo, cobrindo o rosto com a guarda e recuperando após oclusão.

O navegador automático com backend gráfico padrão não sustentou poses suficientes para o teste de captura. Com ANGLE D3D11 explícito, a integração passou, mas chegou a aproximadamente 0,87 pose/s com intervalos grandes. Esse teste não aprova responsividade nem serve como benchmark de ganho: não houve comparação antes/depois da captura sob o mesmo ambiente. O relatório de captura está em [recorded-webcam-test.json](../experiments/boxing_review/recorded-webcam-test.json). Uma nova sessão humana no navegador usado para jogar continua sendo necessária.
