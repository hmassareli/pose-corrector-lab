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

# Re-solve the same frame under 3 variants by re-importing the solver module and
# calling updateAvatarPose with different flags, using the pose/aux the page loaded.
DUMP = """
async () => {
  const THREE = window.__BAKE_THREE__;
  const av = window.__BAKE_AVATAR__;
  const rig = window.__BAKE_RIG__;
  const S = await import('/static/mikapo_mixamo_solver.js');
  // pull pose+aux back from the page: bake_seq fetched pose JSON; refetch it here
  const q = new URLSearchParams(location.search);
  const data = await fetch(q.get('pose')).then(r=>r.json());
  const lowestAnkle = Math.min(data.joints[5][1], data.joints[6][1]);
  const pose = data.joints.map((p)=>[p[0], -p[1]+lowestAnkle, -p[2]]);
  const JOINT_NAMES = ['pelvis','left_hip','right_hip','left_knee','right_knee','left_ankle','right_ankle','spine','left_shoulder','right_shoulder','left_elbow','right_elbow','left_wrist','right_wrist','neck','head'];
  const nameToIndex = Object.fromEntries(JOINT_NAMES.map((n,i)=>[n,i]));
  const aux = S.auxFromSmpl(data.aux_smpl, true);
  const footDirections = S.footDirectionsFromSmplAux(aux);
  const headForward = S.headForwardFromSmplAux(aux);

  const twistOf = (name) => {
    const r = rig.bones.get(name);
    if (!r) return null;
    const q = r.bone.getWorldQuaternion(new THREE.Quaternion());
    const restQ = av.getWorldQuaternion(new THREE.Quaternion()).multiply(r.restQuaternionInRoot);
    const dq = restQ.clone().invert().multiply(q);
    const axis = r.restDirectionInRoot.clone().applyQuaternion(av.getWorldQuaternion(new THREE.Quaternion())).normalize();
    const v = new THREE.Vector3(dq.x, dq.y, dq.z);
    const proj = v.dot(axis);
    const twistQ = new THREE.Quaternion(axis.x*proj, axis.y*proj, axis.z*proj, dq.w).normalize();
    const ang = 2*Math.acos(Math.min(1,Math.abs(twistQ.w)))*180/Math.PI;
    return +(ang*(proj>=0?1:-1)).toFixed(1);
  };
  const grab = (label) => ({
    label,
    leftArm: twistOf('leftArm'), leftForeArm: twistOf('leftForeArm'), leftHand: twistOf('leftHand'),
    rightArm: twistOf('rightArm'), rightForeArm: twistOf('rightForeArm'), rightHand: twistOf('rightHand'),
  });

  const results = [];
  const run = async (label, opts, palm) => {
    S.setHandRetargetOpts({ palmEnabled: palm });
    S.resetAvatarMotion(av, S.createAvatarMotion());
    S.resetRetargetFilters(rig);
    S.updateAvatarPose({
      model: av, rig, pose, nameToIndex, motion: S.createAvatarMotion(),
      aux, footDirections, headForward,
      allowFeet: true, footMode: 'yawFromDir', plantGround: true, groundY: 0,
      timestampMs: null, ...opts,
    });
    av.updateWorldMatrix(true, true);
    results.push(grab(label));
    // also report the palm axes + forearm dir obs for diagnosis
  };
  await run('witness+palm (atual)', { useWitness: true }, true);
  // palm observability: angle between across and forearm axis
  const fore = rig.bones.get('leftForeArm');
  const p0 = fore.bone.getWorldPosition(new THREE.Vector3());
  const p1 = fore.child.getWorldPosition(new THREE.Vector3());
  const foreDir = p1.clone().sub(p0).normalize();
  const axesL = S.computeHandPalmAxes(aux, 'left');
  const axesR = S.computeHandPalmAxes(aux, 'right');
  const obs = (axes) => {
    if (!axes?.across) return null;
    const dot = Math.abs(axes.across.clone().dot(foreDir));
    return +(Math.sqrt(Math.max(0,1-dot*dot))).toFixed(3); // sin(angle)
  };
  await run('so witness', { useWitness: true }, false);
  await run('sem witness, com palm', { useWitness: false }, true);
  await run('sem witness, sem palm', { useWitness: false }, false);
  S.setHandRetargetOpts({ palmEnabled: true });
  return { results, obs: { left: obs(axesL), right: obs(axesR) },
           palmL: axesL ? { fwd: axesL.forward.toArray().map(v=>+v.toFixed(2)), across: axesL.across ? axesL.across.toArray().map(v=>+v.toFixed(2)) : null } : null };
}
"""

srv=ThreadingHTTPServer(('127.0.0.1',0),H)
threading.Thread(target=srv.serve_forever,daemon=True).start()
url=f'http://127.0.0.1:{srv.server_port}'
with sync_playwright() as pw:
    b=pw.chromium.launch(headless=True)
    for tag in ['upright','sit']:
        p=b.new_page(viewport={'width':720,'height':960})
        p.goto(f"{url}/bake_seq?pose=/poses/pose_{tag}.json&avatar=boxeador&side=1&fps=1&ui=0", wait_until='domcontentloaded', timeout=180000)
        p.wait_for_function('() => window.__BAKE_READY__ || window.__BAKE_ERROR__', timeout=240000)
        try: p.evaluate('() => window.__bakeSeqStep && window.__bakeSeqStep()')
        except Exception: pass
        out=p.evaluate(DUMP)
        print('=====', tag)
        for r in out['results']:
            print(f"  {r['label']:<24} L arm={r['leftArm']:>7} fore={r['leftForeArm']:>7} hand={r['leftHand']:>7} | R arm={r['rightArm']:>7} fore={r['rightForeArm']:>7} hand={r['rightHand']:>7}")
        print('  palm obs (sin angulo across vs forearm): L', out['obs']['left'], ' R', out['obs']['right'])
        print('  palm L fwd', out['palmL']['fwd'], 'across', out['palmL']['across'])
        p.close()
    b.close()
srv.shutdown()


