"""Prepara pontos reais existentes para auditoria; nao executa inferencia."""
import json
import sys
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
LAB = HERE.parents[1]
sys.path.insert(0, str(LAB / 'src'))
from pose_lab.skeleton import smplx55_to_lab, smplx55_avatar_aux_json

d = np.load(LAB / 'experiments/nlf_fit_webcam1/fit_smplx.npz')
x = d['x55'].astype(float) / 1000
fit = d['fit_joints'].astype(float) / 1000
names = [str(n) for n in d['smplx55_names']]
idx = {n:i for i,n in enumerate(names)}
valid = d['ok'].astype(bool)
frames = []
for t in range(len(x)):
    j = x[t] - x[t,0]
    frames.append(dict(joints=smplx55_to_lab(j).tolist(),aux_smpl=smplx55_avatar_aux_json(j),ok=bool(valid[t])))
(HERE / 'raw_x55_frames.json').write_text(json.dumps(frames),encoding='utf-8')

def unit(v):
    return v / np.maximum(np.linalg.norm(v,axis=-1,keepdims=True),1e-12)

stats = {'frames':len(x),'fit_ok_frames':int(valid.sum()),'input_file':'experiments/nlf_fit_webcam1/fit_smplx.npz'}
for label,j in [('raw_x55',x),('fit_joints',fit)]:
    stats[label]={}
    for side in ['left','right']:
        across=j[:,idx[side+'_pinky1']]-j[:,idx[side+'_index1']]
        span=np.linalg.norm(across,axis=-1)
        forward=(j[:,idx[side+'_pinky1']]+j[:,idx[side+'_index1']])/2-j[:,idx[side+'_wrist']]
        normal=unit(np.cross(unit(forward),unit(across)))
        jumps=np.degrees(np.arccos(np.clip((normal[1:]*normal[:-1]).sum(-1),-1,1)))
        mask=valid[1:]&valid[:-1]
        jumps=jumps[mask]
        stats[label][side]={'finger_span_m_p05_p50_p95':np.percentile(span[valid],[5,50,95]).tolist(),
                            'palm_normal_jump_deg_p50_p95_max':[float(np.percentile(jumps,50)),float(np.percentile(jumps,95)),float(jumps.max())],
                            'jumps_gt90':int((jumps>90).sum())}
(HERE/'input_sequence_results.json').write_text(json.dumps(stats,indent=2),encoding='utf-8')
print(json.dumps(stats,indent=2))
