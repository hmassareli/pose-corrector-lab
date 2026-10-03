from __future__ import annotations
import json, sys, threading
from http.server import ThreadingHTTPServer
from pathlib import Path
import numpy as np
from playwright.sync_api import sync_playwright

LAB = Path('.').resolve()
sys.path[:0] = [str(LAB/'scripts'), str(LAB/'src')]
from check_palm_fidelity import Handler
from pose_lab.skeleton import smplx55_avatar_aux_json, smplx55_to_lab

OUT = LAB/'experiments/bone_crook'
OUT.mkdir(parents=True, exist_ok=True)
NPZ = LAB/'experiments/nlf_fit_webcam1/fit_smplx.npz'
d=np.load(NPZ); fit=np.asarray(d['fit_joints'],float); ok=np.asarray(d['ok'],bool)
axis = fit[:,12]-fit[:,0]
axis_len=np.linalg.norm(axis,axis=1)
lean=np.degrees(np.arccos(np.clip(axis[:,1]/np.maximum(axis_len,1e-9),-1,1)))
valid=np.where(ok & (axis_len>0.05))[0]
upright=int(valid[np.argmin(np.abs(lean[valid]-180))])
frames_meta=[]
for t,tag in [(37,'sit'), (528,'mid'), (1052,'lean'), (upright,'upright')]:
    j=fit[t]
    frames_meta.append({'tag':tag,'frame':int(t),'lean':float(lean[t]),
        'joints':np.round(smplx55_to_lab(j),6).tolist(),
        'aux_smpl':smplx55_avatar_aux_json(j)})
(OUT/'frames.json').write_text(json.dumps(frames_meta,separators=(',',':')),encoding='utf-8')

DUMP = """
() => {
  const THREE = window.__BAKE_THREE__;
  const av = window.__BAKE_AVATAR__;
  const rig = window.__BAKE_RIG__;
  const cam = window.__BAKE_CAMERA__;
  av.updateWorldMatrix(true,true);
  const invM = av.matrixWorld.clone().invert();
  const P = (bone) => {
    const p = bone.getWorldPosition(new THREE.Vector3()).applyMatrix4(invM);
    return [p.x,p.y,p.z];
  };
  const bones = {};
  for (const [k,r] of rig.bones) {
    const pos = P(r.bone);
    const childPos = r.child ? P(r.child) : null;
    let liveDir=null, liveLen=null;
    if (childPos) {
      const d=[childPos[0]-pos[0],childPos[1]-pos[1],childPos[2]-pos[2]];
      liveLen=Math.hypot(...d);
      liveDir = liveLen>1e-8 ? d.map(v=>v/liveLen) : null;
    }
    const bind = 2*Math.acos(Math.min(1, Math.abs(r.bone.quaternion.clone().dot(r.restLocalQuaternion))))*180/Math.PI;
    bones[k] = {
      bone:r.bone.name, child:r.child?r.child.name:null,
      pos: pos.map(v=>+v.toFixed(4)),
      childPos: childPos ? childPos.map(v=>+v.toFixed(4)) : null,
      liveDir: liveDir ? liveDir.map(v=>+v.toFixed(4)) : null,
      liveLen: liveLen!=null ? +liveLen.toFixed(4) : null,
      restDir: [r.restDirectionInRoot.x,r.restDirectionInRoot.y,r.restDirectionInRoot.z].map(v=>+v.toFixed(4)),
      bindDeg: +bind.toFixed(2),
      posDeltaCm: +(r.bone.position.distanceTo(r.restLocalPosition)*100).toFixed(3),
    };
  }
  const chain=['hips','spine','spine1','spine2','neck','head'];
  const turns=[];
  for (let i=1;i<chain.length-1;i++){
    const a=bones[chain[i-1]], b=bones[chain[i]], c=bones[chain[i+1]];
    if(!a||!b||!c) continue;
    const u=[b.pos[0]-a.pos[0],b.pos[1]-a.pos[1],b.pos[2]-a.pos[2]];
    const v=[c.pos[0]-b.pos[0],c.pos[1]-b.pos[1],c.pos[2]-b.pos[2]];
    const nu=Math.hypot(...u), nv=Math.hypot(...v);
    const dot=(u[0]*v[0]+u[1]*v[1]+u[2]*v[2])/(nu*nv);
    turns.push({at:chain[i], deg:+(Math.acos(Math.min(1,Math.max(-1,dot)))*180/Math.PI).toFixed(2)});
  }
  const aimKinks=[];
  for (let i=0;i<chain.length-1;i++){
    const a=bones[chain[i]], b=bones[chain[i+1]];
    if(!a?.liveDir||!b?.liveDir) continue;
    const dot=a.liveDir[0]*b.liveDir[0]+a.liveDir[1]*b.liveDir[1]+a.liveDir[2]*b.liveDir[2];
    aimKinks.push({from:chain[i], to:chain[i+1], deg:+(Math.acos(Math.min(1,Math.max(-1,dot)))*180/Math.PI).toFixed(2)});
  }
  const lU=bones.leftUpLeg, rU=bones.rightUpLeg, lA=bones.leftArm, rA=bones.rightArm;
  const yaw = (a,b) => {
    if(!a||!b) return null;
    const ax=b.pos[0]-a.pos[0], az=b.pos[2]-a.pos[2];
    return Math.atan2(az, ax)*180/Math.PI;
  };
  const hipYaw = yaw(lU,rU), shYaw=yaw(lA,rA);
  let twist=null;
  if (hipYaw!=null && shYaw!=null) {
    let d=shYaw-hipYaw; while(d>180)d-=360; while(d<-180)d+=360; twist=+d.toFixed(2);
  }
  if (!window.__SKEL__) {
    const sk = new THREE.SkeletonHelper(av);
    sk.material.depthTest=false; sk.material.depthWrite=false; sk.material.transparent=true; sk.material.opacity=1;
    if (sk.material.color) sk.material.color.setHex(0x7dd3fc);
    let root=av; while(root.parent) root=root.parent;
    root.add(sk); window.__SKEL__=sk;
    const g=new THREE.Group(); root.add(g); window.__JG__=g;
    const geo=new THREE.SphereGeometry(0.018,12,12);
    const colors={hips:0x3ddea5,spine:0x6ea8fe,spine1:0x6ea8fe,spine2:0x6ea8fe,neck:0xc084fc,head:0xc084fc,
      leftShoulder:0xffdd44,rightShoulder:0xffdd44,leftArm:0xff8c42,rightArm:0xff8c42,
      leftUpLeg:0xffffff,rightUpLeg:0xffffff,leftLeg:0xaaaaaa,rightLeg:0xaaaaaa,
      leftFoot:0xff6b9d,rightFoot:0xff6b9d,leftHand:0x3de0ff,rightHand:0x3de0ff,
      leftForeArm:0x88ff88,rightForeArm:0x88ff88};
    window.__MARKS__=[];
    for (const [k,r] of rig.bones) {
      const mat=new THREE.MeshBasicMaterial({color:colors[k]??0xe2e8f0, depthTest:false, transparent:true, opacity:0.95});
      const m=new THREE.Mesh(geo, mat); m.renderOrder=20; g.add(m);
      window.__MARKS__.push({bone:r.bone, mesh:m});
    }
    av.traverse(n=>{ if(n.isMesh&&n.material){ const mats=Array.isArray(n.material)?n.material:[n.material]; for(const mat of mats){ mat.transparent=true; mat.opacity=0.28; mat.depthWrite=false; mat.needsUpdate=true; } }});
  }
  for (const m of window.__MARKS__) {
    m.mesh.position.copy(m.bone.getWorldPosition(new THREE.Vector3()));
  }
  // side camera manually
  if (cam) {
    cam.position.set(1.9, 1.05, 0.15);
    cam.up.set(0,1,0);
    cam.lookAt(0, 0.85, 0);
    cam.updateProjectionMatrix();
  }
  if (window.__bakeRender) window.__bakeRender();
  return {bones, turns, aimKinks, twist, hipYaw: hipYaw==null?null:+hipYaw.toFixed(2), shYaw: shYaw==null?null:+shYaw.toFixed(2)};
}
"""

class H(Handler):
    def translate_path(self, path: str):
        from urllib.parse import unquote, urlparse
        route=unquote(urlparse(path).path)
        if route.startswith('/poses/'):
            return str(OUT/route[len('/poses/'):])
        return super().translate_path(route)

srv=ThreadingHTTPServer(('127.0.0.1',0),H)
threading.Thread(target=srv.serve_forever,daemon=True).start()
url=f'http://127.0.0.1:{srv.server_port}'
results={}
try:
  with sync_playwright() as pw:
    browser=pw.chromium.launch(headless=True)
    for fm in frames_meta:
        pose_name=f"pose_{fm['tag']}.json"
        (OUT/pose_name).write_text(json.dumps({'joints':fm['joints'],'aux_smpl':fm['aux_smpl']},separators=(',',':')),encoding='utf-8')
        page=browser.new_page(viewport={'width':720,'height':960})
        page.goto(f"{url}/bake_seq?pose=/poses/{pose_name}&avatar=boxeador&side=1&fps=1&ui=0", wait_until='domcontentloaded', timeout=180000)
        page.wait_for_function('() => window.__BAKE_READY__ || window.__BAKE_ERROR__', timeout=240000)
        err=page.evaluate('() => window.__BAKE_ERROR__')
        if err:
            print('ERR', fm['tag'], err); page.close(); continue
        try:
            page.evaluate('() => window.__bakeSeqStep && window.__bakeSeqStep()')
        except Exception:
            pass
        data=page.evaluate(DUMP)
        page.screenshot(path=str(OUT/f"boxeador_{fm['tag']}.png"), type='png')
        results[fm['tag']]=data
        print('====', fm['tag'], 'frame', fm['frame'], 'lean', round(fm['lean'],1))
        print(' turns', data['turns'])
        print(' aimKinks', data['aimKinks'])
        print(' twist hip->sh', data['twist'])
        for k in ['hips','spine','spine1','spine2','neck','leftShoulder','rightShoulder','leftArm','rightArm','leftUpLeg','rightUpLeg','leftLeg','rightLeg']:
            b=data['bones'].get(k)
            if not b: continue
            print(f"  {k:14s} bind={b['bindDeg']:6.2f} dPos={b['posDeltaCm']:6.3f}cm dir={b['liveDir']} child={b['child']}")
        page.close()
    browser.close()
finally:
    srv.shutdown()
(OUT/'measure.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
print('wrote', OUT)
