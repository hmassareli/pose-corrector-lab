# Checklist operacional do lab

## Dia 0 — estrutura
- [x] Pastas data/ docs/ configs/ scripts/ src/ viewer/ runs/
- [x] Docs científicos (FPS 30, features, eval, logging)
- [x] Viewer HTML
- [x] Wrappers GVHMR

## Dia 1 — teacher
- [x] Instalar GVHMR + checkpoints SMPL do upstream
- [x] Executar teacher nos vídeos atuais
- [x] Exportar joints e alinhar com MediaPipe
- [ ] Revisar/expandir `qa.json` para descartar teacher duvidoso

## Dia 2 — MediaPipe + pair
- [x] Implementar `run_mediapipe.py`
- [x] `build_dataset.py` @ 30 Hz
- [x] Criar split atual por vídeo/shot
- [ ] Criar identidades humanas globais e refazer split por pessoa + sessão
- [ ] Coletar hold-out na webcam/setup real do jogo

## Dia 3 — treino baseline
- [x] GRU causal em `src/pose_lab/models.py` (TCN não implementada)
- [x] `train.py` + JSONL/TensorBoard
- [x] `eval.py` hard/easy vs MediaPipe
- [ ] Implementar baseline EMA na avaliação principal
- [ ] Implementar métricas temporais (direção, timing do pico e jitter) no relatório principal
- [ ] Implementar loss temporal real; `w_smooth` atual é apenas magnitude e foi 0.0 nos treinos recentes
- [ ] Implementar ou remover `w_bone`; atualmente o config não tem efeito

## Go/No-go
Ver critérios em `docs/04_evaluation.md`.
