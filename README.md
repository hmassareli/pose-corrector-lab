# Pose Corrector Lab

Laboratório de IA para a **rede corretora de pose de boxe** (MediaPipe → residual → pose corrigida), com **GVHMR** como teacher offline.

## HEAVY HANDS

Jogo de boxe com webcam, rastreamento NLF-S e os três avatares originais. Abra `http://127.0.0.1:8780/static/boxing.html` depois de iniciar `python scripts/serve_lab.py --host 127.0.0.1 --port 8780`. Ligue a webcam no menu e aguarde a calibração; o treino é liberado com o rastreamento estável. Menus em português/inglês; HUD de luta em inglês. A sala padrão é `HEAVY1`.

Força estimada em newtons a partir dos movimentos em metros e da massa configurada; dano, PEAK persistente e estatísticas usam colisões renderizadas. A opção de som reduzido desativa zumbido e abafamento do nocaute. Créditos dos sons em `assets/boxing_audio/CREDITS.md`. Plano e evidências em `docs/BOXING_FIX_PLAN_2026-10-02.md` e `docs/BOXING_GAUNTLET_REVIEW_2026-10-02.md`.

A disponibilidade jurídica do nome HEAVY HANDS ainda não foi verificada.

## Inferência Live com webcam

O repositório inclui os checkpoints necessários para testar o corretor diretamente no navegador. O vídeo da webcam fica local: o navegador extrai a pose com MediaPipe e envia somente os landmarks para o servidor Python local.

### Requisitos

- Python 3.10 ou mais recente.
- Webcam.
- Conexão com a internet na primeira execução, para o navegador baixar o MediaPipe.
- GPU NVIDIA é opcional; a inferência também funciona em CPU.

### Instalação

No Windows PowerShell:

```powershell
git clone https://github.com/hmassareli/pose-corrector-lab.git
cd pose-corrector-lab
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
```

No Linux, macOS ou WSL, troque a ativação do ambiente por:

```bash
source .venv/bin/activate
```

### Executar

```bash
python scripts/serve_lab.py --warmup
```

Abra [http://127.0.0.1:8780/live](http://127.0.0.1:8780/live), permita o acesso à webcam e clique em **Iniciar câmera**. Selecione **Corrigido** para aplicar a rede ou **Raw MP** para ver somente o MediaPipe.

O primeiro carregamento pode demorar enquanto o PyTorch abre o checkpoint e o navegador baixa o modelo do MediaPipe. O terminal deve informar `Checkpoints: 2 under runs/`.

### Checkpoints incluídos

| Checkpoint | Uso recomendado |
|---|---|
| `20260726_092251_gru_noaux_dropaccel_v1/best_hard` | Modelo geral e opção padrão. Melhor resultado no teste oficial: 194,8 mm no subconjunto hard. |
| `20260727_134842_gru_noaux_dropaccel_win_ft/best_hard` | Fine-tuning experimental para o vídeo WIN. Melhor nesse domínio específico, mas ligeiramente pior no teste geral. |

Para confirmar que a instalação e os arquivos estão corretos:

```bash
python scripts/smoke_test.py
python -c "import sys; sys.path.insert(0, 'scripts'); import serve_lab; print([c['id'] for c in serve_lab.discover_checkpoints(force=True)])"
```

O Live não precisa dos vídeos, do dataset, do GVHMR nem dos demais checkpoints de treinamento. Esses artefatos são deliberadamente excluídos do repositório público.

## Layout

```
pose_corrector_lab/
├── README.md                 ← você está aqui
├── docs/                     ← protocolo científico (dataset, features, eval)
├── configs/                  ← hiperparâmetros e paths
├── data/
│   ├── raw_videos/           ← vídeos originais (input humano)
│   ├── input/                ← fila de inferência do teacher (symlink ou cópias)
│   ├── teacher/              ← saídas GVHMR (poses GT)
│   ├── mediapipe/            ← poses MediaPipe alinhadas
│   ├── paired/               ← samples prontos pro treino (janelas)
│   └── splits/               ← train/val/test por pessoa/vídeo
├── external/                 ← clones (GVHMR) — gitignored parcialmente
├── scripts/                  ← CLI do lab
├── src/pose_lab/             ← código Python do experimento
├── viewer/                   ← visualizador HTML (vídeo + bone 3D)
├── runs/                     ← logs, checkpoints, métricas
└── notebooks/                ← exploração ad-hoc
```

## Quick start

```bash
cd pose_corrector_lab
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -e .

# Unified lab (offline multi-source + live webcam) — preferred
python scripts/serve_lab.py
# → http://127.0.0.1:8780/       Offline: MediaPipe / Teacher / Teacher aligned / Corrector
# → http://127.0.0.1:8780/live  Webcam + MediaPipe WASM + corrector (checkpoint dropdown)

# Legacy single-source viewer (one process per source)
python scripts/serve_viewer.py --source mediapipe --port 8770
```

### Pose Lab unificado

Um comando sobe o site inteiro na porta **8780**:

| Página | O que faz |
|--------|-----------|
| `/` | Clips offline com botões de fonte (sem trocar de porta) |
| `/live` | Webcam → MediaPipe Pose (browser) → skeleton 3D; opcional corrector via `/api/correct` |

Checkpoints descobertos em `runs/*/checkpoints/{best_hard,last}.pt` aparecem no dropdown do Live. O checkpoint recomendado atualmente é `gru_noaux_dropaccel_v1/best_hard`. O fine-tuning `gru_noaux_dropaccel_win_ft` melhora o clip WIN usado no treino, mas piora levemente o teste oficial; portanto, não substitui o baseline como modelo geral.

**Limitações do Live:** world landmarks do MediaPipe no browser são aproximados (Z fraco); o corrector roda no Python com janela T=15 — FPS modesto em CPU, suficiente para demo. Use **Raw MP** para só o skeleton da webcam; **Corrigido** + **Sombra MP** para ver o delta.

**Limitações da evidência atual:** os 269 clips são recortes/rastros derivados de poucos vídeos-fonte, não 269 pessoas independentes. A validação vem do mesmo vídeo-fonte `burn_500_shots` predominante no treino; o teste usa outros dois vídeos, mas ainda não é um hold-out amplo de jogadores e sessões reais do jogo. Veja `docs/04_evaluation.md`.

```bash
# Pré-carregar o checkpoint preferido na subida
python scripts/serve_lab.py --warmup --source corrected

# Viewer legado / demo sintético
python scripts/make_demo_clip.py
python scripts/serve_viewer.py --clip demo_jab
# → http://127.0.0.1:8765/?clip=demo_jab

# Teacher real
python scripts/setup_gvhmr.py
# …siga o README do external/GVHMR (SMPL + checkpoints)…
# copie vídeos para data/input/
python scripts/run_teacher.py --input data/input --out data/teacher --static-camera
python scripts/serve_viewer.py --clip <clip_id>
```

Smoke test dos módulos core: `python scripts/smoke_test.py`

| Doc | Conteúdo |
|-----|----------|
| [docs/00_overview.md](docs/00_overview.md) | visão do experimento |
| [docs/01_teacher_gvhmr.md](docs/01_teacher_gvhmr.md) | setup + inferência teacher |
| [docs/02_dataset_and_features.md](docs/02_dataset_and_features.md) | FPS 30, features, samples |
| [docs/03_training.md](docs/03_training.md) | losses, currículo, logging |
| [docs/04_evaluation.md](docs/04_evaluation.md) | hard/easy, go/no-go |
| [docs/05_checklist.md](docs/05_checklist.md) | checklist operacional |
