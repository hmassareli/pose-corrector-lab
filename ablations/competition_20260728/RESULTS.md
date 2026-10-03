# RESULTADOS — competição noturna

Gerado por `ablations/finalize_report.py`  
Pasta: `C:/Users/Henrique/studies/3d augmented games using mocap/pose_corrector_lab/ablations/competition_20260728`

## Veredito rápido

**Time GPT** vence (gpt_multilag_best impr=0.9369 vs me 0.9127)

Punch score: **GPT** 0.4913 > me 0.4787

**Melhor overall (hand proximity / test):** `baseline_dropaccel_best`  
Checkpoint: `C:\Users\Henrique\studies\3d augmented games using mocap\pose_corrector_lab\runs\20260726_092251_gru_noaux_dropaccel_v1/checkpoints/best_hard.pt`

Baseline punch_score: 0.49348055589787293

## Ranking completo
| rank | name | team | hands↓ | vs base hard | test_hard↓ | test_impr% | elbow↓ | punch↑ |
|-----:|------|------|-------:|-------------:|-----------:|-----------:|-------:|-------:|
| 1 | baseline_dropaccel_best | baseline | 0.0772 | +0.00% | 194.7699 | 62.5352 | 13.8561 | 0.4935 |
| 2 | gpt_multilag_best | gpt | 0.0775 | +2.42% | 190.0567 | 63.4419 | 13.9369 | 0.4913 |
| 3 | me_seq_vel_z_bone_best | me | 0.1072 | -38.53% | 269.8114 | 48.1007 | 22.2619 | 0.4787 |
| 4 | me_seq_vel_z_best | me | 0.1084 | -34.86% | 262.674 | 49.4736 | 18.5538 | 0.4751 |
| 5 | gpt_seq_vel_best | gpt | 0.1095 | -37.60% | 268.0023 | 48.4487 | 18.755 | 0.4718 |
| 6 | hybrid_multilag_seq_vel_z_best | hybrid | 0.1102 | -37.55% | 267.9072 | 48.467 | 19.1086 | 0.4743 |
| 7 | hybrid_full_stack_best | hybrid | 0.1135 | -49.37% | 290.9234 | 44.0397 | 22.3108 | 0.4817 |
| 8 | gpt_seq_vel_dir_best | gpt | 0.1168 | -47.31% | 286.9065 | 44.8124 | 20.0133 | 0.4716 |

## Punch trajectory (jogo)
| name | punch↑ | peak_wrist_mm↓ | timing_frames↓ | dir_err↓ | return_mm↓ | idle_mm↓ |
|------|-------:|---------------:|---------------:|---------:|-----------:|---------:|
| baseline_dropaccel | 0.49348055589787293 | 96.69764264512203 | 0.6348993288590604 | 0.3809452983837526 | 61.65400838541533 | 894.2634015211029 |
| gpt_multilag | 0.4912739860959927 | 96.56323539684732 | 0.640268456375839 | 0.39050481098031503 | 59.654155116483366 | 892.245926873412 |
| me_seq_vel_z_bone | 0.4786951091706933 | 127.6033793859403 | 0.7033557046979866 | 0.42913362965742 | 73.41206123875494 | 899.4086128973795 |
| me_seq_vel_z | 0.475084063165629 | 129.6823885025728 | 0.6523489932885906 | 0.45837962483577854 | 77.34698451124875 | 899.4088211147242 |
| gpt_seq_vel | 0.47175583100996565 | 130.0686403415313 | 0.6597315436241611 | 0.46260248253512254 | 79.33613534294773 | 900.0408633258498 |
| hybrid_multilag_seq_vel_z | 0.4742812344921899 | 132.3899760433032 | 0.648993288590604 | 0.46252664626409096 | 78.82371037455862 | 898.3627665153057 |
| hybrid_full_stack | 0.4817016971903231 | 131.41544062953395 | 0.6677852348993288 | 0.4225234633341726 | 76.78937608756162 | 904.6926590215494 |
| gpt_seq_vel_dir | 0.47163556771888276 | 134.68774017157935 | 0.6624161073825503 | 0.4488721103081385 | 84.03922849409588 | 901.2784357606192 |

## Quem bateu o baseline?
- Ninguém bateu o baseline com folga (≥3% hard ou hands melhor).

## Melhor de cada time
- GPT: `gpt_multilag_best` hard=190.0567
- me: `me_seq_vel_z_bone_best` hard=269.8114
- hybrid: `hybrid_multilag_seq_vel_z_best` hard=267.9072

## Critério go (jogo)
- hard ↓ ≥ 3% vs baseline **e** easy sem regressão > 3% (já gated no treino)
- punch_score ↑ (pico / timing / direção / idle)
- ombros continuam corrigidos

## Próximo passo sugerido
1. Abrir o vencedor no Live viewer
2. Se hybrid ganhou, usar como candidato provisório ao jogo
3. Coletar dados da webcam real antes de crownear modelo final
