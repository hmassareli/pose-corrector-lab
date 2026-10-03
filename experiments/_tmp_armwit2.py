import json, sys, threading, re
from http.server import ThreadingHTTPServer
from pathlib import Path
from playwright.sync_api import sync_playwright
sys.path[:0]=["scripts"]
from check_palm_fidelity import Handler as BaseHandler

LAB=Path(".").resolve(); OUT=LAB/"experiments/bone_crook"
base_txt = (LAB/"viewer/mikapo_mixamo_solver.js").read_text(encoding="utf-8")
# Marker + force useWitness default false AND hardcode arm path to Toward only
nowit = base_txt.replace("useWitness = true,", "useWitness = false, /*ARMROLL_NOWIT*/", 1)
# Also replace the arm witness call with toward so even if flag wrong, no witness
old_arm = """    if (useWitness) {
      rotateBoneWithWitness(model, rig, arm, upperDir, foreDir, 1, timestampMs);
    } else {
      rotateBoneToward(model, rig, arm, upperDir, 1, timestampMs);
    }"""
new_arm = """    // ARMROLL_NOWIT forced
    if (false && useWitness) {
      rotateBoneWithWitness(model, rig, arm, upperDir, foreDir, 1, timestampMs);
    } else {
      rotateBoneToward(model, rig, arm, upperDir, 1, timestampMs);
    }"""
assert old_arm in nowit, "arm block not found"
nowit = nowit.replace(old_arm, new_arm, 1)
(LAB/"experiments/_solver_armroll_nowit.js").write_text(nowit, encoding="utf-8")
print("nowit marker", "ARMROLL_NOWIT" in nowit)

class H(BaseHandler):
    solver = None
    def translate_path(self, path):
        from urllib.parse import unquote, urlparse
        route = unquote(urlparse(path).path)
        if route.startswith("/poses/"):
            return str(OUT / route[len("/poses/"):])
        if "mikapo_mixamo_solver.js" in route and H.solver:
            return str(H.solver)
        return super().translate_path(path)

M = r"""
async () => {
  // prove which solver loaded
  const src = await fetch('/static/mikapo_mixamo_solver.js').then(r=>r.text());
  const marker = src.includes('ARMROLL_NOWIT');
  const THREE = window.__BAKE_THREE__;
  const av = window.__BAKE_AVATAR__;
  const rig = window.__BAKE_RIG__;
  av.updateWorldMatrix(true,true);
  const rootQ = av.getWorldQuaternion(new THREE.Quaternion());
  const twistOf = (name) => {
    const r = rig.bones.get(name);
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
  const arr=v=>v.toArray().map(x=>+x.toFixed(3));
  const Lf=liveFront('leftArm'), Rf=liveFront('rightArm');
  return {
    marker,
    twistArm: [twistOf('leftArm'), twistOf('rightArm')],
    twistFore: [twistOf('leftForeArm'), twistOf('rightForeArm')],
    frontL: Lf&&arr(Lf), frontR: Rf&&arr(Rf),
    frontL_fwd: Lf?+Lf.z.toFixed(3):null,
    frontR_fwd: Rf?+Rf.z.toFixed(3):null,
    frontL_x: Lf?+Lf.x.toFixed(3):null,
    frontR_x: Rf?+Rf.x.toFixed(3):null,
  };
}
"""

def run(solver, label):
    H.solver = Path(solver).resolve()
    srv=ThreadingHTTPServer(("127.0.0.1",0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url=f"http://127.0.0.1:{srv.server_port}"
    print(f"\n== {label} ==")
    with sync_playwright() as pw:
        b=pw.chromium.launch(headless=True)
        for tag in ["upright","sit","mid"]:
            p=b.new_page(viewport={"width":900,"height":1100})
            # cache bust the module on the HTML side by proxy? page imports fixed path; our translate rewrites file content
            p.goto(f"{url}/bake_seq?pose=/poses/pose_{tag}.json&avatar=boxeador&fps=1&ui=0&t={label}", wait_until="domcontentloaded", timeout=180000)
            p.wait_for_function("() => window.__BAKE_READY__ || window.__BAKE_ERROR__", timeout=240000)
            err=p.evaluate("() => window.__BAKE_ERROR__")
            if err:
                print(tag, "ERR", err); p.close(); continue
            p.evaluate("() => window.__bakeSeqStep && window.__bakeSeqStep()")
            out=p.evaluate(M)
            print(f"{tag}: marker={out['marker']} twistArm={out['twistArm']} twistFore={out['twistFore']}")
            print(f"      front L xyz={out['frontL']} fwd={out['frontL_fwd']} x={out['frontL_x']}")
            print(f"      front R xyz={out['frontR']} fwd={out['frontR_fwd']} x={out['frontR_x']}")
            # save close-up screenshot of upper body
            p.evaluate("""() => {
              const av=window.__BAKE_AVATAR__;
              const THREE=window.__BAKE_THREE__;
              av.updateWorldMatrix(true,true);
              // aim camera at chest
              const chest = new THREE.Vector3(0, 1.1, 0);
              window.__bakeLookAt([0.2, 1.35, 1.6], [0, 1.0, 0]);
            }""")
            p.screenshot(path=str(OUT/f"armroll_{label}_{tag}.png"))
            p.close()
        b.close()
    srv.shutdown()

run(LAB/"viewer/mikapo_mixamo_solver.js", "base")
run(LAB/"experiments/_solver_armroll_nowit.js", "nowit")
print("saved pngs to", OUT)
