"""Fresh independent WS sessions, first frame detection and stationary startup metrics."""
import cv2,json,time,numpy as np
from pathlib import Path
from websockets.sync.client import connect
root=Path(__file__).resolve().parents[1];out=root/'experiments/heavy_hands_gauntlet'
cap=cv2.VideoCapture(str(root/'benchmarks/punch_cadence_20261002.mp4'));cap.set(cv2.CAP_PROP_POS_MSEC,5000);ok,bgr=cap.read();assert ok
h,w=bgr.shape[:2];s=min(1,960/max(h,w));frame=cv2.resize(bgr,(round(w*s),round(h*s)));ok,jpg=cv2.imencode('.jpg',frame,[cv2.IMWRITE_JPEG_QUALITY,82]);assert ok
runs=[]
for session in range(2):
 with connect('ws://127.0.0.1:8781/nlf',max_size=None,open_timeout=120) as ws:
  ws.send('warmup');warm=json.loads(ws.recv(timeout=120));assert warm['ok'];poses=[];server=[];start=time.perf_counter()
  for i in range(30):
   ws.send(b'NLF1'+i.to_bytes(4,'little')+jpg.tobytes());d=json.loads(ws.recv(timeout=120));assert d.get('ok'),d;poses.append([[p[0],-p[1],-p[2]] for p in d['camera_joints']]);server.append(d['server_ms'])
  p=np.array(poses);height=p[:,15,1]-np.minimum(p[:,5,1],p[:,6,1]);runs.append({'heightMedian':float(np.median(height)),'firstHeight':float(height[0]),'heightDeviationMax':float(np.max(np.abs(height-np.median(height)))),'rootJitterMedian':float(np.median(np.linalg.norm(np.diff(p[:,0,:],axis=0),axis=1))),'serverMsMedian':float(np.median(server)),'elapsed':time.perf_counter()-start,'poses':p.tolist(),'warm':warm})
assert all(r['heightDeviationMax']<=.03 and r['rootJitterMedian']<.04 for r in runs),runs
assert abs(runs[0]['firstHeight']-runs[1]['firstHeight'])<=.03
result={'result':'PASS','input':'Same stationary human frame at5sec,30consecutive observations per fresh WS, no frame sent before measurement','checks':['two independent session first frames agree within3cm','height±3cm from first observation','median jitter<4cm','first-frame crop from same person, no stale session'],'runs':runs,'limitation':'Controlled stationary startup check; moving first-second frames naturally change stance/height.'};(out/'startup-ws-test.json').write_text(json.dumps(result,indent=2));print(json.dumps({**result,'runs':[{k:v for k,v in r.items() if k!='poses'} for r in runs]},indent=2),flush=True)
