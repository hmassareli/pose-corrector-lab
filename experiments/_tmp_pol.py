import json, sys, threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from playwright.sync_api import sync_playwright
sys.path[:0]=["scripts"]
from check_palm_fidelity import Handler

LAB=Path(".").resolve(); OUT=LAB/"experiments/bone_crook"

class H(Handler):
    def translate_path(self, path):
        from urllib.parse import unquote, urlparse
        route=unquote(urlparse(path).path)
        if route.startswith("/poses/"):
            return str(OUT/route[len("/poses/"):])
        return super().translate_path(route)

M = r"""
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

  const v = (a) => new THREE.Vector3().fromArray(a);
  const arr = (vv) => vv.toArray().map(x=>+x.toFixed(3));
  const ang = (a,b) => +(a.angleTo(b)*180/Math.PI).toFixed(1);
  const mirX = (vv) => new THREE.Vector3(-vv.x, vv.y, vv.z);

  const palmRaw = (side) => {
    const w=aux[side+'_wrist'], i=aux[side+'_index'], p=aux[side+'_pinky'];
    const el=aux[side+'_elbow'];
    if(!w||!i||!p) return null;
    const fwd = i.clone().add(p).multiplyScalar(0.5).sub(w).normalize();
    const across = p.clone().sub(i).normalize(); // pure pinky-index
    const n = new THREE.Vector3().crossVectors(fwd, across).normalize();
    const fore = (el && w) ? w.clone().sub(el).normalize() : null;
    return {fwd, across, n, fore};
  };

  // After aim-align only, what is aligned restAcross (same as rotateBoneWithAcross start)
  const alignedRestAcross = (boneName, liveDirRoot) => {
    const rest = rig.bones.get(boneName);
    const restDirW = rest.restDirectionInRoot.clone().applyQuaternion(rootQ).normalize();
    const liveDirW = liveDirRoot.clone().normalize().applyQuaternion(rootQ).normalize();
    const align = new THREE.Quaternion().setFromUnitVectors(restDirW, liveDirW);
    const a = rest.restAcrossInRoot.clone().applyQuaternion(rootQ).applyQuaternion(align);
    a.addScaledVector(liveDirW, -a.dot(liveDirW));
    return a.normalize();
  };

  const twistOf = (name) => {
    const r = rig.bones.get(name);
    if (!r) return null;
    const q = r.bone.getWorldQuaternion(new THREE.Quaternion());
    const restQ = rootQ.clone().multiply(r.restQuaternionInRoot);
    const dq = restQ.clone().invert().multiply(q);
    const axis = r.restDirectionInRoot.clone().applyQuaternion(rootQ).normalize();
    const vv = new THREE.Vector3(dq.x, dq.y, dq.z);
    const proj = vv.dot(axis);
    const twistQ = new THREE.Quaternion(axis.x*proj, axis.y*proj, axis.z*proj, dq.w).normalize();
    const aa = 2*Math.acos(Math.min(1,Math.abs(twistQ.w)))*180/Math.PI;
    return +(aa*(proj>=0?1:-1)).toFixed(1);
  };

  // palm normal of rendered bone: bone's +Y or from restAcross live
  const livePalmN = (handName) => {
    const r = rig.bones.get(handName);
    // use restAcross rotated into live, cross with bone dir as normal proxy
    const q = r.bone.getWorldQuaternion(new THREE.Quaternion());
    const restQ = rootQ.clone().multiply(r.restQuaternionInRoot);
    const dqr = q.clone().multiply(restQ.clone().invert());
    const acrossW = r.restAcrossInRoot.clone().applyQuaternion(rootQ).applyQuaternion(dqr).normalize();
    const dirW = r.restDirectionInRoot.clone().applyQuaternion(rootQ).applyQuaternion(dqr).normalize();
    // better get actual child aim as dir
    return { acrossW: arr(acrossW), dirW: arr(dirW), n: arr(new THREE.Vector3().crossVectors(dirW, acrossW).normalize()) };
  };

  const sides = {};
  for (const side of ['left','right']) {
    const raw = palmRaw(side);
    const fore = side==='left'?'leftForeArm':'rightForeArm';
    const hand = side==='left'?'leftHand':'rightHand';
    const arm = side==='left'?'leftArm':'rightArm';
    const el=aux[side+'_elbow'], wr=aux[side+'_wrist'], sh=aux[side+'_shoulder'];
    const foreDir = wr.clone().sub(el);
    const upperDir = el.clone().sub(sh);
    const aligned = alignedRestAcross(fore, foreDir);
    const pure = raw.across.clone();
    const neg = pure.clone().negate();
    // dots in world after projecting pure onto plane perp live fore
    const liveDirW = foreDir.clone().normalize().applyQuaternion(rootQ).normalize();
    const projA = (a) => {
      const w = a.clone().applyQuaternion(rootQ);
      w.addScaledVector(liveDirW, -w.dot(liveDirW));
      return w.normalize();
    };
    const pPure = projA(pure);
    const pNeg = projA(neg);
    sides[side] = {
      angAligned_vs_pure: ang(aligned, pPure),
      angAligned_vs_neg: ang(aligned, pNeg),
      wouldAcuteFlip_pure: aligned.dot(pPure) < 0,
      wouldAcuteFlip_neg: aligned.dot(pNeg) < 0,
      chooseBetter: (aligned.dot(pPure) >= aligned.dot(pNeg)) ? 'pure' : 'neg',
      // which matches rest polarity better (smaller acute angle)
      restDotPure: +aligned.dot(pPure).toFixed(3),
      restDotNeg: +aligned.dot(pNeg).toFixed(3),
      palmN_pure: arr(raw.n),
      palmN_neg: arr(raw.n.clone().negate()),
      // current opts
      twistArm: twistOf(arm),
      twistFore: twistOf(fore),
      twistHand: twistOf(hand),
      live: livePalmN(hand),
    };
  }

  // mirror compare palm normals of DATA pure
  const Lp = palmRaw('left'), Rp = palmRaw('right');
  const dataMirror = {
    across_L_vs_mirR: ang(Lp.across, mirX(Rp.across)),
    across_L_vs_negMirR: ang(Lp.across, mirX(Rp.across).negate()),
    n_L_vs_mirR: ang(Lp.n, mirX(Rp.n)),
    n_L_vs_negMirR: ang(Lp.n, mirX(Rp.n).negate()),
  };

  // after current solve, live palm across mirror
  const Ll = livePalmN('leftHand'), Rl = livePalmN('rightHand');
  const liveMirror = {
    across_L_vs_mirR: ang(v(Ll.acrossW), mirX(v(Rl.acrossW))),
    across_L_vs_negMirR: ang(v(Ll.acrossW), mirX(v(Rl.acrossW)).negate()),
    n_L_vs_mirR: ang(v(Ll.n), mirX(v(Rl.n))),
    n_L_vs_negMirR: ang(v(Ll.n), mirX(v(Rl.n)).negate()),
  };

  // structural choice: per-side pick sign by max dot with aligned rest (no global flags)
  const structural = {};
  for (const side of ['left','right']) {
    structural[side] = sides[side].chooseBetter;
  }

  return { sides, dataMirror, liveMirror, structural, opts: S.getHandRetargetOpts() };
}
"""

srv=ThreadingHTTPServer(("127.0.0.1",0),H)
threading.Thread(target=srv.serve_forever,daemon=True).start()
url=f"http://127.0.0.1:{srv.server_port}"
with sync_playwright() as pw:
    b=pw.chromium.launch(headless=True)
    for tag in ["upright","sit","mid"]:
        p=b.new_page(viewport={"width":720,"height":960})
        p.goto(f"{url}/bake_seq?pose=/poses/pose_{tag}.json&avatar=boxeador&fps=1&ui=0", wait_until="domcontentloaded", timeout=180000)
        p.wait_for_function("() => window.__BAKE_READY__ || window.__BAKE_ERROR__", timeout=240000)
        try: p.evaluate("() => window.__bakeSeqStep && window.__bakeSeqStep()")
        except Exception: pass
        out=p.evaluate(M)
        print("==", tag)
        print(json.dumps(out, indent=2))
        p.close()
    b.close()
srv.shutdown()
