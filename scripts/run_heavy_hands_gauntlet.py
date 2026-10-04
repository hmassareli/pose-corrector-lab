"""Repeatable HEAVY HANDS gauntlet. Uses running local lab8780 and relay8790.
No real webcam is activated. --recorded-camera uses an explicit prerecorded fixture.
"""
import argparse,json,subprocess,sys,time
from pathlib import Path
root=Path(__file__).resolve().parents[1];out=root/'experiments/heavy_hands_gauntlet';out.mkdir(exist_ok=True)
p=argparse.ArgumentParser();p.add_argument('--full-replay',action='store_true');p.add_argument('--recorded-camera',action='store_true');p.add_argument('--backend-rebalance',action='store_true');args=p.parse_args()
commands=[['node','tests/test_boxing_core.mjs'],['node','tests/test_sparring_mocap.mjs'],[sys.executable,'tests/test_heavy_backend_stability.py'],[sys.executable,'tests/test_heavy_startup.py'],[sys.executable,'scripts/benchmark_heavy_runtime.py'],[sys.executable,'tests/test_heavy_ui_review.py'],[sys.executable,'tests/test_heavy_audio.py'],[sys.executable,'tests/test_boxing_footwork.py'],[sys.executable,'tests/test_boxing_combat_e2e.py'],[sys.executable,'tests/test_boxing_network.py'],[sys.executable,'tests/test_boxing_browser.py'],[sys.executable,'tests/test_boxing_browser.py','p2p'],[sys.executable,'tests/test_boxing_debug_recording.py'],[sys.executable,'tests/test_heavy_hands_geometry_review.py']]
if args.full_replay:commands.append([sys.executable,'tests/test_heavy_live_replay.py'])
if args.backend_rebalance:commands.append([sys.executable,'tests/test_heavy_backend_rebalance.py'])
if args.recorded_camera:commands.append([sys.executable,'tests/test_boxing_recorded_webcam.py'])
rows=[]
for i,command in enumerate(commands):
 start=time.perf_counter();name=Path(command[1]).stem+('-'+command[2] if len(command)>2 else '');print('Running',name,flush=True)
 with (out/('suite-'+name+'.log')).open('w',encoding='utf-8') as log:
  result=subprocess.run(command,cwd=root,stdout=log,stderr=subprocess.STDOUT)
 row={'command':command,'code':result.returncode,'seconds':round(time.perf_counter()-start,2)};rows.append(row);print('PASS' if not result.returncode else 'FAIL',name,flush=True)
(out/'suite-result.json').write_text(json.dumps(rows,indent=2),encoding='utf-8');sys.exit(1 if any(row['code'] for row in rows) else 0)
