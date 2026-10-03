import json
from pathlib import Path
for s in ['cached','fresh']:
 j=json.loads(Path('experiments/heavy_hands_gauntlet/benchmark_runtime_'+s+'.json').read_text());print(s,[(r['n'],r['t'],r['hand'],r['forceN']) for r in j['rows'] if not r['detected']]);print([(e['hand'],round(e['time']/1000,3),round(e['extension'],2),round(e['forceN'])) for e in j['events'] if 20<e['time']/1000<27])
path=Path('../debug_luta/corner-debug-2026-10-02T15-07-23-920Z/timeline.ndjson')
poses=[];frames=[];n=0
with path.open(encoding='utf-8') as f:
 for line in f:
  if line.startswith('{"type":"pose"'):
   j=json.loads(line);inp=j.get('input',{});poses.append({'t':j['tMs'],'cam':inp.get('cameraPose'),'pose':inp.get('pose'),'capture':inp.get('nlfDebug',{}).get('capture',{}).get('absoluteMs')})
  elif line.startswith('{"type":"frame"'):
   n+=1
   if n%150==0:
    j=json.loads(line);frames.append({'t':j['tMs'],'fighters':[{k:v for k,v in a.items() if k in ('avatarId','x','z','yaw','pose','aux')} for a in j['fighters']]})
result={'poses':poses,'frames':frames};Path('experiments/heavy_hands_gauntlet/live11-replay.json').write_text(json.dumps(result,separators=(',',':')),encoding='utf-8');print('Live replay',len(poses),len(frames),poses[0] if poses else None)
