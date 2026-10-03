import json, sys, threading
from http.server import ThreadingHTTPServer
from pathlib import Path
import numpy as np
from playwright.sync_api import sync_playwright
sys.path[:0]=['scripts']
from check_palm_fidelity import Handler

LAB=Path('.').resolve()
OUT=LAB/'experiments/bone_crook'
OLD=LAB/'experiments/_solver_spine_zigzag.js'

class H(Handler):
    old=False
    def translate_path(self, path):
        from urllib.parse import unquote, urlparse
        route=unquote(urlparse(path).path)
        if H.old and route=='/static/mikapo_mixamo_solver.js':
            return str(OLD)
        if route.startswith('/poses/'):
            return str(OUT/route[len('/poses/'):])
        return super().translate_path(route)

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
    let liveDir=null;
    if (childPos) {
      const d=[childPos[0]-pos[0],childPos[1]-pos[1],childPos[2]-pos[2]];
      const len=Math.hypot(...d);
      liveDir = len>1e-8 ? d.map(v=>v/len) : null;
    }
    const bind = 2*Math.acos(Math.min(1, Math.abs(r.bone.quaternion.clone().dot(r.restLocalQuaternion))))*180/Math.PI;
    bones[k] = { pos, childPos, liveDir, bindDeg:+bind.toFixed(2) };
  }
  const chain=['hips','spine','spine1','spine2','neck','head'];
  const aimKinks=[];
  for (let i=0;i<chain.length-1;i++){
    const a=bones[chain[i]], b=bones[chain[i+1]];
    if(!a?.liveDir||!b?.liveDir) continue;
    const dot=a.liveDir[0]*b.liveDir[0]+a.liveDir[1]*b.liveDir[1]+a.liveDir[2]*b.liveDir[2];
    aimKinks.push({from:chain[i], to:chain[i+1], deg:+(Math.acos(Math.min(1,Math.max(-1,dot)))*180/Math.PI).toFixed(2)});
  }
  // skeleton overlay
  if (!window.__SKEL__) {
    const sk = new THREE.SkeletonHelper(av);
    sk.material.depthTest=false; sk.material.depthWrite=false; sk.material.transparent=true; sk.material.opacity=1;
    if (sk.material.color) sk.material.color.setHex(0x7dd3fc);
    let root=av; while(root.parent) root=root.parent;
    root.add(sk); window.__SKEL__=sk;
    const g=new THREE.Group(); root.add(g);
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
  for (const m of window.__MARKS__) m.mesh.position.copy(m.bone.getWorldPosition(new THREE.Vector3()));
  if (cam) { cam.position.set(1.9, 1.05, 0.15); cam.up.set(0,1,0); cam.lookAt(0,0.85,0); cam.updateProjectionMatrix(); }
  if (window.__bakeRender) window.__bakeRender();
  return {bones, aimKinks};
}
"""

srv=ThreadingHTTPServer(('127.0.0.1',0),H)
threading.Thread(target=srv.serve_forever,daemon=True).start()
url=f'http://127.0.0.1:{srv.server_port}'
frames=json.loads((OUT/'frames.json').read_text())
results={}
with sync_playwright() as pw:
    b=pw.chromium.launch(headless=True)
    for variant in ['before','after']:
        H.old = (variant=='before')
        results[variant]={}
        for fm in frames:
            tag=fm['tag']
            page=b.new_page(viewport={'width':720,'height':960})
            page.goto(f"{url}/bake_seq?pose=/poses/pose_{tag}.json&avatar=boxeador&side=1&fps=1&ui=0&v={variant}", wait_until='domcontentloaded', timeout=180000)
            page.wait_for_function('() => window.__BAKE_READY__ || window.__BAKE_ERROR__', timeout=240000)
            err=page.evaluate('() => window.__BAKE_ERROR__')
            if err: print('ERR',variant,tag,err); page.close(); continue
            try: page.evaluate('() => window.__bakeSeqStep && window.__bakeSeqStep()')
            except Exception: pass
            data=page.evaluate(DUMP)
            page.screenshot(path=str(OUT/f'ab_{variant}_{tag}.png'))
            results[variant][tag]=data
            page.close()
    b.close()
srv.shutdown()
(OUT/'ab_measure.json').write_text(json.dumps(results,indent=2),encoding='utf-8')

print('\n================ A/B: kinks na cadeia (graus) ================')
print(f'{"frame":<10}{"hips->spine":>18}{"spine->spine1":>20}{"spine1->spine2":>20}{"spine2->neck":>18}')
for fm in frames:
    tag=fm['tag']
    def g(v,frm,to):
        kk=results[v][tag]['aimKinks']
        m=[x for x in kk if x['from']==frm]
        return m[0]['deg'] if m else None
    row=f'{tag:<10}'
    for frm,to in [('hips','spine'),('spine','spine1'),('spine1','spine2'),('spine2','neck')]:
        a=g('before',frm,to); bb=g('after',frm,to)
        row+=f'{a:>6} -> {bb:>5}    '
    print(row)
print('\nbind deviation spine1 (before -> after):')
for fm in frames:
    tag=fm['tag']
    a=results['before'][tag]['bones']['spine1']['bindDeg']; bb=results['after'][tag]['bones']['spine1']['bindDeg']
    h0=results['before'][tag]['bones']['hips']['bindDeg']; h1=results['after'][tag]['bones']['hips']['bindDeg']
    print(f'  {tag:<10} spine1 {a:6.1f} -> {bb:5.1f}    hips {h0:6.1f} -> {h1:5.1f}')
