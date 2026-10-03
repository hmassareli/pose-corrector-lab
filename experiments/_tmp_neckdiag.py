import json, sys, threading
from http.server import ThreadingHTTPServer
from pathlib import Path
import numpy as np
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
  const D = (n) => {
    const r = rig.bones.get(n);
    if (!r?.child) return null;
    const a = P(n); const b = r.child.getWorldPosition(new THREE.Vector3()).applyMatrix4(invM);
    const d = b.sub(a); return d.normalize();
  };
  const deg = (u,v) => u&&v ? +(Math.acos(Math.min(1,Math.max(-1,u.dot(v))))*180/Math.PI).toFixed(1) : null;
  // SMPL collar->shoulder per side (what applyShoulderFromSmpl aims at)
  const liveL = aux.left_shoulder.clone().sub(aux.left_collar).normalize();
  const liveR = aux.right_shoulder.clone().sub(aux.right_collar).normalize();
  // torso axes from LIVE shoulders (same as solver)
  const upU = aux.neck.clone().sub(aux.left_hip.clone().add(aux.right_hip).multiplyScalar(0.5)).normalize();
  const across = aux.right_shoulder.clone().sub(aux.left_shoulder);
  const acrossU = across.clone().addScaledVector(upU, -across.dot(upU)).normalize();
  const fwdU = new THREE.Vector3().crossVectors(acrossU, upU).normalize();
  const latL = acrossU.clone().multiplyScalar(-1), latR = acrossU.clone();
  const elevAz = (live, lat) => ({
    elev: +(Math.asin(THREE.MathUtils.clamp(live.dot(upU),-1,1))*180/Math.PI).toFixed(1),
    az: +(Math.atan2(live.dot(fwdU), live.dot(lat))*180/Math.PI).toFixed(1),
  });
  // NLF spine3->neck and neck->head, and avatar spine2->neck, neck->head
  const nlfs3n = aux.neck.clone().sub(aux.spine3).normalize();
  const nlfnh = aux.head.clone().sub(aux.neck).normalize();
  const avs2n = P('neck').sub(P('spine2')).normalize();
  const avnh = D('neck');
  return {
    smplElevAzL: elevAz(liveL, latL), smplElevAzR: elevAz(liveR, latR),
    avatarDirL: D('leftShoulder')?.toArray().map(v=>+v.toFixed(3)),
    avatarDirR: D('rightShoulder')?.toArray().map(v=>+v.toFixed(3)),
    smplDirL: liveL.toArray().map(v=>+v.toFixed(3)),
    smplDirR: liveR.toArray().map(v=>+v.toFixed(3)),
    nlfSpine3Neck_vs_NeckHead: deg(nlfs3n, nlfnh),
    avSpine2Neck_vs_NeckHead: deg(avs2n, avnh),
    restNeckDir: (()=>{const r=rig.bones.get('neck'); return [r.restDirectionInRoot.x,r.restDirectionInRoot.y,r.restDirectionInRoot.z].map(v=>+v.toFixed(3));})(),
  };
}
"""

srv=ThreadingHTTPServer(('127.0.0.1',0),H)
threading.Thread(target=srv.serve_forever,daemon=True).start()
url=f'http://127.0.0.1:{srv.server_port}'
with sync_playwright() as pw:
    b=pw.chromium.launch(headless=True)
    for tag in ['mid','upright','sit']:
        p=b.new_page(viewport={'width':720,'height':960})
        p.goto(f"{url}/bake_seq?pose=/poses/pose_{tag}.json&avatar=boxeador&fps=1&ui=0", wait_until='domcontentloaded', timeout=180000)
        p.wait_for_function('() => window.__BAKE_READY__ || window.__BAKE_ERROR__', timeout=240000)
        try: p.evaluate('() => window.__bakeSeqStep && window.__bakeSeqStep()')
        except Exception: pass
        out=p.evaluate(M)
        print('=====', tag)
        print('  SMPL collar->sh elev/az L:', out['smplElevAzL'], ' R:', out['smplElevAzR'])
        print('  dirs avatar L/R:', out['avatarDirL'], out['avatarDirR'])
        print('  dirs smpl   L/R:', out['smplDirL'], out['smplDirR'])
        print('  NLF spine3->neck vs neck->head kink:', out['nlfSpine3Neck_vs_NeckHead'])
        print('  AVATAR spine2->neck vs neck->head kink:', out['avSpine2Neck_vs_NeckHead'])
        print('  rest neck dir:', out['restNeckDir'])
        p.close()
    b.close()
srv.shutdown()

