import json, sys, threading, shutil
from http.server import ThreadingHTTPServer
from pathlib import Path
from playwright.sync_api import sync_playwright
sys.path[:0]=["scripts"]
from check_palm_fidelity import Handler

LAB=Path(".").resolve(); OUT=LAB/"experiments/bone_crook"
# snapshot baseline solver
src=LAB/"viewer/mikapo_mixamo_solver.js"
base=LAB/"experiments/_solver_armroll_base.js"
if not base.exists():
    shutil.copy2(src, base)
    print("snapshot", base)
else:
    print("snapshot exists", base)

class H(Handler):
    def translate_path(self, path):
        from urllib.parse import unquote, urlparse
        route=unquote(urlparse(path).path)
        if route.startswith("/poses/"):
            return str(OUT/route[len("/poses/"):])
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
  const invRoot = rootQ.clone().invert();

  const restA = (name) => {
    const r = rig.bones.get(name);
    if (!r?.restAcrossInRoot) return null;
    return r.restAcrossInRoot.toArray().map(v=>+v.toFixed(3));
  };
  const restD = (name) => {
    const r = rig.bones.get(name);
    return r?.restDirectionInRoot?.toArray().map(v=>+v.toFixed(3)) || null;
  };
  // mirror x of vec
  const mir = (a) => a ? [-a[0], a[1], a[2]] : null;
  const dot = (a,b) => a[0]*b[0]+a[1]*b[1]+a[2]*b[2];
  const ang = (a,b) => {
    const d=Math.max(-1,Math.min(1,dot(a,b)));
    return +(Math.acos(d)*180/Math.PI).toFixed(1);
  };

  // anatomical across pure pinky-index both sides
  const anat = (side, negate) => {
    const w=aux[side+'_wrist'], i=aux[side+'_index'], p=aux[side+'_pinky'];
    if(!w||!i||!p) return null;
    const across = p.clone().sub(i);
    if (negate) across.negate();
    return across.normalize().toArray().map(v=>+v.toFixed(3));
  };

  // palm normal = fwd x across
  const palmN = (side, negate) => {
    const w=aux[side+'_wrist'], i=aux[side+'_index'], p=aux[side+'_pinky'];
    if(!w||!i||!p) return null;
    const fwd = i.clone().add(p).multiplyScalar(0.5).sub(w).normalize();
    let across = p.clone().sub(i);
    if (negate) across.negate();
    across.normalize();
    const n = new THREE.Vector3().crossVectors(fwd, across).normalize();
    return n.toArray().map(v=>+v.toFixed(3));
  };

  const Lf = rig.bones.get('leftForeArm');
  const Rf = rig.bones.get('rightForeArm');
  const Lra = Lf.restAcrossInRoot.toArray();
  const Rra = Rf.restAcrossInRoot.toArray();
  const LraM = mir(Lra);

  // also: after applying current solver, what is the live bone's "applied across" = restAcross rotated by delta from rest
  const liveAcross = (name) => {
    const r = rig.bones.get(name);
    if (!r?.restAcrossInRoot) return null;
    const q = r.bone.getWorldQuaternion(new THREE.Quaternion());
    const restQ = rootQ.clone().multiply(r.restQuaternionInRoot);
    // liveAcrossWorld = restAcrossWorld applied through rest->live delta
    const restAW = r.restAcrossInRoot.clone().applyQuaternion(rootQ);
    const dq = q.clone().multiply(restQ.clone().invert()); // rest->live in world? 
    // better: take restAcross in root, transform by live root-space bone rot relative to rest
    const liveQroot = invRoot.clone().multiply(q);
    const restQroot = r.restQuaternionInRoot;
    const dqr = liveQroot.clone().multiply(restQroot.clone().invert());
    const a = r.restAcrossInRoot.clone().applyQuaternion(dqr).normalize();
    // project perp to live bone dir
    const liveDir = r.restDirectionInRoot.clone().applyQuaternion(dqr).normalize();
    a.addScaledVector(liveDir, -a.dot(liveDir));
    return a.normalize().toArray().map(v=>+v.toFixed(3));
  };

  const opts = S.getHandRetargetOpts();

  return {
    opts,
    restAcross: {
      Lfore: restA('leftForeArm'), Rfore: restA('rightForeArm'),
      Lhand: restA('leftHand'), Rhand: restA('rightHand'),
      Ldir: restD('leftForeArm'), Rdir: restD('rightForeArm'),
    },
    restMirror: {
      L_vs_mirR_ang: ang(Lra, mir(Rra)),
      L_vs_negMirR_ang: ang(Lra, [-mir(Rra)[0], -mir(Rra)[1], -mir(Rra)[2]]),
      R_vs_mirL_ang: ang(Rra, mir(Lra)),
      R_vs_negMirL_ang: ang(Rra, [-LraM[0], -LraM[1], -LraM[2]]),
      L: Lra.map(v=>+v.toFixed(3)),
      R: Rra.map(v=>+v.toFixed(3)),
      mirR: mir(Rra).map(v=>+v.toFixed(3)),
      negMirR: [-mir(Rra)[0], -mir(Rra)[1], -mir(Rra)[2]].map(v=>+v.toFixed(3)),
    },
    anat: {
      pureL: anat('left', false), pureR: anat('right', false),
      curL: anat('left', opts.negateAcrossLeft), curR: anat('right', opts.negateAcrossRight),
      pureMirrorAng: (()=>{ const a=anat('left',false), b=anat('right',false); return a&&b? ang(a, mir(b)):null; })(),
      pureNegMirrorAng: (()=>{ const a=anat('left',false), b=anat('right',false);
        if(!a||!b) return null; const m=mir(b); return ang(a,[-m[0],-m[1],-m[2]]); })(),
      curMirrorAng: (()=>{ const a=anat('left',opts.negateAcrossLeft), b=anat('right',opts.negateAcrossRight);
        return a&&b? ang(a, mir(b)):null; })(),
    },
    palmN: {
      pureL: palmN('left',false), pureR: palmN('right',false),
      curL: palmN('left',opts.negateAcrossLeft), curR: palmN('right',opts.negateAcrossRight),
      pureMirrorN: (()=>{ const a=palmN('left',false), b=palmN('right',false); return a&&b? ang(a,mir(b)):null; })(),
      curMirrorN: (()=>{ const a=palmN('left',opts.negateAcrossLeft), b=palmN('right',opts.negateAcrossRight);
        return a&&b? ang(a,mir(b)):null; })(),
    },
    liveAcrossAfter: {
      L: liveAcross('leftForeArm'), R: liveAcross('rightForeArm'),
    },
  };
}
"""

srv=ThreadingHTTPServer(("127.0.0.1",0),H)
threading.Thread(target=srv.serve_forever,daemon=True).start()
url=f"http://127.0.0.1:{srv.server_port}"
with sync_playwright() as pw:
    b=pw.chromium.launch(headless=True)
    for tag in ["upright","mid"]:
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
