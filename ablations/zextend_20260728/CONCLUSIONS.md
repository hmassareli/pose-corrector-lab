# Competition conclusions

Folder: `ablations/zextend_20260728`

## Ranking (best ckpts)
| rank | name | team | hand_prox_mae | test_hard | test_impr% | elbow | punch_score |
|-----:|------|------|--------------:|----------:|-----------:|------:|------------:|
| 1 | lastpos_vel003_zextend_best | baseline | 0.0746 | 188.7005 | 63.7027 | 11.7358 | 0.4977 |

## Punch trajectory (game-oriented)
- **lastpos_vel003_zextend**: punch_score=0.49773905698020227, peak_wrist_C=88.66463662754694, timing_C=0.6604026845637584, dir_C=0.3646447243563982, idle_mm=893.8669328331088

## Winner (by hand proximity / test hard)
`C:\Users\Henrique\studies\3d augmented games using mocap\pose_corrector_lab\runs\20260728_222624_abl2_lastpos_vel003_zextend/checkpoints/best_hard.pt`

## Go criteria reminder
- Prefer ≥3% hard improvement vs baseline without easy regression >3%
- Prefer higher punch_score (peak / timing / direction / idle)
- Shoulders remain corrected in all candidates
