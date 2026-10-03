# Competition conclusions

Folder: `C:/Users/Henrique/studies/3d augmented games using mocap/pose_corrector_lab/ablations/competition_20260728`

## Ranking (best ckpts)
| rank | name | team | hand_prox_mae | test_hard | test_impr% | elbow | punch_score |
|-----:|------|------|--------------:|----------:|-----------:|------:|------------:|
| 1 | baseline_dropaccel_best | baseline | 0.0772 | 194.7699 | 62.5352 | 13.8561 | 0.4935 |
| 2 | gpt_multilag_best | gpt | 0.0775 | 190.0567 | 63.4419 | 13.9369 | 0.4913 |
| 3 | me_seq_vel_z_bone_best | me | 0.1072 | 269.8114 | 48.1007 | 22.2619 | 0.4787 |
| 4 | me_seq_vel_z_best | me | 0.1084 | 262.674 | 49.4736 | 18.5538 | 0.4751 |
| 5 | gpt_seq_vel_best | gpt | 0.1095 | 268.0023 | 48.4487 | 18.755 | 0.4718 |
| 6 | hybrid_multilag_seq_vel_z_best | baseline | 0.1102 | 267.9072 | 48.467 | 19.1086 | 0.4743 |
| 7 | hybrid_full_stack_best | baseline | 0.1135 | 290.9234 | 44.0397 | 22.3108 | 0.4817 |
| 8 | gpt_seq_vel_dir_best | gpt | 0.1168 | 286.9065 | 44.8124 | 20.0133 | 0.4716 |

## Punch trajectory (game-oriented)
- **baseline_dropaccel**: punch_score=0.49348055589787293, peak_wrist_C=96.69764264512203, timing_C=0.6348993288590604, dir_C=0.3809452983837526, idle_mm=894.2634015211029
- **gpt_multilag**: punch_score=0.4912739860959927, peak_wrist_C=96.56323539684732, timing_C=0.640268456375839, dir_C=0.39050481098031503, idle_mm=892.245926873412
- **me_seq_vel_z_bone**: punch_score=0.4786951091706933, peak_wrist_C=127.6033793859403, timing_C=0.7033557046979866, dir_C=0.42913362965742, idle_mm=899.4086128973795
- **me_seq_vel_z**: punch_score=0.475084063165629, peak_wrist_C=129.6823885025728, timing_C=0.6523489932885906, dir_C=0.45837962483577854, idle_mm=899.4088211147242
- **gpt_seq_vel**: punch_score=0.47175583100996565, peak_wrist_C=130.0686403415313, timing_C=0.6597315436241611, dir_C=0.46260248253512254, idle_mm=900.0408633258498
- **hybrid_multilag_seq_vel_z**: punch_score=0.4742812344921899, peak_wrist_C=132.3899760433032, timing_C=0.648993288590604, dir_C=0.46252664626409096, idle_mm=898.3627665153057
- **hybrid_full_stack**: punch_score=0.4817016971903231, peak_wrist_C=131.41544062953395, timing_C=0.6677852348993288, dir_C=0.4225234633341726, idle_mm=904.6926590215494
- **gpt_seq_vel_dir**: punch_score=0.47163556771888276, peak_wrist_C=134.68774017157935, timing_C=0.6624161073825503, dir_C=0.4488721103081385, idle_mm=901.2784357606192

## Winner (by hand proximity / test hard)
`C:\Users\Henrique\studies\3d augmented games using mocap\pose_corrector_lab\runs\20260726_092251_gru_noaux_dropaccel_v1/checkpoints/best_hard.pt`

## Go criteria reminder
- Prefer ≥3% hard improvement vs baseline without easy regression >3%
- Prefer higher punch_score (peak / timing / direction / idle)
- Shoulders remain corrected in all candidates
