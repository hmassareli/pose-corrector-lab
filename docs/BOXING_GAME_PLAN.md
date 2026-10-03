# CORNER — plano do jogo de boxe

## Objetivo e decisões — 1 de outubro de 2026

Jogo de boxe estilizado para dois jogadores em browsers, controlado pela webcam. Preservar os três personagens do registro `avatar_assets.js`, o solver MiKaPo atualizado, NLF-S + SMPL-X55 e o slider One Euro 0–100 (0 desliga; 50 mantém os parâmetros atuais). Não substituir experimentos anteriores nem declarar que um método venceu sem medições.

## Entregas

1. Cena de ringue, iluminação quente/fria, torcida estilizada discreta, HUD legível, menu e treino contra sparring, com controle exclusivamente pela webcam. Nenhum comando de teclado; as luvas são as nativas dos modelos, sem esferas ou substitutos.
2. Primeira pessoa nos olhos do lutador; terceira pessoa elevada atrás, corpo inteiro e adversário visíveis. Câmera segue o duelo, sem giro livre involuntário.
3. Adapter para o pipeline Live existente. Vídeo e inferência NLF ficam no computador do jogador; pela rede seguem poses e comandos. NLF não é um modelo que hoje roda automaticamente em qualquer browser: requer o serviço local e os pesos já existentes. Uma versão pública precisa resolver esse requisito ou oferecer MediaPipe local explicitamente.
4. Movimento orbital pela translação absoluta da câmera estimada pelo NLF, preservada separadamente da pose relativa. Escala calibrada pela altura; sem ganho lateral artificial ou avanço automático do jogador. Avanço/recuo habilitados por padrão, limitados pelo ringue e distância mínima de contato. Calibração redefine o centro físico sem mudar a posição no ringue. Pés visíveis: detectar apoio/balanço, manter pé de apoio no mundo e resolver a perna por IK; sola usa a geometria nativa da bota. Pés fora da imagem: permitir movimento pelo tronco e gerar passos alternados estimados, sem exigir corpo inteiro continuamente. Rotação do quadril limitada a ±12° em relação ao alvo, preservando o giro do tórax no hook. Câmera acompanha diretamente; slider de suavização continua disponível.
5. Simulação fixa 60 Hz. Luvas com varredura contínua contra esfera da cabeça e cápsula do tronco; braço estendido sozinho não causa golpes repetidos. Velocidade mínima, janela de ataque, retração e cooldown por mão. Defesa por mãos junto ao rosto, esquiva pela pose. Normalizar dimensões físicas dos personagens para evitar vantagem pelo tamanho do asset.
6. Vida, guarda e atordoamento temporário. Energia fica para uma evolução após validação humana. Reação visual aditiva leve, limitada: evitar perder controle por segundos ou atrasar globalmente a webcam. Feedback distinto de bloqueio, golpe limpo e nocaute. Rounds e resultado sincronizados.
7. Relay WebSocket primeiro; P2P WebRTC opcional com sinalização pelo mesmo servidor, canal de poses sem retransmitir frames antigos, fallback relay e indicação do transporte real. Um jogador é autoridade na versão casual; não prometer resistência a trapaças. Servidor autoritativo e compensação de latência são evolução necessária para competição.

## Rede / Contabo

SSH verificado em `contabo`. VPS usa Docker Swarm/Easypanel/Traefik e já contém outros serviços. Criar serviço isolado e publicar somente após testes; não alterar serviços existentes. HTTPS/WSS obrigatório fora de localhost. Limitar tamanho/frequência de mensagens, salas de dois jogadores, validade de IDs, timeout e limpeza. P2P pode falhar em NAT simétrico; TURN necessário para cobertura ampla. Medir RTT real entre duas conexões externas antes de anunciar baixa latência.

## Som

Preferir Foley gravado/licenciado: luva em saco/pad, roupa, passo em lona, impacto corporal, sino e torcida em camadas. Assets precisam de licença registrada em manifesto, ganho por categoria, variações e ausência de clipping. Sem osciladores improvisados como trilha definitiva. Torcida reage à sequência de golpes e ao atordoamento, com cooldown. Vozes opcionais gravadas/TTS de qualidade para início e resultado. FL Studio via MCP não deve ser presumido disponível: avaliar conectores existentes e bibliotecas licenciadas; ferramenta de síntese musical não substitui Foley convincente. A versão atual usa WAVs gravados: impactos DavidW (CC-BY 4.0), sino e torcida Umplix (CC0). Licenças em assets/boxing_audio/CREDITS.md. Torcida reage aos impactos. Música e vozes opcionais ficam para depois.

## Loop de avaliação até 9/10

Executar, testar invariantes, capturar menu/luta/primeira pessoa/configurações e entregar evidência ao subagente avaliador. Notas subjetivas independentes: visual 35%, UX 30%, leitura do combate 20%, coerência 15%. Meta ponderada ≥9, nenhuma categoria <8, nenhum defeito crítico. Registrar cada rodada, screenshots, pontos fracos, alterações e resultado. Prints não comprovam latência, tracking, colisão nem rede: essas partes precisam de testes próprios. Não aumentar nota apenas para encerrar. Avaliação humana com webcam e dois jogadores continua indispensável.

## Critérios de aceite

- Os três avatares carregam, sem T-pose durante luta, braços acompanham pose e palmas usam os auxiliares existentes.
- Slider persiste e 0 bypassa filtro; não suavizar detector de golpe junto do render.
- Câmera não corta adversário ou corpo em terceira pessoa, nem mostra rosto próprio na primeira.
- Sem golpe parado repetido; bloqueio e retração funcionam; distância e ringue limitados.
- Dois clientes recebem mesmo resultado, entrada fora de ordem é descartada, desconexão interrompe a luta.
- Interface funciona em 1366×768 e 1920×1080; 60 FPS de render é alvo, medir no hardware real.
- Erros de webcam, NLF, asset e rede são explicados na própria interface.

## Limites da primeira versão

Plano complementar registrado em 2 de outubro de 2026: [retarget, cabeça/pescoço e desempenho para hardware mais fraco](RETARGET_AND_PERFORMANCE_PLAN.md). As [correções de poses R1–R5](AVATAR_POSE_FIXES.md) foram implementadas e receberam validação automatizada. A meta de capacidade de reconhecimento +15% permanece uma proposta a medir.

Sem ranking, compras, ragdoll completo ou matchmaking público. Começar com arena de campeonato e variação de iluminação; priorizar qualidade sobre quantidade. A revisão visual atingiu 9,02/10; replay de webcam passou pelo NLF CUDA/TRT. Relay público e P2P passaram em dois navegadores na mesma máquina. Ainda validar duas pessoas em redes externas, calibrar golpes e ouvir/mixar os sons durante uma luta real; não confundir os testes automatizados com essa validação humana.

