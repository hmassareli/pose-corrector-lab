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

  const arr=(v)=>[...v.toArray()].map(x=>+x.toFixed(3));
  const ang=(a,b)=>+(a.angleTo(b)*180/Math.PI).toFixed(1);
  const mir=(v)=>new THREE.Vector3(-v.x,v.y,v.z);

  // bone local axes in WORLD
  const localAxes = (name) => {
    const r = rig.bones.get(name);
    const e = new THREE.Euler().setFromQuaternion(r.bone.getWorldQuaternion(new THREE.Quaternion()), 'XYZ');
    const m = new THREE.Matrix4().extractRotation(r.bone.matrixWorld);
    const x=new THREE.Vector3(), y=new THREE.Vector3(), z=new THREE.Vector3();
    m.extractBasis(x,y,z);
    return {x:arr(x), y:arr(y), z:arr(z)};
  };

  // rest local axes in world (rest pose orientation)
  const restAxes = (name) => {
    const r = rig.bones.get(name);
    const restQ = rootQ.clone().multiply(r.restQuaternionInRoot);
    const x=new THREE.Vector3(1,0,0).applyQuaternion(restQ);
    const y=new THREE.Vector3(0,1,0).applyQuaternion(restQ);
    const z=new THREE.Vector3(0,0,1).applyQuaternion(restQ);
    return {x:arr(x), y:arr(y), z:arr(z),
      // which axis is closest to restDirection and restWitness
      dir: arr(r.restDirectionInRoot.clone().applyQuaternion(rootQ)),
      wit: r.restWitnessInRoot ? arr(r.restWitnessInRoot.clone().applyQuaternion(rootQ)) : null,
    };
  };

  const armGeom = (side) => {
    const sh=aux[side+'_shoulder'], el=aux[side+'_elbow'], wr=aux[side+'_wrist'];
    const upper=el.clone().sub(sh);
    const fore=wr.clone().sub(el);
    const u=upper.clone().normalize(), f=fore.clone().normalize();
    const hinge=new THREE.Vector3().crossVectors(u,f);
    const hl=hinge.length();
    if(hl>1e-8) hinge.multiplyScalar(1/hl); else hinge.set(0,0,0);
    // "biceps facing" anatomical approx: cross(hinge, upper) — points to inside of elbow / biceps side
    const biceps = new THREE.Vector3().crossVectors(hinge, u);
    if(biceps.lengthSq()>1e-8) biceps.normalize();
    // elev / azimuth
    const elev = Math.asin(Math.max(-1,Math.min(1,u.y)))*180/Math.PI;
    const az = Math.atan2(u.x, u.z)*180/Math.PI;
    const bend = Math.acos(Math.max(-1,Math.min(1,u.dot(f))))*180/Math.PI;
    return {
      upper: arr(u), fore: arr(f), hinge: arr(hinge), biceps: arr(biceps),
      elev:+elev.toFixed(1), az:+az.toFixed(1), bend:+bend.toFixed(1),
      // forearm component in horizontal plane
      fore_fwd: +f.z.toFixed(3), fore_up: +f.y.toFixed(3), fore_x: +f.x.toFixed(3),
      biceps_fwd: +biceps.z.toFixed(3), biceps_up: +biceps.y.toFixed(3), biceps_x: +biceps.x.toFixed(3),
    };
  };

  // After solve: which live bone axis best matches data biceps direction?
  const matchBiceps = (name, bicepsW) => {
    const ax = localAxes(name);
    const axes = {
      x: new THREE.Vector3().fromArray(ax.x),
      y: new THREE.Vector3().fromArray(ax.y),
      z: new THREE.Vector3().fromArray(ax.z),
    };
    const b = new THREE.Vector3().fromArray(bicepsW);
    let best = null;
    for (const [k,v] of Object.entries(axes)) {
      const e1 = ang(v,b), e2 = ang(v,b.clone().negate());
      const e = Math.min(e1,e2);
      const sign = e1 <= e2 ? '+' : '-';
      if (!best || e < best.err) best = {axis:sign+k, err:e};
    }
    return best;
  };

  // twist about bone using swing-twist vs rest
  const twistOf = (name) => {
    const r = rig.bones.get(name);
    const q = r.bone.getWorldQuaternion(new THREE.Quaternion());
    const restQ = rootQ.clone().multiply(r.restQuaternionInRoot);
    const dq = restQ.clone().invert().multiply(q);
    const axis = r.restDirectionInRoot.clone().applyQuaternion(rootQ).normalize();
    const vv = new THREE.Vector3(dq.x,dq.y,dq.z);
    const proj = vv.dot(axis);
    const twistQ = new THREE.Quaternion(axis.x*proj,axis.y*proj,axis.z*proj,dq.w).normalize();
    const aa = 2*Math.acos(Math.min(1,Math.abs(twistQ.w)))*180/Math.PI;
    return +(aa*(proj>=0?1:-1)).toFixed(1);
  };

  // Live "front" = rest +Z (witness) after solve; live "biceps" match
  const liveFront = (name) => {
    // restWitness mapped by live orientation
    const r = rig.bones.get(name);
    const qw = r.bone.getWorldQuaternion(new THREE.Quaternion());
    const restQ = rootQ.clone().multiply(r.restQuaternionInRoot);
    const dqw = qw.clone().multiply(restQ.clone().invert());
    const front = r.restWitnessInRoot.clone().applyQuaternion(rootQ).applyQuaternion(dqw).normalize();
    const dir = r.restDirectionInRoot.clone().applyQuaternion(rootQ).applyQuaternion(dqw).normalize();
    front.addScaledVector(dir, -front.dot(dir));
    return front.lengthSq()>1e-8 ? front.normalize() : null;
  };

  const LG = armGeom('left'), RG = armGeom('right');
  const Lb = LG.biceps, Rb = RG.biceps;

  // Does the SOLVER's live front match data biceps?
  const Lf = liveFront('leftArm'), Rf = liveFront('rightArm');
  const Lbv = new THREE.Vector3().fromArray(Lb), Rbv = new THREE.Vector3().fromArray(Rb);

  return {
    data: {
      L: LG, R: RG,
      // mirror checks on DATA
      upper_L_vs_mirR: ang(new THREE.Vector3().fromArray(LG.upper), mir(new THREE.Vector3().fromArray(RG.upper))),
      fore_L_vs_mirR: ang(new THREE.Vector3().fromArray(LG.fore), mir(new THREE.Vector3().fromArray(RG.fore))),
      hinge_L_vs_mirR: ang(new THREE.Vector3().fromArray(LG.hinge), mir(new THREE.Vector3().fromArray(RG.hinge))),
      hinge_L_vs_negMirR: ang(new THREE.Vector3().fromArray(LG.hinge), mir(new THREE.Vector3().fromArray(RG.hinge)).negate()),
      biceps_L_vs_mirR: ang(Lbv, mir(Rbv)),
      biceps_L_vs_negMirR: ang(Lbv, mir(Rbv).negate()),
    },
    restAxes: { L: restAxes('leftArm'), R: restAxes('rightArm') },
    liveAxes: { L: localAxes('leftArm'), R: localAxes('rightArm') },
    twistArm: [twistOf('leftArm'), twistOf('rightArm')],
    match: {
      L: matchBiceps('leftArm', Lb),
      R: matchBiceps('rightArm', Rb),
    },
    frontVsBiceps: {
      L: Lf ? { ang: ang(Lf, Lbv), angNeg: ang(Lf, Lbv.clone().negate()), front: arr(Lf) } : null,
      R: Rf ? { ang: ang(Rf, Rbv), angNeg: ang(Rf, Rbv.clone().negate()), front: arr(Rf) } : null,
    },
    // CRITICAL: is rest local frame a mirror? compare rest Y and Z with mir
    restMirror: (()=>{
      const L=restAxes('leftArm'), R=restAxes('rightArm');
      const lv=(a)=>new THREE.Vector3().fromArray(a);
      return {
        x_L_vs_mirR: ang(lv(L.x), mir(lv(R.x))),
        y_L_vs_mirR: ang(lv(L.y), mir(lv(R.y))),
        y_L_vs_negMirR: ang(lv(L.y), mir(lv(R.y)).negate()),
        z_L_vs_mirR: ang(lv(L.z), mir(lv(R.z))),
        z_L_vs_negMirR: ang(lv(L.z), mir(lv(R.z)).negate()),
        dir_L_vs_mirR: ang(lv(L.dir), mir(lv(R.dir))),
      };
    })(),
  };
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
        print("====", tag)
        print("DATA elev/az/bend L", out["data"]["L"]["elev"], out["data"]["L"]["az"], out["data"]["L"]["bend"],
              "R", out["data"]["R"]["elev"], out["data"]["R"]["az"], out["data"]["R"]["bend"])
        print("DATA upper mir", out["data"]["upper_L_vs_mirR"], "fore mir", out["data"]["fore_L_vs_mirR"],
              "hinge mir/neg", out["data"]["hinge_L_vs_mirR"], out["data"]["hinge_L_vs_negMirR"],
              "biceps mir/neg", out["data"]["biceps_L_vs_mirR"], out["data"]["biceps_L_vs_negMirR"])
        print("DATA biceps L", out["data"]["L"]["biceps"], "fwd/up", out["data"]["L"]["biceps_fwd"], out["data"]["L"]["biceps_up"])
        print("DATA biceps R", out["data"]["R"]["biceps"], "fwd/up", out["data"]["R"]["biceps_fwd"], out["data"]["R"]["biceps_up"])
        print("twistArm", out["twistArm"])
        print("frontVsBiceps L", out["frontVsBiceps"]["L"], "R", out["frontVsBiceps"]["R"])
        print("match axis L/R", out["match"]["L"], out["match"]["R"])
        print("restMirror", out["restMirror"])
        print("restAxes L", out["restAxes"]["L"])
        print("restAxes R", out["restAxes"]["R"])
        p.close()
    b.close()
srv.shutdown()
