import json, sys, threading
from http.server import ThreadingHTTPServer
from pathlib import Path
import numpy as np
from playwright.sync_api import sync_playwright
sys.path[:0]=['scripts']
from check_palm_fidelity import Handler

LAB=Path('.').resolve()
OUT=LAB/'experiments/bone_crook'
frames=json.loads((OUT/'frames.json').read_text())

class H(Handler):
    def translate_path(self, path):
        from urllib.parse import unquote, urlparse
        route=unquote(urlparse(path).path)
        if route.startswith('/poses/'):
            return str(OUT/route[len('/poses/'):])
        return super().translate_path(route)

# Measure per-bone twist contribution: aim-only (no witness, no palm) vs witness vs witness+palm
DUMP = """
async (variant) => {
  const THREE = window.__BAKE_THREE__;
  const av = window.__BAKE_AVATAR__;
  const rig = window.__BAKE_RIG__;
  const S = await import('/static/mikapo_mixamo_solver.js');
  // replay the current frame under each variant by re-running updateAvatarPose
  // We cannot replay easily; instead measure current pose then compute what each
  // path WOULD give for the right forearm/hand twist relative to rest.
  const inv = av.getWorldQuaternion(new THREE.Quaternion()).invert();
  const twistOf = (name) => {
    const r = rig.bones.get(name);
    if (!r) return null;
    // residual rotation about bone axis vs rest, in degrees
    const q = r.bone.getWorldQuaternion(new THREE.Quaternion());
    const restQ = av.getWorldQuaternion(new THREE.Quaternion()).multiply(r.restQuaternionInRoot);
    const dq = restQ.clone().invert().multiply(q);
    // decompose: swing-twist around bone axis
    const axis = new THREE.Vector3(0,1,0).applyQuaternion(restQ).normalize();
    const v = new THREE.Vector3(dq.x, dq.y, dq.z);
    const proj = v.dot(axis);
    const twistQ = new THREE.Quaternion(axis.x*proj, axis.y*proj, axis.z*proj, dq.w).normalize();
    const ang = 2*Math.acos(Math.min(1,Math.abs(twistQ.w)))*180/Math.PI;
    const sign = proj >= 0 ? 1 : -1;
    return +(sign*ang).toFixed(1);
  };
  return {
    variant,
    leftArm: twistOf('leftArm'), leftForeArm: twistOf('leftForeArm'), leftHand: twistOf('leftHand'),
    rightArm: twistOf('rightArm'), rightForeArm: twistOf('rightForeArm'), rightHand: twistOf('rightHand'),
  };
}
"""

# To isolate contributions, patch the solver at runtime via URL variants is hard;
# simpler: measure current (witness+palm) pose, then re-evaluate updateAvatarPose
# with useWitness=false and palmEnabled=false via module opts, on the same frame.
DUMP2 = """
async () => {
  const THREE = window.__BAKE_THREE__;
  const av = window.__BAKE_AVATAR__;
  const rig = window.__BAKE_RIG__;
  const S = await import('/static/mikapo_mixamo_solver.js');
  const out = {};
  const measure = (label) => {
    av.updateWorldMatrix(true,true);
    const twistOf = (name) => {
      const r = rig.bones.get(name);
      if (!r) return null;
      const q = r.bone.getWorldQuaternion(new THREE.Quaternion());
      const restQ = av.getWorldQuaternion(new THREE.Quaternion()).multiply(r.restQuaternionInRoot);
      const dq = restQ.clone().invert().multiply(q);
      const axis = new THREE.Vector3(0,1,0).applyQuaternion(restQ).normalize();
      const v = new THREE.Vector3(dq.x, dq.y, dq.z);
      const proj = v.dot(axis);
      const twistQ = new THREE.Quaternion(axis.x*proj, axis.y*proj, axis.z*proj, dq.w).normalize();
      const ang = 2*Math.acos(Math.min(1,Math.abs(twistQ.w)))*180/Math.PI;
      return +(ang*(proj>=0?1:-1)).toFixed(1);
    };
    out[label] = {
      leftArm: twistOf('leftArm'), leftForeArm: twistOf('leftForeArm'), leftHand: twistOf('leftHand'),
      rightArm: twistOf('rightArm'), rightForeArm: twistOf('rightForeArm'), rightHand: twistOf('rightHand'),
    };
  };
  // frame data comes from the bake_seq page state: re-solve with variants.
  // We need the pose+aux; bake_seq stores them on window? Check globals.
  const keys = Object.keys(window).filter(k=>k.startsWith('__BAKE'));
  out._keys = keys;
  measure('as_loaded');
  return out;
}
"""

srv=ThreadingHTTPServer(('127.0.0.1',0),H)
threading.Thread(target=srv.serve_forever,daemon=True).start()
url=f'http://127.0.0.1:{srv.server_port}'
with sync_playwright() as pw:
    b=pw.chromium.launch(headless=True)
    p=b.new_page(viewport={'width':720,'height':960})
    p.goto(f"{url}/bake_seq?pose=/poses/pose_upright.json&avatar=boxeador&side=1&fps=1&ui=0", wait_until='domcontentloaded', timeout=180000)
    p.wait_for_function('() => window.__BAKE_READY__ || window.__BAKE_ERROR__', timeout=240000)
    try: p.evaluate('() => window.__bakeSeqStep && window.__bakeSeqStep()')
    except Exception: pass
    out=p.evaluate(DUMP2)
    print(json.dumps(out, indent=1))
    b.close()
srv.shutdown()
