"""Compara classes visuais com NLF bruto e geometria independente do avatar."""
from pathlib import Path
import json, numpy as np
from collections import Counter

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'experiments/review_20260930/palm_live'
LABELS=ROOT/'src/benchmark_images/palm_orientation/labels.json'

def normal(w,i,p,side):
 w,i,p=map(lambda v:np.array(v,float),(w,i,p))
 a=i-w; b=p-w; cross=np.cross(a,b)
 denom=np.linalg.norm(a)*np.linalg.norm(b)
 quality=np.linalg.norm(cross)/denom if denom>1e-12 else 0
 if quality<.05: return None,quality
 return cross/np.linalg.norm(cross)*(-1 if side=='left' else 1),quality

def classify(n,side):
 if n is None: return 'degenerada'
 x=1 if side=='right' else -1
 axes={'cima':[0,1,0],'baixo':[0,-1,0], 'lado_interno':[x,0,0],
       'lado_externo':[-x,0,0],'camera':[0,0,1],'longe_da_camera':[0,0,-1]}
 return max(axes,key=lambda label:np.dot(n,axes[label]))

def measure(fs,side,kind):
 normals=[];qualities=[];classes=[]
 for f in fs:
  if kind=='nlf':
   names=f['data']['smplx55_names']; pts=np.array(f['data']['smplx55'])*[1,-1,-1]
   get=lambda part:pts[names.index(side+'_'+part)]
   n,q=normal(get('wrist'),get('index1'),get('pinky1'),side)
  else:
   g=f.get('handGeometry',{})
   keys=[side+'_'+part for part in ['hand','handindex1','handpinky1']]
   if any(k not in g for k in keys): continue
   n,q=normal(*(g[k] for k in keys),side)
  classes.append(classify(n,side));qualities.append(q)
  if n is not None: normals.append(n)
 if not classes: return {'majority':'indisponivel','samples':0}
 return {'majority':Counter(classes).most_common(1)[0][0], 'class_counts':dict(Counter(classes)),
  'samples':len(classes),'median_normal':np.median(normals,axis=0).round(4).tolist() if normals else None,
  'median_sin_knuckle_angle':round(float(np.median(qualities)),4)}

def main():
 labels=json.loads(LABELS.read_text(encoding='utf-8'))
 for folder in OUT.iterdir():
  if not (folder/'summary.json').exists(): continue
  summary=json.loads((folder/'summary.json').read_text(encoding='utf-8'))
  frames=json.loads((folder/'frames.json').read_text(encoding='utf-8'))
  results=[]
  for i,capture in enumerate(summary['captures']):
   sample=next(s for s in labels['samples'] if s['image']==capture['image'])
   start=summary.get('capture_cycle_start',0)+i*6
   fs=[f for f in frames if start+2<=f['videoTime']<=start+5.8]
   for side,label in sample['hands'].items():
    if not label.get('evaluate'): continue
    # Live selfie mirror flips X and swaps anatomical L/R. Raw NLF remains unmirrored.
    avatar_side='left' if side=='right' else 'right'
    raw=measure(fs,side,'nlf'); avatar=measure(fs,avatar_side,'avatar')
    results.append({'image':sample['image'],'source_hand':side,'avatar_hand':avatar_side,
     'expected':label['palm_direction'],'raw_nlf':raw,'rendered_geometry':avatar,
     'raw_matches':raw['majority']==label['palm_direction'],
     'avatar_matches':avatar['majority']==label['palm_direction'],
     'boxes':np.median([f['data']['box'] for f in fs],axis=0).round(1).tolist() if fs else []})
  report={'avatar':summary['avatar'],'nlf_matches':sum(r['raw_matches'] for r in results),
   'avatar_matches':sum(r['avatar_matches'] for r in results),'evaluated_hand_cases':len(results),
   'nlf_query':sorted(set(f['data']['nlf_query'] for f in frames)),
   'labels_sha256':__import__('hashlib').sha256(LABELS.read_bytes()).hexdigest(),
   'method':'Eixo dominante da normal de wrist/index1/pinky1. NLF sem espelho; avatar por posições reais de ossos, com troca L/R do selfie. Descartados 2s iniciais de cada foto; vetores com sin(angulo)<0.05 degenerados.',
   'limitations':'Rótulos visuais aproximados, câmera não calibrada, punhos fechados parcialmente ocultos. Frames repetidos não são amostras independentes. Não representa acurácia geral ou erro angular 3D.',
   'results':results}
  (folder/'palm_metrics.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
  print(folder.name,report['nlf_matches'],report['avatar_matches'],len(results))
  for r in results:print(r['image'][:2],r['source_hand'],r['expected'],r['raw_nlf']['majority'],r['rendered_geometry']['majority'],r['boxes'])

if __name__=='__main__':main()
