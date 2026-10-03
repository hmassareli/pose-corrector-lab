# HEAVY HANDS — executar e jogar

No ambiente Python configurado do laboratório, dentro de `pose_corrector_lab`:

```powershell
python scripts/serve_lab.py --host 127.0.0.1 --port 8780
```

Abra [HEAVY HANDS](http://127.0.0.1:8780/static/boxing.html). Ligue a webcam pelo indicador do menu, permita a câmera e aguarde o estado calibrado. Afaste-se até aparecer o corpo inteiro e fique parado por um instante durante a calibração. O treino só é liberado após pelo menos meio segundo de rastreamento estável. Toda ação da luta vem da webcam; não há controle pelo teclado.

As pernas seguem o NLF sem passos inventados. O ajuste do chão move apenas a raiz do avatar. Avanço/recuo e movimento lateral usam translação métrica; massa corporal, suavização, visão, personagem, idioma e som ficam em Ajustes. Os menus alternam entre português e inglês; o HUD de combate permanece em inglês. PEAK só cresce quando você acerta o adversário e fica salvo neste navegador. Força é uma estimativa da câmera em newtons, não uma medição com dinamômetro.

O botão de gravação exporta vídeo original, comparação, poses, estágios do retarget e ossos finais. A webcam continua ligada ao voltar ao menu; pode ser desligada pelo indicador. Sem câmera/rastreamento, a luta pausa.

Para duelo, ambos precisam do laboratório local com NLF e pesos instalados. Escolham a mesma sala, por padrão `HEAVY1`. O endpoint configurável oferece relay e P2P com fallback; sem TURN, algumas redes impedem conexão direta. O primeiro jogador é a autoridade da simulação. Apenas poses e estado do jogo seguem para o adversário. Perdas de snapshots são reparadas por blocos do histórico, inclusive após KO.

A música e os 37 clipes de Victor estão integrados. Som de impacto reduzido desliga zumbido e abafamento do KO. Créditos/proveniência em [CREDITS](../assets/boxing_audio/CREDITS.md). Audição humana das variantes e validação com duas pessoas em redes diferentes continuam pendentes.

Parecer do gauntlet: [9,18/10, com evidências e ressalvas](BOXING_GAUNTLET_REVIEW_2026-10-02.md). Relatório de implementação: [BOXING_IMPLEMENTATION_2026-10-02.md](BOXING_IMPLEMENTATION_2026-10-02.md). A disponibilidade jurídica do nome não foi verificada.

