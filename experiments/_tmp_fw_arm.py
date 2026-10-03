import json, sys, threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from playwright.sync_api import sync_playwright
sys.path[:0]=["scripts"]
from check_palm_fidelity import Handler as BaseHandler

LAB=Path(".").resolve(); OUT=LAB/"experiments/bone_crook"
AVATAR="fighter-web"

class H(BaseHandler):
    solver=None
    def translate_path(self, path):
        from urllib.parse import unquote, urlparse
        route=unquote(urlparse(path).path)
        if route.startswith("/poses/"):
            return str(OUT/route[len("/poses/"):])
        if "mikapo_mixamo_solver.js" in route and H.solver:
            return str(H.solver)
        return super().translate_path(path)

M = r"""
async () => {
  const src = await fetch('/static/mikapo_mixamo_solver.js').then(r=>r.text());
  const marker = src.includes('ARMROLL_NOWIT');
  const THREE = window.__BAKE_THREE__;
  const av = window.__BAKE_AVATAR__;
  const rig = window.__BAKE_RIG__;
  av.updateWorldMatrix(true,true);
  const rootQ = av.getWorldQuaternion(new THREE.Quaternion());
  const arr=v=>v.toArray().map(x=>+x.toFixed(3));
  const ang=(a,b)=>+(a.angleTo(b)*180/Math.PI).toFixed(1);
  const mir=v=>new THREE.Vector3(-v.x,v.y,v.z);

  const twistOf = (name) => {
    const r = rig.bones.get(name);
    if (!r) return null;
    const q = r.bone.getWorldQuaternion(new THREE.Quaternion());
    const restQ = rootQ.clone().multiply(r.restQuaternionInRoot);
    const dq = restQ.clone().invert().multiply(q);
    const axis = r.restDirectionInRoot.clone().applyQuaternion(rootQ).normalize();
    const vv = new THREE.Vector3(dq.x,dq.y,dq.z);
    const proj = vv.dot(axis);
    const twistQ = new THREE.Quaternion(axis.x*proj, axis.y*proj, axis.z*proj, dq.w).normalize();
    const aa = 2*Math.acos(Math.min(1,Math.abs(twistQ.w)))*180/Math.PI;
    return +(aa*(proj>=0?1:-1)).toFixed(1);
  };
  const liveFront = (name) => {
    const r = rig.bones.get(name);
    if (!r?.restWitnessInRoot) return null;
    const qw = r.bone.getWorldQuaternion(new THREE.Quaternion());
    const restQ = rootQ.clone().multiply(r.restQuaternionInRoot);
    const dqw = qw.clone().multiply(restQ.clone().invert());
    const dir = r.restDirectionInRoot.clone().applyQuaternion(rootQ).applyQuaternion(dqw).normalize();
    const front = r.restWitnessInRoot.clone().applyQuaternion(rootQ).applyQuaternion(dqw);
    front.addScaledVector(dir, -front.dot(dir));
    return front.lengthSq()>1e-8 ? front.normalize() : null;
  };
  const restAxes = (name) => {
    const r = rig.bones.get(name);
    if (!r) return null;
    const restQ = rootQ.clone().multiply(r.restQuaternionInRoot);
    const x=new THREE.Vector3(1,0,0).applyQuaternion(restQ);
    const y=new THREE.Vector3(0,1,0).applyQuaternion(restQ);
    const z=new THREE.Vector3(0,0,1).applyQuaternion(restQ);
    return {
      x:arr(x), y:arr(y), z:arr(z),
      dir: arr(r.restDirectionInRoot.clone().applyQuaternion(rootQ)),
      wit: r.restWitnessInRoot ? arr(r.restWitnessInRoot.clone().applyQuaternion(rootQ)) : null,
    };
  };
  const Lf=liveFront('leftArm'), Rf=liveFront('rightArm');
  const Lrest=restAxes('leftArm'), Rrest=restAxes('rightArm');
  const lv=a=>new THREE.Vector3().fromArray(a);
  return {
    marker,
    avatar: window.__BAKE_AVATAR_ID__,
    rigKeys: window.__BAKE_RIG_KEYS__,
    twistArm: [twistOf('leftArm'), twistOf('rightArm')],
    twistFore: [twistOf('leftForeArm'), twistOf('rightForeArm')],
    twistHand: [twistOf('leftHand'), twistOf('rightHand')],
    frontL: Lf&&arr(Lf), frontR: Rf&&arr(Rf),
    frontL_fwd: Lf?+Lf.z.toFixed(3):null,
    frontR_fwd: Rf?+Rf.z.toFixed(3):null,
    frontL_x: Lf?+Lf.x.toFixed(3):null,
    frontR_x: Rf?+Rf.x.toFixed(3):null,
    liveMir: (Lf&&Rf) ? {
      ang: ang(Lf, mir(Rf)),
      angNeg: ang(Lf, mir(Rf).negate()),
    } : null,
    restMirror: (Lrest&&Rrest) ? {
      x_L_vs_mirR: ang(lv(Lrest.x), mir(lv(Rrest.x))),
      y_L_vs_mirR: ang(lv(Lrest.y), mir(lv(Rrest.y))),
      y_L_vs_negMirR: ang(lv(Lrest.y), mir(lv(Rrest.y)).negate()),
      z_L_vs_mirR: ang(lv(Lrest.z), mir(lv(Rrest.z))),
      z_L_vs_negMirR: ang(lv(Lrest.z), mir(lv(Rrest.z)).negate()),
      dir_L_vs_mirR: ang(lv(Lrest.dir), mir(lv(Rrest.dir))),
      wit_L_vs_mirR: (Lrest.wit&&Rrest.wit) ? ang(lv(Lrest.wit), mir(lv(Rrest.wit))) : null,
    } : null,
    restL: Lrest, restR: Rrest,
  };
}
"""

SHOT = r"""
async (cfg) => {
  const THREE = window.__BAKE_THREE__;
  const rig = window.__BAKE_RIG__;
  const av = window.__BAKE_AVATAR__;
  av.updateWorldMatrix(true,true);
  const wp = (name) => rig.bones.get(name).bone.getWorldPosition(new THREE.Vector3());
  const Lsh=wp('leftArm'), Rsh=wp('rightArm');
  const mid = Lsh.clone().add(Rsh).multiplyScalar(0.5);
  let target, eye;
  const side = cfg.side;
  if (side==='left') {
    target = Lsh.clone().add(new THREE.Vector3(0,-0.12,0.05));
    eye = target.clone().add(new THREE.Vector3(-0.55, 0.25, 0.75));
  } else if (side==='right') {
    target = Rsh.clone().add(new THREE.Vector3(0,-0.12,0.05));
    eye = target.clone().add(new THREE.Vector3(0.55, 0.25, 0.75));
  } else if (side==='top') {
    target = mid.clone().add(new THREE.Vector3(0,-0.05,0.1));
    eye = target.clone().add(new THREE.Vector3(0, 1.1, 0.15));
  } else {
    target = mid.clone().add(new THREE.Vector3(0,-0.05,0));
    eye = target.clone().add(new THREE.Vector3(0, 0.15, 1.2));
  }
  window.__bakeLookAt([eye.x,eye.y,eye.z],[target.x,target.y,target.z]);
  return true;
}
"""

def run(solver, label):
    H.solver=Path(solver).resolve()
    srv=ThreadingHTTPServer(("127.0.0.1",0),H)
    threading.Thread(target=srv.serve_forever,daemon=True).start()
    url=f"http://127.0.0.1:{srv.server_port}"
    print(f"\n===== {label} / {AVATAR} =====")
    with sync_playwright() as pw:
        b=pw.chromium.launch(headless=True)
        for tag in ["upright","sit","mid"]:
            p=b.new_page(viewport={"width":720,"height":960})
            p.goto(f"{url}/bake_seq?pose=/poses/pose_{tag}.json&avatar={AVATAR}&fps=1&ui=0&v={label}", wait_until="domcontentloaded", timeout=180000)
            p.wait_for_function("() => window.__BAKE_READY__ || window.__BAKE_ERROR__", timeout=240000)
            err=p.evaluate("() => window.__BAKE_ERROR__")
            if err:
                print(tag, "ERR", err); p.close(); continue
            p.evaluate("() => window.__bakeSeqStep && window.__bakeSeqStep()")
            out=p.evaluate(M)
            print(f"-- {tag} avatar={out['avatar']} marker={out['marker']}")
            print(f"   twist Arm L/R: {out['twistArm']}  Fore {out['twistFore']}  Hand {out['twistHand']}")
            print(f"   front L xyz={out['frontL']} fwd/x={out['frontL_fwd']}/{out['frontL_x']}")
            print(f"   front R xyz={out['frontR']} fwd/x={out['frontR_fwd']}/{out['frontR_x']}")
            print(f"   liveMir ang/neg={out['liveMir']}")
            print(f"   restMirror={out['restMirror']}")
            if tag=="upright":
                print(f"   restL={out['restL']}")
                print(f"   restR={out['restR']}")
            for side in ["left","right","top","front"]:
                p.evaluate(SHOT, {"side":side})
                p.screenshot(path=str(OUT/f"fw_{label}_{tag}_{side}.png"))
            p.close()
        b.close()
    srv.shutdown()

# ensure nowit solver exists with marker
base = (LAB/"viewer/mikapo_mixamo_solver.js").read_text(encoding="utf-8")
nowit_path = LAB/"experiments/_solver_armroll_nowit.js"
if "ARMROLL_NOWIT" not in nowit_path.read_text(encoding="utf-8"):
    nowit = base.replace("useWitness = true,", "useWitness = false, /*ARMROLL_NOWIT*/", 1)
    old_arm = """    if (useWitness) {\n      rotateBoneWithWitness(model, rig, arm, upperDir, foreDir, 1, timestampMs);\n    } else {\n      rotateBoneToward(model, rig, arm, upperDir, 1, timestampMs);\n    }"""
    new_arm = """    // ARMROLL_NOWIT forced\n    if (false && useWitness) {\n      rotateBoneWithWitness(model, rig, arm, upperDir, foreDir, 1, timestampMs);\n    } else {\n      rotateBoneToward(model, rig, arm, upperDir, 1, timestampMs);\n    }"""
    if old_arm in nowit:
        nowit = nowit.replace(old_arm, new_arm, 1)
    nowit_path.write_text(nowit, encoding="utf-8")
    print("rewrote nowit")
else:
    print("nowit ok")

run(LAB/"viewer/mikapo_mixamo_solver.js", "base")
run(nowit_path, "nowit")
print("saved fw_*.png")
