# BOM DIA ☕🔥

## Abre nesta ordem
1. **`RESULTS.md`** — veredito GPT vs me + híbridos + punch scores  
2. **`MORNING_SUMMARY.json`** — one-liner  
3. **`overnight_status.json`** — deve estar `"phase": "done"`  
4. **`CONCLUSIONS.md`** / **`leaderboard.tsv`** — detalhe

## O que rolou de madrugada
- Competição wave-1 (GPT vs me) + wave-2 (híbridos)
- `gpt_multilag` foi interrompido na época ~52 e **salvado** (best @ época 45, val≈217.9)
- Runner endurecido: `run_overnight_hard.py` (resume + salvage + finalize)
- Benchmark de soco: pico / timing / direção / idle / jitter

Se `phase` ≠ `done`, ainda está na fila — olha `logs/train_*.log`.
