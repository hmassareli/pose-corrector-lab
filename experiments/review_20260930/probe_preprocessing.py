"""Reproducoes das funcoes Python atuais, sem alterar treino/modelos."""
import ast
import json
import sys
from collections import Counter
from pathlib import Path
import numpy as np
import torch

HERE=Path(__file__).resolve().parent
LAB=HERE.parents[1]
sys.path.insert(0,str(LAB/'src'))
from pose_lab.align import body_frame_from_pose,to_body_frame,from_body_frame
from pose_lab.skeleton import TARGET_IDX,N_TARGETS,DELTA_DIM
from pose_lab.metrics import hard_mask

def read_function(file,name,scope):
    tree=ast.parse(file.read_text(encoding='utf-8-sig'))
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
    node.decorator_list=[]
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(file),'exec'),scope)
    return scope[name]

env=dict(np=np,torch=torch,TARGET_IDX=TARGET_IDX,N_TARGETS=N_TARGETS,DELTA_DIM=DELTA_DIM,
         body_frame_from_pose=body_frame_from_pose,to_body_frame=to_body_frame,from_body_frame=from_body_frame,
         hard_mask=hard_mask,take_delta_last=lambda x:x,DataLoader=object)
apply_delta=read_function(LAB/'scripts/export_corrected.py','apply_delta',env)
eval_delta=read_function(LAB/'scripts/train.py','eval_delta',env)
pose=np.array([[0,1,0],[-.1,1,0],[.1,1,0],[-.1,.55,0],[.1,.55,0],[-.1,.1,0],[.1,.1,0],
               [0,1.25,0],[-.2,1.5,0],[.2,1.5,0],[-.45,1.5,0],[.45,1.5,0],[-.45,1.75,.1],[.45,1.75,.1],[0,1.5,0],[0,1.8,0]],float)
report={}
for label,p in [('normal',pose.copy()),('coincident_shoulders',pose.copy())]:
    if label=='coincident_shoulders':p[8]=p[9]=[0,1.5,0]
    R,scale,origin=body_frame_from_pose(p)
    out=apply_delta(p,np.zeros(DELTA_DIM))
    report[label]={'det_R':float(np.linalg.det(R)),'orthonormal_error':float(np.linalg.norm(R@R.T-np.eye(3))),
                   'max_target_displacement_with_zero_delta_m':float(np.linalg.norm(out[TARGET_IDX]-p[TARGET_IDX],axis=-1).max())}

class ZeroModel:
    def eval(self):pass
    def __call__(self,x):return {'delta':torch.zeros((len(x),DELTA_DIM))}
true=torch.zeros((2,DELTA_DIM));true.reshape(2,N_TARGETS,3)[:,:,0]=.25
metrics=eval_delta(ZeroModel(),[{'x':torch.zeros((2,15,113)),'y':true,'conf':torch.ones((2,N_TARGETS))}],torch.device('cpu'))
report['metric_units']={'shoulder_width_m':.4,'bodyframe_error':.25,'expected_physical_error_mm':100,
                        'reported_mpjpe_overall_mm':metrics['mpjpe_overall_mm']}
(HERE/'preprocessing_probe_results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))

inventory=[]
for folder in ['src/pose_lab','scripts','viewer','docs','configs']:
    for p in sorted((LAB/folder).rglob('*')):
        if not p.is_file() or p.suffix not in ['.py','.js','.html','.md','.yaml','.toml']:continue
        text=p.read_text(encoding='utf-8-sig',errors='replace')
        row={'path':p.relative_to(LAB).as_posix(),'lines':len(text.splitlines()),'bytes':p.stat().st_size}
        if p.suffix=='.py':
            try:
                tree=ast.parse(text);row['docstring']=ast.get_docstring(tree);row['top_level_functions']=[n.name for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef,ast.AsyncFunctionDef))]
            except SyntaxError as e:row['parse_error']=str(e)
        inventory.append(row)
(HERE/'source_inventory.json').write_text(json.dumps(inventory,indent=2,ensure_ascii=False),encoding='utf-8')
print('Inventario:',len(inventory),'arquivos;',sum(r['lines'] for r in inventory),'linhas; erros de AST:',sum('parse_error' in r for r in inventory))
