from pathlib import Path
import json,re
path=Path('experiments/heavy_hands_gauntlet/benchmark_input.json')
data=json.loads(path.read_text())
rows=[]
for line in Path('benchmarks/punch_cadence_20261002.punches.md').read_text(encoding='utf-8').splitlines():
 cells=[x.strip() for x in line.strip('|').split('|')]
 if len(cells)!=8 or not cells[0].isdigit():continue
 rows.append({'n':int(cells[0]),'t':float(cells[1].rstrip('s')),'hand':'L' if cells[2]=='esq' else 'R','forceN':float(cells[5].split()[0])})
data['reference']=rows
path.write_text(json.dumps(data),encoding='utf-8')
