# Competition conclusions

Folder: `C:/Users/Henrique/studies/3d augmented games using mocap/pose_corrector_lab/ablations/phase2_20260728`

## Ranking (best ckpts)
| rank | name | team | hand_prox_mae | test_hard | test_impr% | elbow | punch_score |
|-----:|------|------|--------------:|----------:|-----------:|------:|------------:|
| 1 | lastpos_vel003_best | baseline | 0.0758 | 187.4433 | 63.9446 | 12.7108 | 0.5043 |
| 2 | arch_hidden192_best | baseline | 0.0767 | 189.4163 | 63.565 | 13.8711 | 0.4809 |
| 3 | multilag_separate_best | baseline | 0.0769 | 192.7027 | 62.9329 | 13.5588 | 0.4826 |
| 4 | lastpos_vel005_best | baseline | 0.0772 | 188.3285 | 63.7743 | 13.3531 | 0.5029 |
| 5 | baseline_seed42_best | baseline | 0.0772 | 194.7699 | 62.5352 | 13.8561 | 0.4935 |
| 6 | arch_T24_best | baseline | 0.0773 | 190.9639 | 63.3128 | 12.9171 | 0.4943 |
| 7 | multilag_seed42_best | baseline | 0.0775 | 190.0567 | 63.4419 | 13.9369 | 0.4913 |
| 8 | baseline_seed2026_best | baseline | 0.0779 | 189.8169 | 63.488 | 12.8351 | 0.4845 |
| 9 | arch_layers1_best | baseline | 0.078 | 201.7579 | 61.1911 | 12.6879 | 0.4727 |
| 10 | multilag_seed1337_best | baseline | 0.0781 | 189.6288 | 63.5242 | 13.8654 | 0.4801 |
| 11 | arch_T9_best | baseline | 0.0782 | 192.7034 | 62.9241 | 13.5509 | 0.4781 |
| 12 | multilag_seed2026_best | baseline | 0.0784 | 191.8887 | 63.0895 | 13.1367 | 0.4823 |
| 13 | baseline_seed1337_best | baseline | 0.0789 | 191.6918 | 63.1273 | 14.5125 | 0.4793 |
| 14 | lastpos_vel003_tiera_best | baseline | 0.0796 | 193.2361 | 62.8303 | 13.571 | 0.5027 |
| 15 | seq_only_best | baseline | 0.0802 | 198.1141 | 61.892 | 14.2414 | 0.4799 |
| 16 | lastpos_vel010_best | baseline | 0.0839 | 206.5536 | 60.2686 | 15.0612 | 0.5114 |
| 17 | lastpos_vel005_dir005_best | baseline | 0.0842 | 202.8507 | 60.9809 | 14.9002 | 0.5137 |

## Punch trajectory (game-oriented)
- **lastpos_vel003**: punch_score=0.5043141906026818, peak_wrist_C=91.90031920035112, timing_C=0.6214765100671141, dir_C=0.3633936620080505, idle_mm=893.1375641492898
- **arch_hidden192**: punch_score=0.48093081630993934, peak_wrist_C=94.51877347503479, timing_C=0.6691275167785234, dir_C=0.42217190274232663, idle_mm=893.6216461747534
- **multilag_separate**: punch_score=0.4826448651059733, peak_wrist_C=92.90126521472197, timing_C=0.661744966442953, dir_C=0.413205337681673, idle_mm=894.0339029425329
- **lastpos_vel005**: punch_score=0.5029461282315464, peak_wrist_C=95.42271089970697, timing_C=0.6496644295302013, dir_C=0.35593867714822497, idle_mm=893.1343434001586
- **baseline_seed42**: punch_score=0.49348055589787293, peak_wrist_C=96.69764264512203, timing_C=0.6348993288590604, dir_C=0.3809452983837526, idle_mm=894.2634015211029
- **arch_T24**: punch_score=0.4942841437560511, peak_wrist_C=91.9086319965217, timing_C=0.6456375838926175, dir_C=0.3759262121083728, idle_mm=891.1359207303955
- **multilag_seed42**: punch_score=0.4912739860959927, peak_wrist_C=96.56323539684732, timing_C=0.640268456375839, dir_C=0.39050481098031503, idle_mm=892.245926873412
- **baseline_seed2026**: punch_score=0.48446848049616975, peak_wrist_C=94.56439685715016, timing_C=0.6671140939597315, dir_C=0.4007802302891431, idle_mm=894.085055098034
- **arch_layers1**: punch_score=0.4726673091958547, peak_wrist_C=93.97205605790732, timing_C=0.6825503355704698, dir_C=0.43491476588047995, idle_mm=896.1909072671679
- **multilag_seed1337**: punch_score=0.4800897461410632, peak_wrist_C=97.40739181406155, timing_C=0.6550335570469799, dir_C=0.4338055145878619, idle_mm=892.8477060391893
- **arch_T9**: punch_score=0.4780653669411045, peak_wrist_C=99.34648212468306, timing_C=0.648993288590604, dir_C=0.43806207318217355, idle_mm=893.2739425687784
- **multilag_seed2026**: punch_score=0.4822965696163775, peak_wrist_C=95.59794820819934, timing_C=0.687248322147651, dir_C=0.39817759613746245, idle_mm=893.9742526609022
- **baseline_seed1337**: punch_score=0.47927110484057933, peak_wrist_C=99.01462971993801, timing_C=0.6610738255033557, dir_C=0.43281222365351474, idle_mm=893.0739414347196
- **lastpos_vel003_tiera**: punch_score=0.5026812600045676, peak_wrist_C=97.98187480736496, timing_C=0.62751677852349, dir_C=0.3642407785428977, idle_mm=894.8331249182069
- **seq_only**: punch_score=0.4798528180830361, peak_wrist_C=100.1579765422016, timing_C=0.7033557046979866, dir_C=0.394162019275305, idle_mm=893.8082139853409
- **lastpos_vel010**: punch_score=0.5113624763893639, peak_wrist_C=105.08975839132778, timing_C=0.6053691275167785, dir_C=0.34587601881485724, idle_mm=894.9599444271037
- **lastpos_vel005_dir005**: punch_score=0.5136593819115409, peak_wrist_C=103.59648036185177, timing_C=0.5912751677852349, dir_C=0.33701224226126014, idle_mm=893.8622180379214

## Winner (by hand proximity / test hard)
`C:\Users\Henrique\studies\3d augmented games using mocap\pose_corrector_lab\runs\20260728_151848_abl2_lastpos_vel003/checkpoints/best_hard.pt`

## Go criteria reminder
- Prefer ≥3% hard improvement vs baseline without easy regression >3%
- Prefer higher punch_score (peak / timing / direction / idle)
- Shoulders remain corrected in all candidates
