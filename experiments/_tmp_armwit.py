import json, sys, threading, shutil
from http.server import ThreadingHTTPServer
from pathlib import Path
from playwright.sync_api import sync_playwright
sys.path[:0]=["scripts"]
from check_palm_fidelity import Handler

LAB=Path(".").resolve(); OUT=LAB/"experiments/bone_crook"
# Prepare two solver variants served as /static/mikapo_mixamo_solver.js via query? 
# Handler serves viewer/; we'll patch a copy that forces no arm witness and one baseline.
base = (LAB/"viewer/mikapo_mixamo_solver.js").read_text(encoding="utf-8")
# force no witness: change default useWitness = true to false AND the arm loop only
no_wit = base.replace("useWitness = true,", "useWitness = false,", 1)
(LAB/"experiments/_solver_armroll_nowit.js").write_text(no_wit, encoding="utf-8")
# structural candidate later

class H(Handler):
    SOLVER = None  # path override
    def translate_path(self, path):
        from urllib.parse import unquote, urlparse
        route=unquote(urlparse(path).path)
        if route.startswith("/poses/"):
            return str(OUT/route[len("/poses/"):])
        if route.endswith("/mikapo_mixamo_solver.js") and H.SOLVER:
            return str(H.SOLVER)
        return super().translate_path(route)

M = r"""
async () => {
  const THREE = window.__BAKE_THREE__;
  const av = window.__BAKE_AVATAR__;
  const rig = window.__BAKE_RIG__;
  const S = await import('/static/mikapo_mixamo_solver.js?' + Date.now());
  const q = new URLSearchParams(location.search);
  const data = await fetch(q.get('pose')).then(r=>r.json());
  const aux = S.auxFromSmpl(data.aux_smpl, true);
  av.updateWorldMatrix(true,true);
  const rootQ = av.getWorldQuaternion(new THREE.Quaternion());

  const arr = (v) => v.toArray().map(x => +x.toFixed(3));
  const ang = (a,b) => +(a.angleTo(b)*180/Math.PI).toFixed(1);
  const mir = (v) => new THREE.Vector3(-v.x, v.y, v.z);

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

  // "biceps facing" = bone local +Y or rest witness rotated to live, projected perp to bone
  // Use restWitnessInRoot transformed by rest->live as the arm's roll reference after solve.
  // For Mixamo, restWitness was calibrated as character-forward (+Z) at rest.
  const liveRollAxis = (name) => {
    const r = rig.bones.get(name);
    if (!r?.restWitnessInRoot) return null;
    const qw = r.bone.getWorldQuaternion(new THREE.Quaternion());
    const restQ = rootQ.clone().multiply(r.restQuaternionInRoot);
    const dqw = qw.clone().multiply(restQ.clone().invert());
    const dirW = r.restDirectionInRoot.clone().applyQuaternion(rootQ).applyQuaternion(dqw).normalize();
    const witW = r.restWitnessInRoot.clone().applyQuaternion(rootQ).applyQuaternion(dqw);
    witW.addScaledVector(dirW, -witW.dot(dirW));
    if (witW.lengthSq() < 1e-8) return null;
    return witW.normalize();
  };

  // anatomical elbow hinge normal (plane of upper+fore): u x f
  // When arm hangs, hinge ~ left-right; biceps "front" is roughly character forward for both.
  const hinge = (side) => {
    const sh=aux[side+'_shoulder'], el=aux[side+'_elbow'], wr=aux[side+'_wrist'];
    const u = el.clone().sub(sh).normalize();
    const f = wr.clone().sub(el).normalize();
    const h = new THREE.Vector3().crossVectors(u, f);
    if (h.lengthSq() < 1e-10) return null;
    return h.normalize();
  };

  // angle of live roll-axis vs character forward, around bone axis — "how much is biceps rotated"
  // Also: angle of live roll vs expected forearm-perp (what witness wants)
  const sideReport = (side) => {
    const arm = side==='left' ? 'leftArm' : 'rightArm';
    const fore = side==='left' ? 'leftForeArm' : 'rightForeArm';
    const sh=aux[side+'_shoulder'], el=aux[side+'_elbow'], wr=aux[side+'_wrist'];
    const upper = el.clone().sub(sh).normalize();
    const foreD = wr.clone().sub(el).normalize();
    const r = rig.bones.get(arm);
    const liveWit = liveRollAxis(arm);
    const h = hinge(side);
    // expected witness from data: forearm projected perp upper
    const exp = foreD.clone().addScaledVector(upper, -foreD.dot(upper));
    const expN = exp.lengthSq()>1e-10 ? exp.normalize() : null;
    // rest witness in root
    const restW = r.restWitnessInRoot ? r.restWitnessInRoot.clone() : null;
    const restD = r.restDirectionInRoot.clone();
    // after shortest-arc only (no roll): restWit mapped by FromUnitVectors(restDir, liveDir)
    const rootW = rootQ;
    const restDirW = restD.clone().applyQuaternion(rootW).normalize();
    const liveDirW = upper.clone().normalize(); // already viewer/root-ish: aux is viewer space same as root if model identity
    // aux is in viewer/world; model root may not be identity. Convert live dirs to world via assuming aux already world-matched to bake.
    // bake uses same space for aux and bone world after plant.
    const align = new THREE.Quaternion().setFromUnitVectors(restDirW, liveDirW.clone().normalize());
    const shortWit = restW ? restW.clone().applyQuaternion(rootW).applyQuaternion(align) : null;
    if (shortWit) {
      shortWit.addScaledVector(liveDirW, -shortWit.dot(liveDirW));
      if (shortWit.lengthSq()>1e-10) shortWit.normalize();
    }
    const out = {
      twistArm: twistOf(arm),
      twistFore: twistOf(fore),
      twistHand: twistOf(side==='left'?'leftHand':'rightHand'),
      restWitness: restW ? arr(restW) : null,
      restDir: arr(restD),
      liveWit: liveWit ? arr(liveWit) : null,
      expWit: expN ? arr(expN) : null,
      hinge: h ? arr(h) : null,
      ang_liveWit_vs_exp: (liveWit && expN) ? ang(liveWit, expN) : null,
      ang_liveWit_vs_negExp: (liveWit && expN) ? ang(liveWit, expN.clone().negate()) : null,
      ang_shortWit_vs_exp: (shortWit && expN && shortWit.lengthSq()>0) ? ang(shortWit, expN) : null,
      // facing: angle of liveWit to world +Z (forward) and +X
      liveWit_fwd: liveWit ? +(liveWit.dot(new THREE.Vector3(0,0,1))).toFixed(3) : null,
      liveWit_up: liveWit ? +(liveWit.dot(new THREE.Vector3(0,1,0))).toFixed(3) : null,
      // bend amount (how observable witness is)
      bendDeg: +(Math.acos(Math.max(-1,Math.min(1, upper.dot(foreD))))*180/Math.PI).toFixed(1),
    };
    return out;
  };

  const L = sideReport('left');
  const R = sideReport('right');
  const Lw = liveRollAxis('leftArm');
  const Rw = liveRollAxis('rightArm');
  return {
    L, R,
    mirror: {
      liveWit_L_vs_mirR: (Lw&&Rw) ? ang(Lw, mir(Rw)) : null,
      liveWit_L_vs_negMirR: (Lw&&Rw) ? ang(Lw, mir(Rw).negate()) : null,
      restWit_L_vs_mirR: (()=>{
        const a=rig.bones.get('leftArm').restWitnessInRoot;
        const b=rig.bones.get('rightArm').restWitnessInRoot;
        return a&&b ? ang(a, mir(b)) : null;
      })(),
      restWit_L_vs_negMirR: (()=>{
        const a=rig.bones.get('leftArm').restWitnessInRoot;
        const b=rig.bones.get('rightArm').restWitnessInRoot;
        return a&&b ? ang(a, mir(b).negate()) : null;
      })(),
      twistArm_sum: +(L.twistArm + R.twistArm).toFixed(1),
      twistArm_diff: +(L.twistArm - R.twistArm).toFixed(1),
    },
  };
}
"""

def run(solver_path, label):
    H.SOLVER = Path(solver_path).resolve()
    srv=ThreadingHTTPServer(("127.0.0.1",0),H)
    threading.Thread(target=srv.serve_forever,daemon=True).start()
    url=f"http://127.0.0.1:{srv.server_port}"
    print(f"\n===== {label} ({H.SOLVER.name}) =====")
    with sync_playwright() as pw:
        b=pw.chromium.launch(headless=True)
        for tag in ["upright","sit","mid"]:
            p=b.new_page(viewport={"width":720,"height":960})
            p.goto(f"{url}/bake_seq?pose=/poses/pose_{tag}.json&avatar=boxeador&fps=1&ui=0", wait_until="domcontentloaded", timeout=180000)
            p.wait_for_function("() => window.__BAKE_READY__ || window.__BAKE_ERROR__", timeout=240000)
            err=p.evaluate("() => window.__BAKE_ERROR__")
            if err: print(tag, "ERR", err); p.close(); continue
            try: p.evaluate("() => window.__bakeSeqStep && window.__bakeSeqStep()")
            except Exception: pass
            out=p.evaluate(M)
            print(f"-- {tag}")
            print(f"   twist Arm L/R: {out['L']['twistArm']:>7} / {out['R']['twistArm']:>7}  sum={out['mirror']['twistArm_sum']} diff={out['mirror']['twistArm_diff']}")
            print(f"   twist Fore L/R: {out['L']['twistFore']:>6} / {out['R']['twistFore']:>6}")
            print(f"   bend L/R: {out['L']['bendDeg']} / {out['R']['bendDeg']}")
            print(f"   liveWit vs exp L: {out['L']['ang_liveWit_vs_exp']} (neg {out['L']['ang_liveWit_vs_negExp']})  R: {out['R']['ang_liveWit_vs_exp']} (neg {out['R']['ang_liveWit_vs_negExp']})")
            print(f"   shortWit vs exp L/R: {out['L']['ang_shortWit_vs_exp']} / {out['R']['ang_shortWit_vs_exp']}")
            print(f"   liveWit fwd/up L: {out['L']['liveWit_fwd']}/{out['L']['liveWit_up']}  R: {out['R']['liveWit_fwd']}/{out['R']['liveWit_up']}")
            print(f"   restWit: L {out['L']['restWitness']} R {out['R']['restWitness']} mir {out['mirror']['restWit_L_vs_mirR']}/neg {out['mirror']['restWit_L_vs_negMirR']}")
            print(f"   liveWit mirror L vs mirR/neg: {out['mirror']['liveWit_L_vs_mirR']} / {out['mirror']['liveWit_L_vs_negMirR']}")
            p.close()
        b.close()
    srv.shutdown()

run(LAB/"viewer/mikapo_mixamo_solver.js", "BASELINE (witness on)")
run(LAB/"experiments/_solver_armroll_nowit.js", "NO WITNESS")
