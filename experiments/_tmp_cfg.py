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

# Compare configs by monkeypatching via dynamic import of solver snapshot? We'll re-apply pose with evaluate hacks.
M = r"""
async (cfg) => {
  const THREE = window.__BAKE_THREE__;
  const av = window.__BAKE_AVATAR__;
  const rig = window.__BAKE_RIG__;
  // fresh module each time? cached. Use setHandRetargetOpts and re-call updateAvatarPose
  const S = await import('/static/mikapo_mixamo_solver.js');
  const q = new URLSearchParams(location.search);
  const data = await fetch(q.get('pose')).then(r=>r.json());
  const aux = S.auxFromSmpl(data.aux_smpl, true);

  // reset bones to rest
  for (const [,r] of rig.bones) {
    r.bone.quaternion.copy(r.restLocalQuaternion);
    r.bone.position.copy(r.restLocalPosition);
  }
  av.updateWorldMatrix(true,true);

  if (cfg.opts) S.setHandRetargetOpts(cfg.opts);

  // optional monkeypatch
  const origAcross = S.computeHandPalmAxes;
  if (cfg.mode === 'no_flags') {
    // wrap by temporarily zeroing flags
    S.setHandRetargetOpts({negateAcrossLeft:false, negateAcrossRight:false, palmEnabled:true, aimOnly:false});
  } else if (cfg.mode === 'swap_flags') {
    S.setHandRetargetOpts({negateAcrossLeft:false, negateAcrossRight:true, palmEnabled:true, aimOnly:false});
  } else if (cfg.mode === 'both_neg') {
    S.setHandRetargetOpts({negateAcrossLeft:true, negateAcrossRight:true, palmEnabled:true, aimOnly:false});
  } else if (cfg.mode === 'both_pure') {
    S.setHandRetargetOpts({negateAcrossLeft:false, negateAcrossRight:false, palmEnabled:true, aimOnly:false});
  } else if (cfg.mode === 'aim_only') {
    S.setHandRetargetOpts({palmEnabled:true, aimOnly:true});
  } else {
    S.setHandRetargetOpts({negateAcrossLeft:true, negateAcrossRight:false, palmEnabled:true, aimOnly:false});
  }

  // useWitness override: call update with options if supported
  const body = data.body || data.joints || null;
  // bake_seq exposes solver entry
  if (window.__BAKE_APPLY__) {
    await window.__BAKE_APPLY__();
  } else {
    // fallback: updateAvatarPose
    const joints = data.joints_viewer || data.lab_joints || data.joints;
    S.updateAvatarPose(av, joints, {
      rig,
      aux,
      timestampMs: 1000,
      useWitness: cfg.useWitness !== false,
      useCollarShoulders: true,
    });
  }
  av.updateWorldMatrix(true,true);
  const rootQ = av.getWorldQuaternion(new THREE.Quaternion());

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

  // truth palm normal from aux: n = fwd x (pinky-index)  -- anatomical, same both sides
  // For mirrored consistency of facing: compare n_L to mir(n_R)
  const truth = (side) => {
    const w=aux[side+'_wrist'], i=aux[side+'_index'], p=aux[side+'_pinky'];
    const fwd=i.clone().add(p).multiplyScalar(0.5).sub(w).normalize();
    const across=p.clone().sub(i).normalize();
    const n=new THREE.Vector3().crossVectors(fwd, across).normalize();
    return {fwd, across, n};
  };
  // live palm from hand bone: use middle finger bone if present else restAcross live
  const liveN = (handName) => {
    const r = rig.bones.get(handName);
    const q = r.bone.getWorldQuaternion(new THREE.Quaternion());
    const restQ = rootQ.clone().multiply(r.restQuaternionInRoot);
    const dqw = q.clone().multiply(restQ.clone().invert());
    const acrossW = r.restAcrossInRoot.clone().applyQuaternion(rootQ).applyQuaternion(dqw);
    const dirW = r.restDirectionInRoot.clone().applyQuaternion(rootQ).applyQuaternion(dqw).normalize();
    acrossW.addScaledVector(dirW, -acrossW.dot(dirW)).normalize();
    // palm normal consistent with rest: dir x across (same construction as truth fwd x across if across is medial and dir~fwd)
    // Actually rest palm: fingers along dir, across medial => normal = dir x across
    const n = new THREE.Vector3().crossVectors(dirW, acrossW).normalize();
    return {n, acrossW, dirW};
  };

  const ang = (a,b)=>+(a.angleTo(b)*180/Math.PI).toFixed(1);
  const mir = (v)=>new THREE.Vector3(-v.x,v.y,v.z);

  const TL=truth('left'), TR=truth('right');
  const LL=liveN('leftHand'), LR=liveN('rightHand');

  // error vs truth: min(ang(n,t), ang(n,-t)) because restAcross sign may invert normal
  const errN = (live, t) => Math.min(ang(live,t), ang(live,t.clone().negate()));

  // also compare live normals using sign that matches truth better
  const signedErr = (live, t) => {
    const e1=ang(live,t), e2=ang(live,t.clone().negate());
    return e1<=e2 ? e1 : e2;
  };

  return {
    twist: {
      Arm:[twistOf('leftArm'), twistOf('rightArm')],
      Fore:[twistOf('leftForeArm'), twistOf('rightForeArm')],
      Hand:[twistOf('leftHand'), twistOf('rightHand')],
    },
    palmErrN: { L: signedErr(LL.n, TL.n), R: signedErr(LR.n, TR.n) },
    // if we flip live normal by rest convention, raw ang
    palmErrN_raw: { L: ang(LL.n, TL.n), R: ang(LR.n, TR.n) },
    liveMirrorN: ang(LL.n, mir(LR.n)),
    liveMirrorNneg: ang(LL.n, mir(LR.n).negate()),
    truthMirrorN: ang(TL.n, mir(TR.n)),
    truthMirrorNneg: ang(TL.n, mir(TR.n).negate()),
    // arm elev
    elev: (()=>{
      const e=(side)=>{
        const sh=aux[side+'_shoulder'], el=aux[side+'_elbow'];
        const d=el.clone().sub(sh).normalize();
        return +(Math.asin(Math.max(-1,Math.min(1,d.y)))*180/Math.PI).toFixed(1);
      };
      return [e('left'), e('right')];
    })(),
  };
}
"""

cfgs = [
  {"name":"baseline_flags", "mode":"baseline"},
  {"name":"both_pure", "mode":"both_pure"},
  {"name":"both_neg", "mode":"both_neg"},
  {"name":"swap_flags", "mode":"swap_flags"},
  {"name":"aim_only", "mode":"aim_only"},
  {"name":"no_witness", "mode":"baseline", "useWitness": False},
]

srv=ThreadingHTTPServer(("127.0.0.1",0),H)
threading.Thread(target=srv.serve_forever,daemon=True).start()
url=f"http://127.0.0.1:{srv.server_port}"
with sync_playwright() as pw:
    b=pw.chromium.launch(headless=True)
    for tag in ["upright","sit","mid"]:
        print("####", tag)
        p=b.new_page(viewport={"width":720,"height":960})
        p.goto(f"{url}/bake_seq?pose=/poses/pose_{tag}.json&avatar=boxeador&fps=1&ui=0", wait_until="domcontentloaded", timeout=180000)
        p.wait_for_function("() => window.__BAKE_READY__ || window.__BAKE_ERROR__", timeout=240000)
        try: p.evaluate("() => window.__bakeSeqStep && window.__bakeSeqStep()")
        except Exception: pass
        for cfg in cfgs:
            out=p.evaluate(M, cfg)
            t=out["twist"]
            print(f"  {cfg['name']:14} Arm {t['Arm']} Fore {t['Fore']} Hand {t['Hand']}  palmErr {out['palmErrN']} raw {out['palmErrN_raw']}  liveMirN {out['liveMirrorN']}/{out['liveMirrorNneg']} truthMirN {out['truthMirrorN']}/{out['truthMirrorNneg']}")
        p.close()
    b.close()
srv.shutdown()
