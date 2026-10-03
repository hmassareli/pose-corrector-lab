import json, sys, threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from playwright.sync_api import sync_playwright
sys.path[:0]=['scripts']
from check_palm_fidelity import Handler

LAB=Path('.').resolve()
OUT=LAB/'experiments/bone_crook'

# Probe 1: REST pose asymmetries (what the rig is born with)
REST = """
async () => {
  const THREE = await import('three');
  const { loadAvatar } = await import('/static/avatar_assets.js');
  const { buildAvatarRig } = await import('/static/mikapo_mixamo_solver.js');
  const { root } = await loadAvatar('boxeador');
  root.updateWorldMatrix(true,true);
  const rig = buildAvatarRig(root);
  const out = {};
  const P = (n) => {
    const r = rig.bones.get(n);
    if (!r) return null;
    return r.bone.getWorldPosition(new THREE.Vector3()).toArray().map(v=>+v.toFixed(4));
  };
  // shoulder heights and collar heights in rest
  out.rest = {
    leftShoulder: P('leftShoulder'), rightShoulder: P('rightShoulder'),
    leftArm: P('leftArm'), rightArm: P('rightArm'),
    neck: P('neck'), head: P('head'), spine2: P('spine2'),
    hips: P('hips'),
  };
  // neck rest direction (off vertical? which way?)
  const neck = rig.bones.get('neck');
  out.neckRestDir = neck ? [neck.restDirectionInRoot.x, neck.restDirectionInRoot.y, neck.restDirectionInRoot.z].map(v=>+v.toFixed(3)) : null;
  const head = rig.bones.get('head');
  out.headRestDir = head ? [head.restDirectionInRoot.x, head.restDirectionInRoot.y, head.restDirectionInRoot.z].map(v=>+v.toFixed(3)) : null;
  // collar dirs
  for (const s of ['left','right']) {
    const sh = rig.bones.get(s+'Shoulder');
    if (sh) out[s+'CollarRestDir'] = [sh.restDirectionInRoot.x, sh.restDirectionInRoot.y, sh.restDirectionInRoot.z].map(v=>+v.toFixed(3));
  }
  // RAW bone positions (not rig-mapped): find collar bones directly
  const collars = {};
  root.traverse(n => {
    if ((n.isBone||n.type==='Bone') && /collar|shoulder/i.test(n.name)) {
      collars[n.name] = n.getWorldPosition(new THREE.Vector3()).toArray().map(v=>+v.toFixed(4));
    }
  });
  out.collarBones = collars;
  return out;
}
"""

# Probe 2: live pose per-side — shoulder/collar world pos + dirs after solve
LIVE = """
() => {
  const THREE = window.__BAKE_THREE__;
  const av = window.__BAKE_AVATAR__;
  const rig = window.__BAKE_RIG__;
  av.updateWorldMatrix(true,true);
  const invM = av.matrixWorld.clone().invert();
  const P = (n) => {
    const r = rig.bones.get(n);
    if (!r) return null;
    return r.bone.getWorldPosition(new THREE.Vector3()).applyMatrix4(invM).toArray().map(v=>+v.toFixed(4));
  };
  const D = (n) => {
    const r = rig.bones.get(n);
    if (!r || !r.child) return null;
    const a = r.bone.getWorldPosition(new THREE.Vector3()).applyMatrix4(invM);
    const b = r.child.getWorldPosition(new THREE.Vector3()).applyMatrix4(invM);
    const d = b.sub(a);
    const l = Math.hypot(d.x,d.y,d.z);
    return l>1e-8 ? [d.x/l, d.y/l, d.z/l].map(v=>+v.toFixed(3)) : null;
  };
  const bind = (n) => {
    const r = rig.bones.get(n);
    if (!r) return null;
    return +(2*Math.acos(Math.min(1, Math.abs(r.bone.quaternion.clone().dot(r.restLocalQuaternion))))*180/Math.PI).toFixed(1);
  };
  return {
    pos: { leftShoulder: P('leftShoulder'), rightShoulder: P('rightShoulder'),
           leftArm: P('leftArm'), rightArm: P('rightArm'),
           neck: P('neck'), head: P('head'), spine2: P('spine2') },
    dir: { leftShoulder: D('leftShoulder'), rightShoulder: D('rightShoulder'),
           neck: D('neck'), head: D('head') },
    bindDeg: { leftShoulder: bind('leftShoulder'), rightShoulder: bind('rightShoulder'),
               neck: bind('neck'), head: bind('head'), spine2: bind('spine2') },
    // what the solver USED as inputs: aux collar/shoulder/neck (viewer space)
    aux: window.__BAKE_AUX__ ? true : false,
  };
}
"""

PROBE_HTML = '<!DOCTYPE html><html><head><meta charset="utf-8"/><script type="importmap">{"imports":{"three":"https://unpkg.com/three@0.160.0/build/three.module.js","three/addons/":"https://unpkg.com/three@0.160.0/examples/jsm/"}}</script></head><body><script type="module">window.__R__=null;window.__E__=null;try{window.__R__=await (eval(window.__PROBE__))();}catch(e){window.__E__=String(e&&e.stack||e);}</script></body></html>'

class H(Handler):
    probe=None
    def translate_path(self, path):
        from urllib.parse import unquote, urlparse
        route=unquote(urlparse(path).path)
        if route=='/probe':
            p=OUT/'_probe_neck.html'
            p.write_text(PROBE_HTML, encoding='utf-8')
            return str(p)
        if route.startswith('/poses/'):
            return str(OUT/route[len('/poses/'):])
        return super().translate_path(route)

srv=ThreadingHTTPServer(('127.0.0.1',0),H)
threading.Thread(target=srv.serve_forever,daemon=True).start()
url=f'http://127.0.0.1:{srv.server_port}'
with sync_playwright() as pw:
    b=pw.chromium.launch(headless=True)
    # rest probe: inject probe fn into the page before load
    H.probe = REST
    p=b.new_page()
    p.goto(f'{url}/probe', wait_until='domcontentloaded')
    p.evaluate(f'window.__PROBE__ = {json.dumps(REST)}')
    # the module script already ran before we set it; instead evaluate directly
    out=p.evaluate(REST)
    print('=== REST (rig nasce assim) ===')
    print(json.dumps(out, indent=1))
    p.close()
    # live probe on two frames
    for tag in ['upright','sit']:
        p=b.new_page(viewport={'width':720,'height':960})
        p.goto(f"{url}/bake_seq?pose=/poses/pose_{tag}.json&avatar=boxeador&side=1&fps=1&ui=0", wait_until='domcontentloaded', timeout=180000)
        p.wait_for_function('() => window.__BAKE_READY__ || window.__BAKE_ERROR__', timeout=240000)
        try: p.evaluate('() => window.__bakeSeqStep && window.__bakeSeqStep()')
        except Exception: pass
        out=p.evaluate(LIVE)
        print(f'=== LIVE {tag} ===')
        print(json.dumps(out, indent=1))
        p.close()
    b.close()
srv.shutdown()

# Also: what does the NLF aux say about collar/shoulder/neck on those frames?
import numpy as np
sys.path.insert(0,'src')
frames=json.loads((OUT/'frames.json').read_text())
for fm in frames:
    if fm['tag'] not in ('upright','sit'): continue
    a=fm['aux_smpl']
    lc=np.array(a['left_collar']); rc=np.array(a['right_collar'])
    ls=np.array(a['left_shoulder']); rs=np.array(a['right_shoulder'])
    neck=np.array(a['neck']); head=np.array(a['head'])
    print(f"=== AUX NLF {fm['tag']} (opencv mm) ===")
    print('  collar y (L/R):', round(lc[1],1), round(rc[1],1), ' delta:', round(rc[1]-lc[1],1))
    print('  shoulder y (L/R):', round(ls[1],1), round(rs[1],1), ' delta:', round(rs[1]-ls[1],1))
    print('  collar x (L/R):', round(lc[0],1), round(rc[0],1))
    print('  neck->head dir:', np.round((head-neck)/np.linalg.norm(head-neck),3))
    print('  collar->shoulder L:', np.round((ls-lc)/np.linalg.norm(ls-lc),3), ' R:', np.round((rs-rc)/np.linalg.norm(rs-rc),3))

