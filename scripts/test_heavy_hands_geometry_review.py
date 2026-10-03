"""Independent evaluator: native sole, wrist/palm and contact measurements.

Uses the actual boxing render chain and cached NLF poses, never starts inference.
Synthetic palm checks distinguish fixed fighter axes from actual facial rays.
"""
import json
from pathlib import Path
import numpy as np
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'experiments' / 'heavy_hands_gauntlet'
z = np.load(ROOT / 'benchmarks' / 'punch_cadence_20261002.nlf.npz')
cam = z['cam']
heights = cam[150:450, 15, 1] - np.minimum(cam[150:450, 5, 1], cam[150:450, 6, 1])
scale = 1.72 / float(np.median(heights))
poses = []
for frame in cam[150::12]:
    q = frame.copy()
    q[:, 0] -= frame[0, 0]
    q[:, 2] -= frame[0, 2]
    q[:, 1] -= min(frame[5, 1], frame[6, 1])
    poses.append((q * scale).tolist())

PROBE = r'''async poses=>{
 const T=await import('three'),{neutralPose}=await import('/static/boxing_core.mjs');
 const {soleBottom}=await import('/static/boxing_feet.js');
 const d=cornerDebug;d.paused=true;await new Promise(r=>requestAnimationFrame(r));
 document.getElementById('smooth').value=0;document.getElementById('smooth').dispatchEvent(new Event('input'));
 const a=d.actors[0],at=b=>b.getWorldPosition(new T.Vector3());
 const angle=(x,y)=>T.MathUtils.radToDeg(Math.acos(T.MathUtils.clamp(x.clone().normalize().dot(y.clone().normalize()),-1,1)));
 const measure=(label,guard=false)=>{
  const hands=a.handBasis.map((h,i)=>{
   const fore=a.rig.bones.get((i?'right':'left')+'ForeArm').bone,axis=at(h.hand).sub(at(fore)).normalize();
   const q=h.hand.getWorldQuaternion(new T.Quaternion()),actual=h.axis.clone().applyQuaternion(q),palm=h.palm.clone().applyQuaternion(q).normalize();
   const project=v=>v.clone().addScaledVector(axis,-v.dot(axis)).normalize();
   const inward=project(a.group.getWorldDirection(new T.Vector3()).negate());
   const towardOther=project(new T.Vector3(i?1:-1,0,0).applyQuaternion(a.group.getWorldQuaternion(new T.Quaternion())));
   const actualFace=project(at(a.rig.bones.get('head').bone).sub(at(h.hand)));
   const other=project(at(a.handBasis[1-i].hand).sub(at(h.hand)));
   const headOrigin=at(a.guardContact.headBone),headInverse=a.guardContact.headBone.getWorldQuaternion(new T.Quaternion()).invert();
   const skinGap=Math.min(...a.guardContact.hands[i].sphere.supportPoints.map(p=>{
    const point=p.clone().applyQuaternion(q).add(at(h.hand)).sub(headOrigin).applyQuaternion(headInverse);
    return a.guardContact.surface.distance(point,0,-Infinity).gap;
   }));
   const native=a.guardContact.hands[i],m=a.guardContact.measure(native),arm=at(native.arm),totalArm=arm.distanceTo(at(native.fore))+at(native.fore).distanceTo(at(native.hand));
   const target=at(native.hand).add(m.normal.clone().applyQuaternion(m.headRotation).multiplyScalar(Math.max(0,.004-m.gap)));
   return {wristAngle:angle(axis,actual),quaternionNorm:q.length(),gap:m.gap,skinGap,totalArm,currentReach:arm.distanceTo(at(native.hand)),requiredProjectedReach:arm.distanceTo(target),overReach:arm.distanceTo(target)-(totalArm-.001),
    palmFixedFace:angle(palm,inward),palmFixedOther:angle(palm,towardOther),palmActualFace:angle(palm,actualFace),palmActualOther:angle(palm,other),
    projectedBisectorError:angle(palm,inward.add(towardOther).normalize())};
  });
  const soles=['leftFoot','rightFoot'].map(n=>soleBottom(a,a.rig.bones.get(n).bone));
  return {label,guard,hands,soles,lowestSoleError:Math.min(...soles)-.026};
 };
 const feed=p=>{d.reviewPose(p);d.frame(performance.now()+34);};
 const rows=[];
 // High, bent-elbow and close guards as well as fully extended punches.
 for(const y of [1.45,1.65,1.82])for(const depth of [-.15,0,.15,.30])for(const elbowY of [1.3,1.7]){
  const p=neutralPose();p[12]=[.1,y,depth];p[13]=[-.1,y,depth];p[10]=[.3,elbowY,.05];p[11]=[-.3,elbowY,.05];
  a.guardContact.reset();feed(p);rows.push(measure('guard:'+y+','+depth+','+elbowY,true));
 }
 feed(neutralPose());rows.push(measure('neutral',true));
 // Test floor motion across source leg lifts rather than only a static pose.
 for(let k=0;k<poses.length;k++){feed(poses[k]);rows.push(measure('cached-NLF:'+k));}
 // Change body altitude without changing knee/hip rotations.
 for(const delta of [-.25,-.08,.08,.25]){const p=neutralPose().map(v=>[v[0],v[1]+delta,v[2]]);feed(p);rows.push(measure('height:'+delta));}
 const all=rows.flatMap(r=>r.hands),floor=rows.map(r=>r.lowestSoleError);
 return {avatar:a.avatarId,rows,dimensions:a.guardContact.dimensions(),
  summary:{frames:rows.length,wristMax:Math.max(...all.map(h=>h.wristAngle)),gapMin:Math.min(...all.map(h=>h.gap)),nativeSkinGapMin:Math.min(...all.map(h=>h.skinGap)),
   maxQuaternionNormError:Math.max(...all.map(h=>Math.abs(h.quaternionNorm-1))),floorMaxAbs:Math.max(...floor.map(Math.abs)),floorWithin2cm:floor.filter(x=>Math.abs(x)<=.02).length/floor.length,
   penetratingConfigurations:rows.filter(r=>r.hands.some(h=>h.gap<-.002)).map(r=>({label:r.label,hands:r.hands})),
   neutral:rows.find(r=>r.label==='neutral')},limitation:'Cached NLF joint replay with generated auxiliary landmarks, no new inference. Quantifies native geometry, not live latency or biomechanical force accuracy.'};
}'''

reports = []
with sync_playwright() as pw:
    browser = pw.chromium.launch(args=['--use-angle=d3d11', '--ignore-gpu-blocklist'])
    for avatar in ['boxer-prism31', 'boxeador', 'fighter-web']:
        context = browser.new_context(viewport={'width': 1280, 'height': 800})
        page = context.new_page()
        page.add_init_script('localStorage.setItem("labAvatarId",' + json.dumps(avatar) + ')')
        errors = []
        page.on('pageerror', lambda err: errors.append(str(err)))
        page.goto('http://127.0.0.1:8780/static/boxing.html', wait_until='domcontentloaded')
        page.wait_for_function('window.cornerDebug?.state().loaded', timeout=90000)
        report = page.evaluate(PROBE, poses)
        report['pageErrors'] = errors
        reports.append(report)
        print(json.dumps({'avatar': avatar, **report['summary'], 'errors': errors}), flush=True)
        context.close()
    browser.close()
OUT.mkdir(exist_ok=True)
(OUT / 'independent_geometry_review.json').write_text(json.dumps(reports, indent=2), encoding='utf-8')
print('Saved independent_geometry_review.json', flush=True)
