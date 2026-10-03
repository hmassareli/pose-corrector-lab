import json, sys, threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from playwright.sync_api import sync_playwright
sys.path[:0]=['scripts']
from check_palm_fidelity import Handler

LAB=Path('.').resolve(); OUT=LAB/'experiments/bone_crook'

class H(Handler):
    def translate_path(self, path):
        from urllib.parse import unquote, urlparse
        route=unquote(urlparse(path).path)
        if route.startswith('/poses/'):
            return str(OUT/route[len('/poses/'):])
        return super().translate_path(route)

M = """
async () => {
  const THREE = window.__BAKE_THREE__;
  const av = window.__BAKE_AVATAR__;
  const rig = window.__BAKE_RIG__;
  const S = await import('/static/mikapo_mixamo_solver.js');
  const q = new URLSearchParams(location.search);
  const data = await fetch(q.get('pose')).then(r=>r.json());
  const aux = S.auxFromSmpl(data.aux_smpl, true);
  av.updateWorldMatrix(true,true);
  const invM = av.matrixWorld.clone().invert();
  const P = (n) => rig.bones.get(n) ? rig.bones.get(n).bone.getWorldPosition(new THREE.Vector3()).applyMatrix4(invM) : null;
  const armY = (side) => {
    const sh = P(side+'Arm'), el = P(side+(side==='left'?'ForeArm':'ForeArm'));
    return null;
  };
  // arm elevation: angle of upper arm (Arm->ForeArm) below horizontal, per side
  const elev = (n1, n2) => {
    const a = P(n1), b = P(n2);
    if (!a || !b) return null;
    const d = b.clone().sub(a).normalize();
    return +(Math.asin(THREE.MathUtils.clamp(d.y,-1,1))*180/Math.PI).toFixed(1);
  };
  const elevNLF = (a,b) => {
    const d = b.clone().sub(a).normalize();
    return +(Math.asin(THREE.MathUtils.clamp(d.y,-1,1))*180/Math.PI).toFixed(1);
  };
  // upper arm: SMPL shoulder->elbow vs avatar Arm dir
  
  const out = {};
  out.avatarArmElev = { L: elev('leftArm','leftForeArm'), R: elev('rightArm','rightForeArm') };
  out.nlfArmElev = {
    L: elevNLF(aux.left_elbow.clone().sub(aux.left_shoulder)),
    R: elevNLF(aux.right_elbow.clone().sub(aux.right_shoulder)),
  };
  // NLF shoulder heights (already flipped to viewer: y up)
  out.nlfShY = { L: +aux.left_shoulder.y.toFixed(3), R: +aux.right_shoulder.y.toFixed(3) };
  out.nlfElbowY = { L: +aux.left_elbow.y.toFixed(3), R: +aux.right_elbow.y.toFixed(3) };
  // avatar positions
  const ls = P('leftArm'), rs = P('rightArm');
  out.avatarArmY = { L: +ls.y.toFixed(3), R: +rs.y.toFixed(3) };
  // translation applied to arms by updateJointTranslations
  const l = rig.bones.get('leftArm'), r = rig.bones.get('rightArm');
  out.armTransCm = {
    L: +(l.bone.position.distanceTo(l.restLocalPosition)*100).toFixed(2),
    R: +(r.bone.position.distanceTo(r.restLocalPosition)*100).toFixed(2),
    Ly: +((l.bone.position.y - l.restLocalPosition.y)*100).toFixed(2),
    Ry: +((r.bone.position.y - r.restLocalPosition.y)*100).toFixed(2),
  };
  return out;
}
"""

srv=ThreadingHTTPServer(('127.0.0.1',0),H)
threading.Thread(target=srv.serve_forever,daemon=True).start()
url=f'http://127.0.0.1:{srv.server_port}'
with sync_playwright() as pw:
    b=pw.chromium.launch(headless=True)
    for tag in ['upright','sit','mid']:
        p=b.new_page(viewport={'width':720,'height':960})
        p.goto(f"{url}/bake_seq?pose=/poses/pose_{tag}.json&avatar=boxeador&fps=1&ui=0", wait_until='domcontentloaded', timeout=180000)
        p.wait_for_function('() => window.__BAKE_READY__ || window.__BAKE_ERROR__', timeout=240000)
        try: p.evaluate('() => window.__bakeSeqStep && window.__bakeSeqStep()')
        except Exception: pass
        out=p.evaluate(M)
        print(f"== {tag}")
        print(f"   elev braco  avatar L/R: {out['avatarArmElev']['L']} / {out['avatarArmElev']['R']}   NLF L/R: {out['nlfArmElev']['L']} / {out['nlfArmElev']['R']}")
        print(f"   ombro Y NLF L/R: {out['nlfShY']['L']} / {out['nlfShY']['R']}   cotovelo Y NLF L/R: {out['nlfElbowY']['L']} / {out['nlfElbowY']['R']}")
        print(f"   avatar Arm Y L/R: {out['avatarArmY']['L']} / {out['avatarArmY']['R']}   translacao aplicada cm: L={out['armTransCm']['L']} R={out['armTransCm']['R']} (y: L={out['armTransCm']['Ly']} R={out['armTransCm']['Ry']})")
        p.close()
    b.close()
srv.shutdown()


