import json, sys, threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from playwright.sync_api import sync_playwright
sys.path[:0]=["scripts"]
from check_palm_fidelity import Handler as BaseHandler

LAB=Path(".").resolve(); OUT=LAB/"experiments/bone_crook"

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

SHOT = r"""
async (cfg) => {
  const THREE = window.__BAKE_THREE__;
  const av = window.__BAKE_AVATAR__;
  const rig = window.__BAKE_RIG__;
  av.updateWorldMatrix(true,true);
  // world positions of shoulders/elbows
  const wp = (name) => {
    const r=rig.bones.get(name);
    return r.bone.getWorldPosition(new THREE.Vector3());
  };
  const Lsh=wp('leftArm'), Rsh=wp('rightArm');
  const mid = Lsh.clone().add(Rsh).multiplyScalar(0.5);
  const side = cfg.side; // 'left' | 'right' | 'both'
  let target, eye;
  if (side==='left') {
    target = Lsh.clone().add(new THREE.Vector3(0,-0.12,0.05));
    // look from character front-left slightly above
    eye = target.clone().add(new THREE.Vector3(-0.55, 0.25, 0.75));
  } else if (side==='right') {
    target = Rsh.clone().add(new THREE.Vector3(0,-0.12,0.05));
    eye = target.clone().add(new THREE.Vector3(0.55, 0.25, 0.75));
  } else if (side==='top') {
    target = mid.clone().add(new THREE.Vector3(0,-0.05,0.1));
    eye = target.clone().add(new THREE.Vector3(0, 1.1, 0.15));
  } else {
    // front chest
    target = mid.clone().add(new THREE.Vector3(0,-0.05,0));
    eye = target.clone().add(new THREE.Vector3(0, 0.15, 1.2));
  }
  window.__bakeLookAt([eye.x,eye.y,eye.z],[target.x,target.y,target.z]);
  return {eye:[eye.x,eye.y,eye.z], target:[target.x,target.y,target.z]};
}
"""

def run(solver, label):
    H.solver=Path(solver).resolve()
    srv=ThreadingHTTPServer(("127.0.0.1",0),H)
    threading.Thread(target=srv.serve_forever,daemon=True).start()
    url=f"http://127.0.0.1:{srv.server_port}"
    with sync_playwright() as pw:
        b=pw.chromium.launch(headless=True)
        for tag in ["upright","sit"]:
            p=b.new_page(viewport={"width":720,"height":960})
            p.goto(f"{url}/bake_seq?pose=/poses/pose_{tag}.json&avatar=boxeador&fps=1&ui=0&v={label}", wait_until="domcontentloaded", timeout=180000)
            p.wait_for_function("() => window.__BAKE_READY__ || window.__BAKE_ERROR__", timeout=240000)
            p.evaluate("() => window.__bakeSeqStep && window.__bakeSeqStep()")
            for side in ["left","right","top","front"]:
                p.evaluate(SHOT, {"side":side})
                p.screenshot(path=str(OUT/f"biceps_{label}_{tag}_{side}.png"))
            p.close()
        b.close()
    srv.shutdown()
    print("done", label)

run(LAB/"viewer/mikapo_mixamo_solver.js", "base")
run(LAB/"experiments/_solver_armroll_nowit.js", "nowit")
print("ok")
