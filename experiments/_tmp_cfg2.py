import json, sys, threading, math
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

# Full re-solve using same API as bake_seq, with optional patches applied in-page.
APPLY = r"""
async (cfg) => {
  const THREE = window.__BAKE_THREE__;
  const av = window.__BAKE_AVATAR__;
  const rig = window.__BAKE_RIG__;
  const S = await import('/static/mikapo_mixamo_solver.js');
  const q = new URLSearchParams(location.search);
  const data = await fetch(q.get('pose')).then(r=>r.json());

  // rebuild a clean frame payload like bake_seq
  const f = Array.isArray(data.frames) ? data.frames[0] : data;
  // pose_*.json structure from bone_crook
  const joints = f.joints || data.joints;
  const aux_smpl = f.aux_smpl || data.aux_smpl;
  const nameToIndex = window.__BAKE_NAME_TO_INDEX__ || null;

  // helpers from bake page globals? reimplement minimal viewer convert
  const toViewer = (js) => js.map(p => [p[0], p[1], p[2]]); // already viewer?
  // bone_crook poses are already in viewer space for joints? check bake_seq toViewerSpace
  const pose = joints.map(p => Array.isArray(p) ? p.slice(0,3) : [p.x,p.y,p.z]);

  const aux = S.auxFromSmpl(aux_smpl, true);
  const footDirections = S.footDirectionsFromSmplAux(aux);
  const headForward = S.headForwardFromSmplAux(aux);

  // joint index map
  const JI = window.JOINT_INDEX || {
    pelvis:0,left_hip:1,right_hip:2,spine1:3,left_knee:4,right_knee:5,spine2:6,
    left_ankle:7,right_ankle:8,spine3:9,left_foot:10,right_foot:11,neck:12,
    left_collar:13,right_collar:14,head:15,left_shoulder:16,right_shoulder:17,
    left_elbow:18,right_elbow:19,left_wrist:20,right_wrist:21,left_hand:22,right_hand:23
  };

  // reset filters if available
  if (S.resetRetargetFilters) S.resetRetargetFilters(rig);
  const motion = S.createAvatarMotion();
  S.resetAvatarMotion(av, motion);

  // opts
  const baseOpts = {palmEnabled:true, aimOnly:false, negateAcrossLeft:true, negateAcrossRight:false};
  Object.assign(baseOpts, cfg.opts||{});
  S.setHandRetargetOpts(baseOpts);

  // optional: disable acute by patching? can't easily.
  // useWitness
  S.updateAvatarPose({
    model: av,
    rig,
    pose,
    nameToIndex: JI,
    motion,
    aux,
    footDirections,
    headForward,
    allowFeet: true,
    footMode: 'yawFromDir',
    plantGround: true,
    groundY: 0,
    timestampMs: 5000,
    useWitness: cfg.useWitness !== false,
    useCollarShoulders: true,
    fitPalm: !!cfg.fitPalm,
  });
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

  const ang = (a,b)=>+(a.angleTo(b)*180/Math.PI).toFixed(1);
  const mir = (v)=>new THREE.Vector3(-v.x,v.y,v.z);
  const arr=(v)=>v.toArray().map(x=>+x.toFixed(3));

  // NLF elbow hinge = upper x fore (bend plane normal)
  const hinge = (side) => {
    const sh=aux[side+'_shoulder'], el=aux[side+'_elbow'], wr=aux[side+'_wrist'];
    const u=el.clone().sub(sh).normalize();
    const f=wr.clone().sub(el).normalize();
    const h=new THREE.Vector3().crossVectors(u,f);
    if (h.lengthSq()<1e-8) return null;
    return h.normalize();
  };
  const HL=hinge('left'), HR=hinge('right');

  // live bone dir after solve
  const liveDir = (name) => {
    const r=rig.bones.get(name);
    const c=r.child;
    if(!c) return null;
    const a=r.bone.getWorldPosition(new THREE.Vector3());
    const b=c.getWorldPosition(new THREE.Vector3());
    return b.sub(a).normalize();
  };

  // palm truth and live
  const truthPalm = (side) => {
    const w=aux[side+'_wrist'], i=aux[side+'_index'], p=aux[side+'_pinky'];
    const fwd=i.clone().add(p).multiplyScalar(0.5).sub(w).normalize();
    const across=p.clone().sub(i).normalize();
    const n=new THREE.Vector3().crossVectors(fwd, across).normalize();
    return {fwd, across, n};
  };
  const livePalm = (handName) => {
    const r=rig.bones.get(handName);
    const qw=r.bone.getWorldQuaternion(new THREE.Quaternion());
    const restQ=rootQ.clone().multiply(r.restQuaternionInRoot);
    const dqw=qw.clone().multiply(restQ.clone().invert());
    const dirW=r.restDirectionInRoot.clone().applyQuaternion(rootQ).applyQuaternion(dqw).normalize();
    const acrossW=r.restAcrossInRoot.clone().applyQuaternion(rootQ).applyQuaternion(dqw);
    acrossW.addScaledVector(dirW,-acrossW.dot(dirW)).normalize();
    const n=new THREE.Vector3().crossVectors(dirW, acrossW).normalize();
    return {dirW, acrossW, n};
  };

  const TL=truthPalm('left'), TR=truthPalm('right');
  const LL=livePalm('leftHand'), LR=livePalm('rightHand');
  const err = (ln, tn) => Math.min(ang(ln,tn), ang(ln, tn.clone().negate()));

  // rest witness
  const rw = (name) => {
    const r=rig.bones.get(name);
    return r.restWitnessInRoot ? arr(r.restWitnessInRoot) : null;
  };

  return {
    twist: {
      Arm:[twistOf('leftArm'), twistOf('rightArm')],
      Fore:[twistOf('leftForeArm'), twistOf('rightForeArm')],
      Hand:[twistOf('leftHand'), twistOf('rightHand')],
    },
    hinge: {
      L: HL&&arr(HL), R: HR&&arr(HR),
      L_vs_mirR: HL&&HR ? ang(HL, mir(HR)) : null,
      L_vs_negMirR: HL&&HR ? ang(HL, mir(HR).negate()) : null,
    },
    palmErr: {L: err(LL.n, TL.n), R: err(LR.n, TR.n)},
    palmErrRaw: {L: ang(LL.n, TL.n), R: ang(LR.n, TR.n)},
    acrossErr: {L: err(LL.acrossW, TL.across), R: err(LR.acrossW, TR.across)},
    liveDirs: {
      Larm: arr(liveDir('leftArm')), Rarm: arr(liveDir('rightArm')),
      Lfore: arr(liveDir('leftForeArm')), Rfore: arr(liveDir('rightForeArm')),
    },
    restWitness: {L: rw('leftArm'), R: rw('rightArm')},
    restAcross: {
      L: arr(rig.bones.get('leftForeArm').restAcrossInRoot),
      R: arr(rig.bones.get('rightForeArm').restAcrossInRoot),
      L_vs_negMirR: (()=>{
        const L=rig.bones.get('leftForeArm').restAcrossInRoot;
        const R=rig.bones.get('rightForeArm').restAcrossInRoot;
        return ang(L, mir(R).negate());
      })(),
    },
    truthAcrossMirror: ang(TL.across, mir(TR.across)),
    opts: S.getHandRetargetOpts(),
  };
}
"""

cfgs = [
  {"name":"baseline", "opts":{"negateAcrossLeft":True,"negateAcrossRight":False}},
  {"name":"both_pure", "opts":{"negateAcrossLeft":False,"negateAcrossRight":False}},
  {"name":"swap", "opts":{"negateAcrossLeft":False,"negateAcrossRight":True}},
  {"name":"no_wit", "opts":{"negateAcrossLeft":True,"negateAcrossRight":False}, "useWitness": False},
  {"name":"aim_only", "opts":{"aimOnly":True,"negateAcrossLeft":True,"negateAcrossRight":False}},
]

# also inspect pose joint layout quickly
import json as _j
pose=_j.loads((OUT/"pose_mid.json").read_text(encoding="utf-8"))
print("pose keys", pose.keys() if isinstance(pose,dict) else type(pose))
if isinstance(pose,dict):
    if "frames" in pose:
        print("nframes", len(pose["frames"]), "f0 keys", pose["frames"][0].keys())
    else:
        print("top keys sample", list(pose.keys())[:30])
        if "joints" in pose: print("njoints", len(pose["joints"]))
        if "aux_smpl" in pose: print("aux keys", list(pose["aux_smpl"].keys())[:20])

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
        err=p.evaluate("() => window.__BAKE_ERROR__")
        if err: print("ERR", err)
        # expose JOINT_INDEX if on page
        p.evaluate("""() => {
          // pull from module scope if possible - bake_seq may not expose
          window.__POSE_TAG__ = new URLSearchParams(location.search).get('pose');
        }""")
        for cfg in cfgs:
            try:
                out=p.evaluate(APPLY, cfg)
                t=out["twist"]
                print(f"  {cfg['name']:10} Arm {t['Arm']} Fore {t['Fore']} Hand {t['Hand']} palmErr {out['palmErr']} acrossErr {out['acrossErr']}")
                if cfg['name']=='baseline':
                    print(f"             hinge L/R mir {out['hinge']} truthAcrossMir {out['truthAcrossMirror']} restA {out['restAcross']['L_vs_negMirR']}")
                    print(f"             restWit L/R {out['restWitness']}")
            except Exception as e:
                print("  FAIL", cfg["name"], e)
        p.close()
    b.close()
srv.shutdown()
