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
  const deg = (v) => v ? +(Math.asin(THREE.MathUtils.clamp(v.y/Math.max(1e-9,v.length()),-1,1))*180/Math.PI).toFixed(1) : null;
  const avail = Object.keys(aux).filter(k=>/elbow|shoulder|wrist|arm/i.test(k));
  const out = { avail };
  out.nlfArmElev = {
    L: deg(aux.left_elbow && aux.left_shoulder ? aux.left_elbow.clone().sub(aux.left_shoulder) : null),
    R: deg(aux.right_elbow && aux.right_shoulder ? aux.right_elbow.clone().sub(aux.right_shoulder) : null),
  };
  const aL = P('leftArm'), fL = P('leftForeArm'), aR = P('rightArm'), fR = P('rightForeArm');
  out.avatarArmElev = { L: deg(aL&&fL?fL.clone().sub(aL):null), R: deg(aR&&fR?fR.clone().sub(aR):null) };
  out.nlfShY = { L: aux.left_shoulder?+aux.left_shoulder.y.toFixed(3):null, R: aux.right_shoulder?+aux.right_shoulder.y.toFixed(3):null };
  const ls = P('leftArm'), rs = P('rightArm');
  out.avatarArmY = { L: ls?+ls.y.toFixed(3):null, R: rs?+rs.y.toFixed(3):null };
  const l = rig.bones.get('leftArm'), r = rig.bones.get('rightArm');
  out.armTransCm = {
    L: l?+(l.bone.position.distanceTo(l.restLocalPosition)*100).toFixed(2):null,
    R: r?+(r.bone.position.distanceTo(r.restLocalPosition)*100).toFixed(2):null,
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
        print(f"   elev braco avatar L/R: {out['avatarArmElev']['L']} / {out['avatarArmElev']['R']}   NLF L/R: {out['nlfArmElev']['L']} / {out['nlfArmElev']['R']}")
        print(f"   ombro Y NLF L/R: {out['nlfShY']['L']} / {out['nlfShY']['R']}   avatar ArmY L/R: {out['avatarArmY']['L']} / {out['avatarArmY']['R']}   translacao cm L/R: {out['armTransCm']['L']} / {out['armTransCm']['R']}")
        p.close()
    b.close()
srv.shutdown()

