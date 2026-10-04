# Gravação de diagnóstico

Uma bolinha vermelha fica no canto inferior direito, acima dos controles de visão.
Com a webcam ativa, clique para iniciar. No Chrome/Edge, escolha a pasta de destino:
o jogo cria uma subpasta `corner-debug-<data>` e escreve nela durante a captura.
Clique novamente (o ícone vira um quadradinho) para encerrar e finalizar os arquivos.
Não há duração fixa. O contador mostra o tempo transcorrido; sair da página durante
uma gravação pede confirmação do navegador. Parar o debug não desliga a webcam.

Arquivos:

- `webcam.webm` (ou MP4 conforme o codificador): vídeo original da câmera, sem espelhamento e sem áudio, para reprocessar o reconhecimento.
- `comparacao.webm`: imagem renderizada do ringue, webcam espelhada com a última pose recebida, esqueleto NLF frontal e esqueleto final do avatar frontal. Menus/HUD HTML não entram no vídeo; estados relevantes aparecem na legenda e nos dados.
- `prints/`: JPEG da comparação a cada cinco segundos, incluindo a primeira amostra.
- `timeline.ndjson`: um JSON por linha, contendo eventos e amostras sincronizadas.
- `manifest.json`: duração, contagens, configurações, origem do relógio, formato dos vídeos e erros, caso a gravação seja parcial.
- `LEIA-ME.txt`: explicação suficiente para analisar a captura fora deste repositório.

Navegadores sem seletor de pasta acumulam a captura em memória e baixam um ZIP ao
parar. Para gravações longas, prefira o modo de pasta no Chrome/Edge, que escreve os
dados de forma incremental em disco. Nenhum arquivo é enviado ao adversário ou a
serviços externos. A captura aproveita o fluxo da webcam existente e não abre microfone.

## O que a timeline permite comparar

Eventos `pose` registram cada entrada aceita do tracker antes de normalização,
restrição de direção ou mudanças no avatar. Durante o debug, o bridge também inclui
a resposta original do servidor (`rawJoints`, `rawCameraJoints`, `rawAux`, SMPL-X55),
ID do frame, horário da captura JPEG e tempo da webcam correspondente, horário de
envio/resposta e latência. Capturas descartadas pelo servidor não recebem uma pose;
elas podem continuar aparecendo no vídeo original.

Amostras `frame` apontam para `poseSequence` e contêm a pose usada pelo jogo,
posição dos lutadores, visibilidade/contato dos pés, reação/atordoamento,
diagnóstico da colisão com o próprio rosto, parâmetros da câmera, transformações
do grupo/modelo e posição/rotação local e mundial de **todos os ossos nativos** dos
dois avatares. Também há leituras dos ossos mapeados após cinco etapas:

1. Retarget da pose.
2. Ajuste espacial das mãos.
3. Apoio dos pés, transformações do lutador e reação ao golpe.
4. Retenção do golpe na guarda.
5. Contato com o próprio rosto.

O registro lê essas etapas e não altera a pose. Durante hit-stop, o jogo pode não
executar o retarget naquele frame; o estado final é registrado mesmo assim e
`stages` fica vazio. Transformações `group`/`root` acompanham cada estágio para
permitir comparar coordenadas independentemente da movimentação no ringue.

`tMs` é relativo ao início da sessão. `absoluteMs` usa o relógio monotônico
`performance.timeOrigin + performance.now()`, inclusive dentro do iframe. Cada
vídeo tem um `startOffsetMs`; `webcamTime` permite associar a captura enviada ao
NLF com o fluxo original da câmera. Esses horários são observações do aplicativo,
não uma garantia de correspondência exata com o PTS de cada frame do codificador.
O overlay usa a **última resposta NLF**, que pode estar atrasada em relação à webcam
ao vivo; o vídeo informa sua idade. Não confundir esse atraso com erro espacial.

As vistas dos esqueletos são espelhadas como o painel da webcam. Esse reflexo é
apenas visual; as coordenadas gravadas e o retarget permanecem iguais.
São projeções esquemáticas ajustadas ao tamanho do esqueleto;
para medir flutuação, use as coordenadas mundiais no ringue. O vídeo de comparação
mantém a proporção da imagem do jogo. A captura mira 15 amostras por segundo;
baixa taxa de renderização resulta em menos amostras. A webcam usa a taxa de seu
fluxo. A gravação acrescenta trabalho de leitura de ossos e codificação:
`captureWorkMs` mede leituras/desenho e `gameAndCaptureWorkMs` inclui o frame do
jogo; não são medidas completas do custo do codificador ou da escrita em disco.

Implementação: `viewer/boxing_debug_recording.js`, instrumentação opt-in em
`viewer/boxing.js` e metadados opt-in em `viewer/live.html`. Validação:
`python tests/test_boxing_debug_recording.py` exercita codificadores reais,
integridade ZIP, reprodução dos dois vídeos, dados de entrada/estágios/ossos,
cancelamento, gravações repetidas e continuidade da webcam após parar.

Para viabilizar o carregamento, foi recuperado `viewer/boxing_feet.js`, que estava
ausente embora importado pelo jogo e pelo módulo de contato. O conteúdo veio da
leitura anterior desse mesmo arquivo, às 10:42 de 02/10/2026, normalizando apenas
quebras de linha. Não foi escrita uma nova lógica de marcha nessa recuperação.
