# Avaliação CORNER

Meta solicitada pelo usuário: nota subjetiva ≥9/10. A nota precisa ser justificada com evidência; testes técnicos são critérios separados.

## Protocolo do avaliador

Avalie screenshots reais do build em execução e, quando disponível, navegação/estado de combate. Leia o código para identificar incoerências, mas não atribua aprovação visual sem telas. Não suponha que recursos sem evidência funcionam. Retorne visual (35%), UX (30%), leitura do combate (20%), coerência (15%), nota ponderada, bloqueadores, três correções prioritárias e caminhos de evidência. Critérios: paleta e materiais estilizados sérios, hierarquia clara, qualidade do palco, personagens legíveis, corpo inteiro em terceira pessoa, primeira pessoa limpa, menus sem sobreposição, feedback de golpes/guarda/rede compreensível. Meta ≥9 e categorias ≥8. Nunca ajustar nota para satisfazer o objetivo artificialmente.

## Registro

Baseline: laboratório de pose existente, sem interface de jogo. Avaliação estática do subagente confirmou APIs e riscos; ainda sem nota visual.

| Rodada | Nota | Correções que orientaram a próxima rodada |
|---|---:|---|
| 1 | 7,34 | Visibilidade do oponente e iluminação da arena |
| 2 | 7,78 | Pose dos braços e pescoço |
| 3 | 8,10 | Resize e acessórios das mãos |
| 4 | 8,40 | Primeira pessoa e sobreposição do feedback |
| 5 | 8,73 | Guia compacto e variedade da torcida |
| 6 | 9,015 | Aprovação visual e UX; leitura do combate 8,7 |

Notas do subagente game_reviewer, independentes. Rodada 6: visual 9, UX 9,1, leitura 8,7, coerência 9,3. Evidência atual em experiments/boxing_review/01-lobby.png até 06-small.png; os arquivos foram atualizados durante as iterações e não são um arquivo histórico de cada rodada. A aprovação cobre as telas desktop avaliadas, não toda a jogabilidade.

Verificações separadas: testes de varredura/cápsula, movimento orbital e retração de soco passaram; dois browsers passaram no relay público e no DataChannel P2P; três avatares carregaram; suavização em 0 funcionou; ausência de pose e desconexão pausaram a luta. Replay de webcam pelo NLF CUDA/TRT produziu 77 amostras, mediana 15,03 FPS para vídeo de entrada de 15 FPS, sem erros de página. Isso não mede o limite de desempenho nem a precisão de uma luta humana.

As capturas 07-recorded-nlf-third.png e 08-recorded-nlf-first.png usam o vídeo existente do usuário pelo pipeline real de inferência. A primeira pessoa oculta cabeça/pescoço por skin weights, mantendo as luvas originais. Faltam teste humano com duas redes externas e ajuste final do áudio.

Revisão final dessas duas capturas: aprovação anterior mantida para palco e interface, sem novo bloqueador crítico. Luva durante golpe cobre parcialmente o rival; verificar em movimento se a obstrução é breve. Não foi atribuída nova nota ao tracking ou à ergonomia temporal a partir de frames isolados.

Correção após teste humano: referência de alinhamento passou dos ombros ao quadril, preservando o giro do tórax no hook. Render interpola poses e auxiliares numa janela de uma amostra (20–80 ms, proporcional ao slider até 50%); 0% desliga esse buffer e o filtro. Colisão e comandos continuam na pose mais recente. Testes verificaram progressão entre frames, sincronismo dos auxiliares das mãos, bypass e reset após perda de tracking; replay NLF passou sem erros. Ainda confirmar a sensação do hook ao vivo; não atribuir nova nota por esses testes.

Correção de captura após relatos de "pose perdida": o iframe oculto passou a capturar por timer, independente do requestAnimationFrame; a fila libera também IDs antigos descartados pelo servidor e impede encodes simultâneos. Parar/reiniciar limpa fila e timer. Teste com requestAnimationFrame desativado no iframe: 225 poses em 15 segundos, entrada de 15 FPS, maior intervalo 129 ms, sem erros; reinício da webcam voltou a produzir poses. O limite de pausa por falta de atualização continua em 500 ms. O aquecimento inicial agora é descrito como espera da primeira pose, em vez de perda da pose.

## Ajustes após novos relatos humanos

A hipótese de captura suspensa não foi comprovada como causa do sintoma original. A proteção permanece, mas não é apresentada como diagnóstico de latência humana.

Removida interpolação adicional da pose local; braços têm filtro específico mais responsivo, preservando o slider e seu bypass em 0%. Probe sintético de pose→render a 50%: resposta de metade do deslocamento passou de 33,3 ms para o primeiro frame. Isso exclui câmera/inferência e não significa latência total zero.

Movimento lateral mudou de velocidade por afastamento do centro para deslocamento orbital proporcional ao passo. Parar não continua circulando; retorno acompanha o movimento inverso. Câmera acompanha a posição sem lerp adicional. Teste pela ponte de mensagens: passo físico sintético de 10 cm produziu cerca de 22 cm no ringue em duas atualizações; deriva lateral <1 cm durante a espera. Oponente continua voltado ao alvo.

Luz ambiente/preenchimento mais suave; sombras do próprio modelo desligadas em primeira pessoa para evitar sombra da cabeça invisível. Próprio modelo em DoubleSide nessa visão, câmera sem segunda suavização, near menor e afastamento curto de cápsulas de tronco/braços. Comparações em feedback-before/after-first e shoulder. Verificação manual, não uma certificação de todas as poses.

Reação aditiva de cabeça/pescoço/tórax na direção do golpe, recuperação em 0,5 s; teste mediu 8,63° no pico e recuperação ao repouso. Partículas curtas em tons de pele/rosado e ponto de impacto na superfície. Controles seguem pela webcam; não é simulação de corpo rígido que impede toda penetração das mãos.

Som preservado com offset de início de 188–332 ms, removendo espera no arquivo. Testes de áudio, recoil, movimento e replay NLF passaram sem erros de página. A nova revisão por subagente não executou por limite de uso; não foi inventada nova nota. Aprovação 9,02 permanece o registro da revisão anterior.

## Passos e profundidade — revisão posterior

Encontrado descarte da translação absoluta no servidor: `j55_m = pts_m - pts_m[0]`. A pose relativa permanece para compatibilidade; novo `camera_joints` conserva a estimativa absoluta para o jogo. A ponte Live agora transporta essa informação sem o ajuste antigo de chão. O jogo deixou de amplificar X por 2,8 e interpretar Z como velocidade; usa deslocamentos métricos normalizados pela altura. Aproximação automática existe apenas para o bot. Avanço/recuo do jogador vêm habilitados por padrão, com limites de ringue/contato; o bot não é teleportado para a antiga distância máxima quando o jogador recua.

`WebcamFootwork` detecta apoio/balanço por elevação, velocidade e afastamento acumulado do pé, incluindo passos arrastados. `FootPlanting` resolve as duas pernas após o retarget: pé de apoio mantém âncora no mundo, pé em balanço segue a posição fonte. Soleiras usam vértices das botas originais; não foram criadas próteses ou meshes adicionais. Apenas o primeiro frame estabelece o chão; não zerar a altura dos tornozelos a cada frame.

Correção de requisito pelo usuário: pés podem sair da imagem. Não bloquear deslocamento nesse caso. Visibilidade usa projeção com as mesmas intrínsecas aproximadas do NLF; quando os pés estão fora, o jogo gera passos alternados com elevação de 6,5 cm e apoio estável, guiados pelo deslocamento do corpo. Isso é estimativa, não recuperação de passos que a câmera não observou. A perda do tronco suspende translação e evita salto na recuperação. Histerese reduz alternância de modo na borda da imagem.

Testes controlados em WebGL nos três modelos: pé levantado antes da translação do corpo, apoio preservado dentro de 2 cm durante transferência de peso, avanço/recuo, ausência de deriva parado e movimento com pés fora da imagem. Evidências: `footwork-<avatar>-test.json` e `footwork-<avatar>-third.png`. Testes unitários incluem apoio, passo arrastado, translação métrica e enquadramento parcial. Replay real do vídeo do usuário e transporte online são verificações separadas. A nota visual anterior não certifica esta nova locomoção; avaliação humana de passos, escala de profundidade e transição observado/estimado continua pendente.

Resultado final do replay: 77 poses, mediana 15,02 FPS para entrada de 15 FPS, sem erros de página. Translação absoluta preservada; profundidade estimada do quadril entre 2,48 e 2,66 m. Todos os 77 frames usaram passos estimados por pés fora da imagem, com jogo em execução. Maior intervalo entre poses: 302 ms; isso não mede latência de resposta humana. Em testes sintéticos dos três modelos, pelo menos uma sola ficou a até 2,2 cm da lona durante o passo estimado; tolerância do teste é 3 cm, pois os sapatos são malhas deformáveis. Transporte relay e P2P passaram com novos campos de avanço/recuo e contato/visibilidade; posição prevista do convidado concordou com a autoridade após confirmação. Nenhum desses testes permite atribuir nota à sensação de andar ao vivo.
