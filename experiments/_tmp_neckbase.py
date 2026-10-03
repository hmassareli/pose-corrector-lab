import json, sys, threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from playwright.sync_api import sync_playwright
sys.path[:0]=['scripts']
from check_palm_fidelity import Handler

LAB=Path('.').resolve()
OUT=LAB/'experiments/bone_crook'

class H(Handler):
    def translate_path(self, path):
        from urllib.parse import unquote, urlparse
        route=unquote(urlparse(path).path)
        if route.startswith('/poses/'):
            return str(OUT/route[len('/poses/'):])
        return super().translate_path(route)

MEASURE = """
() => {
  const THREE = window.__BAKE_THREE__;
  const av = window.__BAKE_AVATAR__;
  const rig = window.__BAKE_RIG__;
  const cam = window.__BAKE_CAMERA__;
  av.updateWorldMatrix(true,true);
  const invM = av.matrixWorld.clone().invert();
  const P = (n) => {
    const r = rig.bones.get(n);
    return r ? r.bone.getWorldPosition(new THREE.Vector3()).applyMatrix4(invM).toArray() : null;
  };
  const bind = (n) => {
    const r = rig.bones.get(n);
    return r ? +(2*Math.acos(Math.min(1, Math.abs(r.bone.quaternion.clone().dot(r.restLocalQuaternion))))*180/Math.PI).toFixed(1) : null;
  };
  // neck kink: angle between neck->head and head->headTop (child)
  const nk = rig.bones.get('neck'), hd = rig.bones.get('head');
  let kink = null;
  if (nk?.child && hd?.child) {
    const a = hd.bone.getWorldPosition(new THREE.Vector3()).applyMatrix4(invM).sub(nk.bone.getWorldPosition(new THREE.Vector3()).applyMatrix4(invM));
    const b = hd.child.getWorldPosition(new THREE.Vector3()).applyMatrix4(invM).sub(hd.bone.getWorldPosition(new THREE.Vector3()).applyMatrix4(invM));
    kink = +(Math.acos(Math.min(1,Math.max(-1, a.normalize().dot(b.normalize()))))*180/Math.PI).toFixed(1);
  }
  const ls=P('leftShoulder'), rs=P('rightShoulder'), la=P('leftArm'), ra=P('rightArm');
  const out = {
    bindNeck: bind('neck'), bindHead: bind('head'), neckKink: kink,
    bindLSh: bind('leftShoulder'), bindRSh: bind('rightShoulder'),
    shYDelta: ls&&rs ? +((ls[1]-rs[1])*100).toFixed(2) : null,
    shXDelta: ls&&rs ? +((ls[0]+rs[0])*100).toFixed(2) : null,  // lateral offset symmetry
    armYDelta: la&&ra ? +((la[1]-ra[1])*100).toFixed(2) : null,
  };
  // front view screenshot (symmetry is judged from front)
  if (cam) { cam.position.set(0.05, 1.15, 2.6); cam.up.set(0,1,0); cam.lookAt(0, 0.95, 0); cam.updateProjectionMatrix(); }
  if (window.__bakeRender) window.__bakeRender();
  return out;
}
"""

srv=ThreadingHTTPServer(('127.0.0.1',0),H)
threading.Thread(target=srv.serve_forever,daemon=True).start()
url=f'http://127.0.0.1:{srv.server_port}'
rows=[]
with sync_playwright() as pw:
    b=pw.chromium.launch(headless=True)
    for tag in ['upright','sit','mid']:
        p=b.new_page(viewport={'width':720,'height':960})
        p.goto(f"{url}/bake_seq?pose=/poses/pose_{tag}.json&avatar=boxeador&fps=1&ui=0&v=base", wait_until='domcontentloaded', timeout=180000)
        p.wait_for_function('() => window.__BAKE_READY__ || window.__BAKE_ERROR__', timeout=240000)
        try: p.evaluate('() => window.__bakeSeqStep && window.__bakeSeqStep()')
        except Exception: pass
        m=p.evaluate(MEASURE)
        p.screenshot(path=str(OUT/f'neck_base_{tag}.png'))
        rows.append((tag, m))
        p.close()
    b.close()
srv.shutdown()
print('BASE (solver atual):')
for tag,m in rows:
    print(f"  {tag:<8} kinkNeckHead={m['neckKink']:>5}°  bindN={m['bindNeck']:>5} bindH={m['bindHead']:>5}  bindSh L={m['bindLSh']:>5} R={m['bindRSh']:>5}  shY L-R={m['shYDelta']:>6}cm  armY L-R={m['armYDelta']:>6}cm")
(OUT/'neck_base.json').write_text(json.dumps([{'tag':t, **m} for t,m in rows], indent=1))

