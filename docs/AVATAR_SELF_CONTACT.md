# Guarda e contato com o próprio rosto — 2 de outubro de 2026

> **Revisão posterior — 03/10/2026:** este documento descreve a primeira intervenção. O usuário depois rejeitou a faixa de aproximação suave; foram relatados punhos dobrados e separação da guarda. O assistente reconheceu a inadequação de preservar a mão no mundo após reposicionar o antebraço. Os testes abaixo não certificam fidelidade de todos os gestos. Consulte E3 na [coletânea](COLETANEA_PEDIDOS_ENTREGAS_E_ERROS_2026-10-03.md) e o código atual para a versão vigente.

Correção solicitada após perceber luvas atravessando o rosto ao fechar a guarda. A orientação da cabeça/pescoço foi preservada. Não foi aplicado um deslocamento global da profundidade dos punhos.

## Evidência

Em 30 poses sintéticas por avatar, combinando profundidades de guarda e rotações faciais, vértices da luva entravam no envelope da cabeça: aproximadamente 5,6 cm no Prism e 2,4 cm no Titan/boxeador. O Fighter Web não apresentou penetração nessas mesmas poses; testes adicionais colocando a mão dentro da cabeça e cruzando a região craniana exercitam sua proteção.

Essas medidas são contra um volume convexo conservador derivado da malha nativa, não uma interseção triângulo a triângulo nem uma medida de uma nova sessão humana. O envelope simplificado contém os pontos cranianos amostrados na calibração; as diferenças de proporção entre os três assets são mantidas.

## Implementação

- `viewer/avatar_self_contact.js`: amostra a geometria skinned, após a escala/calibração final. Corrige a referência `bindMatrixInverse` como faz o renderizador antes de medir, evitando tratar os assets como modelos de poucos milímetros.
- O crânio recebe um envelope convexo simplificado a partir de pontos de suporte. A luva usa seu suporte nativo na direção do contato; o raio esférico serve para rejeição rápida de objetos afastados, não para manter a luva afastada do rosto em todas as direções.
- A faixa espacial de aproximação suave tem 20 mm; fora dela, o movimento é livre. Dentro dela, diminui a resposta para dentro da face, com transição contínua. A restrição rígida mantém 4 mm de margem no contato, mais 1 mm de margem no suporte da luva.
- A correção desloca o alvo do punho por IK de dois ossos, distribuindo o movimento entre braço e cotovelo. Preserva a orientação mundial da palma, a cabeça e os comprimentos dos segmentos. Não há filtro temporal adicional nem espera ao retirar a mão.
- A detecção entre frames impede atravessar toda a cabeça com um salto rápido de posição. Remove o componente para dentro do contato e permite deslocamento tangencial; o estado é reiniciado após pausas longas, recalibração ou troca de fonte de tracking.
- No jogo, atua nos dois lutadores depois das reações, apoio dos pés e retenção de golpes na guarda. Usa os modelos existentes; nenhum proxy visual ou nova luva é acrescentado.

É uma restrição física cinemática de não penetração, adequada à pose comandada pela webcam. Não é uma simulação de cabeça e braços livres por ragdoll. Os dados NLF e a suavização existente continuam sendo a entrada do retarget; o contato ajusta sua apresentação final no jogo.

## Validação

`scripts/test_avatar_self_contact.py`: **39 verificações aprovadas**, 13 por modelo. Verifica escala nativa, contato sem penetração, cabeça intacta, orientação da palma, comprimentos, continuidade da aproximação, guarda parada sem deriva, retirada imediata, travessia rápida e casos adversos dentro do crânio. Os 30 casos de guarda por avatar passam com margem mínima aproximada de 4 mm no volume físico. As palmas preservam sua orientação com diferença numérica abaixo de 0,00001°.

A restrição custou aproximadamente 0,05–0,25 ms por chamada no cenário isolado, com 100 chamadas sobre uma postura de contato. Isso não é FPS do jogo nem ganho da inferência. Testes de combate e integração de cabeça/primeira/terceira pessoa também foram executados; a integração verifica a aplicação real do contato e seu reset pelo botão Calibrar.

Relatório e capturas antes/depois: [experiments/avatar_self_contact](../experiments/avatar_self_contact/). A validação humana ainda deve observar guarda fechada, inclinação da cabeça com mãos próximas e saída da guarda para jab/hook. O ajuste atua apenas no contato com a própria cabeça; não implementa contato com todo o corpo, dedos individuais ou entre as duas luvas.
