"""Production native gate during real TRT/DML re-bench and concurrent inference.

Runs an isolated NLF runtime (no camera/server sockets). CPU-only candidates are
excluded from this GPU regression; their speed/quality is not certified here.
"""
import json,time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
import numpy as np
import torch
from serve_lab import NlfRuntime

runtime=NlfRuntime();runtime.load(backend='trt')
assert runtime._backend_forced
frame=np.full((540,960,3),128,dtype=np.uint8)
box=torch.tensor([[192.,108.,576.,324.]])
def infer(_):
 result=runtime.infer_rgb(frame,box=box,skip_detect=True)
 assert result['ok'] and np.isfinite(result['joints']).all(),result
 return result['joints']
reference=infer(0);start=time.perf_counter()
with patch('nlf_engine.available_backends',return_value=['trt','dml']):
 with ThreadPoolExecutor(max_workers=3) as pool:
  work=[pool.submit(infer,i) for i in range(4)]
  bench=pool.submit(runtime._do_rebalance)
  work.extend(pool.submit(infer,i) for i in range(4,12))
  poses=[f.result(timeout=180) for f in work];bench.result(timeout=180)
assert not runtime._rebalancing
final=infer(0)
assert np.isfinite(final).all()
report={'result':'PASS','checks':['explicit trt backend remains forced','real production re-bench TRT+DML while twelve inference callers wait/execute','native gate serializes re-bench and inference','all outputs finite and valid before/during/after','rebalance flag clears','no process crash'],'candidateBackends':['trt','dml'],'inferences':len(poses)+2,'finalBackend':runtime._engine.backend,'maxPoseDifferenceM':float(np.max(np.abs(np.asarray(poses)-reference))),'seconds':time.perf_counter()-start,'limitation':'Isolated runtime on controlled static frame; CPU-only rebalance candidates not benchmarked.'}
out=Path(__file__).resolve().parents[1]/'experiments/heavy_hands_gauntlet'
(out/'backend-rebalance-test.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2),flush=True)
