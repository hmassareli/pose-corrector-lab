"""Real concurrent TRT inference/lifetime and rolling-latency regressions."""
import gc,json,threading,time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
import numpy as np
import torch
from nlf_engine import ENGINE,AsyncPoseWorker,NlfFeatureEngine,_TrtRunner
from serve_lab import NlfRuntime

root=Path(__file__).resolve().parents[1];out=root/'experiments/heavy_hands_gauntlet'
runtime=NlfRuntime();runtime._engine=type('Engine',(),{'baseline':{'p50':30,'p95':35}})()
runtime._monitor_baseline={'p50':30,'p95':35};runtime._last_rebal=0
with patch('serve_lab.threading.Thread') as thread:
 runtime.rebalance_if_degraded(500,25,.85)
 assert not thread.called,'An isolated cold spike with healthy p95 must not re-bench'
 runtime._last_rebal=0;runtime.rebalance_if_degraded(100,150,.2)
 assert thread.call_count==1 and runtime._rebalancing
 runtime._last_rebal=0;runtime.rebalance_if_degraded(100,150,.2)
 assert thread.call_count==1,'Only one re-bench may run'
worker=AsyncPoseWorker(runtime);seen=[]
runtime.rebalance_if_degraded=lambda *args:seen.append(args)
for ms in [50000]+[25]*44:worker._monitor(runtime,{'server_ms':ms})
assert seen[0][0]==25 and seen[0][1]==25,seen

# The dispatch mutex must protect session.run regardless of provider. Exercise
# the actual _run_core with concurrent callers and an overlap-sensitive runner.
eng=NlfFeatureEngine.__new__(NlfFeatureEngine);eng.backend='dml';eng._runner=None
eng._swap_lock=threading.Lock();eng._dispatch_lock=threading.RLock()
eng._consecutive_failures=0;counts={'active':0,'max':0}
def dispatch(*args):
 counts['active']+=1;counts['max']=max(counts['max'],counts['active'])
 time.sleep(.005);counts['active']-=1;return torch.zeros(1)
eng._dispatch=dispatch
with ThreadPoolExecutor(max_workers=4) as pool:
 list(pool.map(lambda _:eng._run_core(torch.zeros(1,1),torch.zeros(1)),range(24)))
assert counts['max']==1,counts

# Real GPU, real production TensorRT engine: two runtimes share a retained
# logger; callers deliberately share one execution context. GC between loads
# stresses the lifetime that previously crashed the long-lived server.
runners=[_TrtRunner(ENGINE.read_bytes()) for _ in range(2)]
assert runners[0].logger is runners[1].logger
gc.collect();x=torch.ones(1,3,256,256,device='cuda',dtype=torch.float16)
reference=runners[0].run(x).float().cpu().numpy();errors=[];start=time.perf_counter()
def infer(i):
 value=runners[i%2].run(x).float().cpu().numpy()
 assert np.isfinite(value).all()
 return float(np.max(np.abs(value-reference)))
with ThreadPoolExecutor(max_workers=4) as pool:differences=list(pool.map(infer,range(80)))
assert max(differences)<=.01,max(differences)
torch.cuda.synchronize();del runners;gc.collect()
r=_TrtRunner(ENGINE.read_bytes());assert np.isfinite(r.run(x).float().cpu().numpy()).all()
report={'result':'PASS','checks':['cold outlier and queue drops cannot trigger backend replacement','sustained median+p95 degradation triggers once','rolling latency median ignores one cold50s sample','provider dispatch never overlaps','80 real concurrent TRT outputs after GC match single-call reference','two runtimes use same process-lifetime logger','new runtime after disposal still infers'],'dispatchMaximumConcurrent':counts['max'],'TRTCalls':80,'maxFeatureDifference':max(differences),'seconds':time.perf_counter()-start}
(out/'backend-stability-test.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2),flush=True)
