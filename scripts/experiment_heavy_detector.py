from pathlib import Path
import subprocess,json
out=Path('experiments/heavy_hands_gauntlet');src=Path('viewer/boxing_core.mjs').read_text();bench=Path('scripts/benchmark_heavy_runtime.mjs').read_text()
rows=[]
for cooldown in [225,240,250,260,270,280]:
 (out/'experiment_core.mjs').write_text(src.replace('time+200','time+'+str(cooldown)))
 (out/'experiment_bench.mjs').write_text(bench.replace('../viewer/boxing_core.mjs','./experiment_core.mjs'))
 for suffix in ['cached','fresh']:
  subprocess.run(['node',str(out/'experiment_bench.mjs'),str(out/('benchmark_input_'+suffix+'.json')),str(out/'experiment_result.json')],capture_output=True,check=True)
  j=json.loads((out/'experiment_result.json').read_text());rows.append({'cooldown':cooldown,'capture':suffix,'events':len(j['events']),'match':j['matched'],'false':len(j['falseEvents']),'fist':j['phases'][-1]['meanPowerPct']})
print(json.dumps(rows,indent=2));(out/'detector_experiments.json').write_text(json.dumps(rows,indent=2))
