import json,numpy as np,re,subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[1];out=root/'experiments/heavy_hands_gauntlet'
refs=[]
for line in (root/'benchmarks/punch_cadence_20261002.punches.md').read_text(encoding='utf-8').splitlines():
 c=[x.strip() for x in line.strip('|').split('|')]
 if len(c)==8 and c[0].isdigit():refs.append({'n':int(c[0]),'t':float(c[1].rstrip('s')),'hand':'L' if c[2]=='esq' else 'R','forceN':float(c[5].split()[0])})
for suffix,cache in [('cached','.nlf.npz'),('fresh','.nlf.fresh.npz')]:
 z=np.load(root/('benchmarks/punch_cadence_20261002'+cache))
 data={'times':z['times'].tolist(),'cam':z['cam'].tolist(),'reference':refs}
 source=out/('benchmark_input_'+suffix+'.json');source.write_text(json.dumps(data),encoding='utf-8')
 subprocess.run(['node','scripts/benchmark_heavy_runtime.mjs',str(source),str(out/('benchmark_runtime_'+suffix+'.json'))],check=True,cwd=root)
