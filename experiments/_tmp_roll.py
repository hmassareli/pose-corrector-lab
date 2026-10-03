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
  const rootQ = av.getWorldQuaternion(new THREE.Quaternion());

  // twist about own bone axis vs rest (same decomposition as the fidelity script)
  const twistOf = (name) => {
    const r = rig.bones.get(name);
    if (!r) return null;
    const q = r.bone.getWorldQuaternion(new THREE.Quaternion());
    const restQ = rootQ.clone().multiply(r.restQuaternionInRoot);
    const dq = restQ.clone().invert().multiply(q);
    const axis = r.restDirectionInRoot.clone().applyQuaternion(rootQ).normalize();
    const v = new THREE.Vector3(dq.x, dq.y, dq.z);
    const proj = v.dot(axis);
    const twistQ = new THREE.Quaternion(axis.x*proj, axis.y*proj, axis.z*proj, dq.w).normalize();
    const ang = 2*Math.acos(Math.min(1,Math.abs(twistQ.w)))*180/Math.PI;
    return +(ang*(proj>=0?1:-1)).toFixed(1);
  };
  // palm axes per side: forward + across, and angle between across and forearm dir
  const palm = (side) => {
    const ax = S.computeHandPalmAxes(aux, side);
    if (!ax) return null;
    return {
      fwd: ax.forward.toArray().map(v=>+v.toFixed(2)),
      across: ax.across ? ax.across.toArray().map(v=>+v.toFixed(2)) : null,
    };
  };
  // what roll does the palm across imply, per side: angle of across projected perp to forearm dir
  const foreDir = (side) => {
    const el = aux[side+'_elbow'], wr = aux[side+'_wrist'];
    return el && wr ? wr.clone().sub(el).normalize() : null;
  };
  const palmRollAngle = (side) => {
    const ax = S.computeHandPalmAxes(aux, side);
    const fd = foreDir(side);
    if (!ax?.across || !fd) return null;
    // angle of the across relative to world-up reference frame around forearm axis
    const perp = ax.across.clone().addScaledVector(fd, -ax.across.dot(fd));
    return +(Math.atan2(perp.y, Math.hypot(perp.x, perp.z))*180/Math.PI).toFixed(1);
  };
  return {
    twist: {
      leftArm: twistOf('leftArm'), rightArm: twistOf('rightArm'),
      leftForeArm: twistOf('leftForeArm'), rightForeArm: twistOf('rightForeArm'),
      leftHand: twistOf('leftHand'), rightHand: twistOf('rightHand'),
    },
    palmL: palm('left'), palmR: palm('right'),
    palmRollL: palmRollAngle('left'), palmRollR: palmRollAngle('right'),
    // aux points for manual check
    auxIdx: {
      L: aux.left_index ? aux.left_index.toArray().map(v=>+v.toFixed(3)) : null,
      R: aux.right_index ? aux.right_index.toArray().map(v=>+v.toFixed(3)) : null,
    },
    auxPinky: {
      L: aux.left_pinky ? aux.left_pinky.toArray().map(v=>+v.toFixed(3)) : null,
      R: aux.right_pinky ? aux.right_pinky.toArray().map(v=>+v.toFixed(3)) : null,
    },
  };
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
        t=out['twist']
        print(f"== {tag}")
        print(f"   twist Arm    L/R: {t['leftArm']:>6} / {t['rightArm']:>6}")
        print(f"   twist ForeArm L/R: {t['leftForeArm']:>6} / {t['rightForeArm']:>6}   (palma/pronacao)")
        print(f"   twist Hand   L/R: {t['leftHand']:>6} / {t['rightHand']:>6}")
        print(f"   palm roll L/R: {out['palmRollL']} / {out['palmRollR']}")
        print(f"   across L: {out['palmL']['across'] if out['palmL'] else None}")
        print(f"   across R: {out['palmR']['across'] if out['palmR'] else None}")
        p.close()
    b.close()
srv.shutdown()

