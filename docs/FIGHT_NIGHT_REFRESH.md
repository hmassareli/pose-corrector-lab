# Fight-night refresh

## Entrega

- A arena, plateia, ringue, HUD, lobby e diálogos agora usam grafite, vermelho de canto, azul elétrico e dourado quente. O material dos avatares saiu do `MeshToonMaterial` e foi para iluminação contínua `MeshStandardMaterial`; contornos de hull foram removidos.
- Impactos usam lotes de partículas 3D com buffers fixos: faíscas, névoa curta e gotas. O texto `POW` foi removido do impacto.
- O rastro dos punhos é uma fita orientada à câmera, com largura de 0,26 m no centro da amostra e fade temporal de 0,2 s. O rastro reinicia quando a mão teleporta entre amostras.
- Durante um adversário atordoado, velocidade de mão entre 2,4 e 14 m/s cria uma esteira de faíscas e fumaça leve. O emissor é limitado por tempo e por pool.
- Os ajustes ganharam `Alto`, `Equilibrado` e `Desempenho`. O modo baixo reduz pixel ratio, desliga sombras, reduz a plateia instanciada e esconde cones de luz; a escolha fica salva em `cornerGraphics`.

## Evidência local

`tests/test_boxing_fight_night.py` valida lobby, settings, arena, primeira pessoa, venue alternativo, resultado, responsividade, gates de velocidade/atordoamento, expiração de partículas, largura do rastro e ausência de crescimento de recursos GPU. O resultado atual está em `experiments/fight_night_refresh/after/validation.json`.

Na captura de revisão, o renderizador ficou em 62–67 chamadas e aproximadamente 16,7 ms por quadro neste PC. Isso é uma medição deste hardware e desta cena, não uma promessa para máquinas fracas. O maior custo observado é o avatar Prism: aproximadamente 1,49 milhão de triângulos e um GLB de 73,6 MB; o segundo avatar tem aproximadamente 295 mil triângulos e 49,3 MB.

## Próximos ganhos para PCs menores

1. Criar variantes de avatar com 300–500 mil triângulos para Alto e 80–150 mil para Desempenho. O ganho mais importante está nos personagens, não na plateia.
2. Rodar `gltf-transform` com simplificação medida, Meshopt/Draco e texturas KTX2/WebP. KTX2 mantém a textura comprimida na GPU; medir qualidade de pele, luvas e tatuagens depois da conversão.
3. Adicionar LOD por distância: personagem próximo em alta resolução, personagem distante em malha reduzida; plateia pode permanecer instanciada.
4. Manter WebGL como caminho compatível. WebGPU pode ser uma opção futura para o renderizador e inferência, mas o jogo atual usa `onBeforeCompile` no avatar; esse mecanismo não é suportado pelo `WebGPURenderer` e exigiria migrar o shader de flash/bruise para TSL/NodeMaterial.
5. Para NLF, medir WebGPU/WebNN contra o backend atual no mesmo hardware e com carga do jogo. O caminho correto é escolher por calibração, limitar frames em voo e evitar cópias extras; não presumir ganho só por ativar WebGPU.
6. Instrumentar idade da pose exibida, p50/p95 do frame, uso de CPU/GPU, VRAM e drops. A câmera pode estar limitada a 30 FPS, então a meta deve ser menor latência e folga, não apenas mais FPS.

## Limite conhecido da validação

O teste de combate existente ainda tem uma fixture que espera `chin` e recebe `clean` no golpe sintético; ele não apresentou erro de JavaScript e os checks de dano, bloqueio, journal e resultado continuam passando. Isso deve ser corrigido no fixture/limiar de colisão antes de usar esse teste como gate de regressão visual.
