from __future__ import annotations
import json, math, sys, threading
from http.server import ThreadingHTTPServer
from pathlib import Path
import numpy as np

LAB = Path('.').resolve()
sys.path[:0] = [str(LAB/'scripts'), str(LAB/'src')]
from check_palm_fidelity import Handler
from pose_lab.skeleton import smplx55_avatar_aux_json, smplx55_to_lab

NPZ = LAB/'experiments/nlf_fit_webcam1/fit_smplx.npz'
OUT = LAB/'experiments/bone_crook'
OUT.mkdir(parents=True, exist_ok=True)
POSE = OUT/'pose.json'

d=np.load(NPZ); fit=np.asarray(d['fit_joints'],float); ok=np.asarray(d['ok'],bool)
# sitting-like frame 37
t=37
j=fit[t]
lab=smplx55_to_lab(j)
aux=smplx55_avatar_aux_json(j)
POSE.write_text(json.dumps({'joints':np.round(lab,6).tolist(),'aux_smpl':aux},separators=(',',':')),encoding='utf-8')
print('wrote', POSE, 'frame', t)

DUMP = r'''
() => {
  const THREE = window.__BAKE_THREE__;
  const av = window.__BAKE_AVATAR__;
  const rig = window.__BAKE_RIG__;
  if (!THREE || !av || !rig) return {error:'missing bake globals', hasThree:!!THREE, hasAv:!!av, hasRig:!!rig, keys:Object.keys(window).filter(k=>k.startsWith('__BAKE'))};
  av.updateWorldMatrix(true,true);
  const inv = av.getWorldQuaternion(new THREE.Quaternion()).invert();
  const P = (bone) => {
    const p = bone.getWorldPosition(new THREE.Vector3()).applyQuaternion(inv);
    return [p.x,p.y,p.z];
  };
  const bones = {};
  for (const [k,r] of rig.bones) {
    const pos = P(r.bone);
    const childPos = r.child ? P(r.child) : null;
    let liveDir = null, liveLen = null;
    if (childPos) {
      const d = [childPos[0]-pos[0], childPos[1]-pos[1], childPos[2]-pos[2]];
      liveLen = Math.hypot(...d);
      liveDir = liveLen>1e-8 ? d.map(v=>v/liveLen) : null;
    }
    const restDir = [r.restDirectionInRoot.x, r.restDirectionInRoot.y, r.restDirectionInRoot.z];
    // bind deviation
    const bind = 2*Math.acos(Math.min(1, Math.abs(r.bone.quaternion.clone().dot(r.restLocalQuaternion))))*180/Math.PI;
    // local euler-ish axis angle of current local vs rest
    const dq = r.restLocalQuaternion.clone().invert().multiply(r.bone.quaternion.clone());
    const ang = 2*Math.acos(Math.min(1, Math.abs(dq.w)))*180/Math.PI;
    bones[k] = {
      boneName: r.bone.name,
      childName: r.child ? r.child.name : null,
      pos, childPos, liveDir, liveLen, restDir,
      bindDeg: +bind.toFixed(2),
      localFromRestDeg: +ang.toFixed(2),
      posDeltaCm: +(r.bone.position.distanceTo(r.restLocalPosition)*100).toFixed(3),
    };
  }
  // chain turning angles hips->head
  const chain = ['hips','spine','spine1','spine2','neck','head'];
  const pts = chain.map(n => bones[n]?.pos).filter(Boolean);
  const turns = [];
  for (let i=1;i<pts.length-1;i++){
    const a=pts[i-1], b=pts[i], c=pts[i+1];
    const u=[b[0]-a[0],b[1]-a[1],b[2]-a[2]];
    const v=[c[0]-b[0],c[1]-b[1],c[2]-b[2]];
    const nu=Math.hypot(...u), nv=Math.hypot(...v);
    const dot = (u[0]*v[0]+u[1]*v[1]+u[2]*v[2])/(nu*nv);
    turns.push({at:chain[i], deg:+(Math.acos(Math.min(1,Math.max(-1,dot)))*180/Math.PI).toFixed(2)});
  }
  // hip aim vs spine aim discontinuity: angle between hips->spine dir and spine->spine1 dir
  const h=bones.hips, s=bones.spine, s1=bones.spine1;
  let hipSpineKink=null, spineSpine1Kink=null;
  if (h&&s&&s1&&h.liveDir&&s.liveDir){
    const dot = h.liveDir[0]*s.liveDir[0]+h.liveDir[1]*s.liveDir[1]+h.liveDir[2]*s.liveDir[2];
    hipSpineKink = +(Math.acos(Math.min(1,Math.max(-1,dot)))*180/Math.PI).toFixed(2);
  }
  if (s&&s1&&s.liveDir&&s1.liveDir){
    const dot = s.liveDir[0]*s1.liveDir[0]+s.liveDir[1]*s1.liveDir[1]+s.liveDir[2]*s1.liveDir[2];
    spineSpine1Kink = +(Math.acos(Math.min(1,Math.max(-1,dot)))*180/Math.PI).toFixed(2);
  }
  // also dump world positions of leftUpLeg/rightUpLeg vs hips child spine
  return {bones, turns, hipSpineKink, spineSpine1Kink, measure: window.__BAKE_MEASURE__};
}
'''

class H(Handler):
    def translate_path(self, path: str):
        from urllib.parse import unquote, urlparse
        route = unquote(urlparse(path).path)
        if route.startswith('/poses/'):
            return str(OUT / route[len('/poses/'):])
        return super().translate_path(route)

# Check if bake_seq exposes globals; else use avatar_bake + inject
from playwright.sync_api import sync_playwright
srv=ThreadingHTTPServer(('127.0.0.1',0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
url=f'http://127.0.0.1:{srv.server_port}'
try:
  with sync_playwright() as pw:
    b=pw.chromium.launch(headless=True)
    p=b.new_page(viewport={'width':900,'height':1100})
    msgs=[]
    p.on('console', lambda m: msgs.append(f'{m.type}:{m.text}'))
    p.on('pageerror', lambda e: msgs.append(f'ERR:{e}'))
    # single frame bake
    p.goto(f'{url}/bake?pose=/poses/pose.json&avatar=boxeador&side=1', wait_until='domcontentloaded', timeout=120000)
    p.wait_for_function('() => window.__BAKE_READY__ || window.__BAKE_ERROR__', timeout=240000)
    err=p.evaluate('() => window.__BAKE_ERROR__')
    print('bake err', err)
    # avatar_bake may not expose THREE/avatar/rig - check
    keys=p.evaluate("() => Object.keys(window).filter(k=>k.startsWith('__'))")
    print('window keys', keys)
    # inject by re-reading measure and also try to patch page to expose
    # Better: open a custom probe page
    b.close()
finally:
  srv.shutdown()
print('msgs', msgs[:15])
