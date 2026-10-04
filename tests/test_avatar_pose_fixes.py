"""Behavioral regression on the actual three rigs; no webcam permission needed.

Tests full orientation, occlusion continuity, body-relative hold, sample clocks,
filter response/jitter, anatomical bounds, palm degeneracy and straight elbows.
Human fidelity and camera-to-display latency are explicitly not certified here.
"""
import ast
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "experiments/retarget_pose_fixes"
OUT.mkdir(exist_ok=True)
tree = ast.parse((ROOT / "scripts/audit_avatar_retarget.py").read_text(encoding="utf-8"))
HARNESS = next(ast.literal_eval(n.value) for n in tree.body
    if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "HARNESS" for t in n.targets))

TEST = r"""async () => {
 const T=await import('three'),S=await import('/static/mikapo_mixamo_solver.js');
 const {neutralPose,JOINTS}=await import('/static/boxing_core.mjs');
 const a=cornerDebug.actors[0],rig=a.rig,root=a.root;
 const results={},checks=[];let clock=1000,motion=S.createAvatarMotion(),calibrationKey=null;
 const q=n=>root.getWorldQuaternion(new T.Quaternion()).invert().multiply(rig.bones.get(n).bone.getWorldQuaternion(new T.Quaternion()));
 const canonical=n=>q(n).multiply((rig.bones.get(n).restFaceInRoot||rig.bones.get(n).restUprightInRoot||rig.bones.get(n).restQuaternionInRoot).clone().invert());
 const check=(name,ok,detail)=>{checks.push({name,ok,detail});};
 const pose=neutralPose(),base={kind:'smpl'};
 for(const [n,i]of Object.entries(JOINTS))base[n]=new T.Vector3(...pose[i]);
 Object.assign(base,{spine1:new T.Vector3(0,1.04,0),spine2:new T.Vector3(0,1.2,0),spine3:new T.Vector3(0,1.4,0),
 neck:new T.Vector3(0,1.55,0),head:new T.Vector3(0,1.72,0),left_eye:new T.Vector3(.035,1.75,.08),right_eye:new T.Vector3(-.035,1.75,.08),jaw:new T.Vector3(0,1.66,.06)});
 const clone=()=>Object.fromEntries(Object.entries(base).map(([k,v])=>[k,v?.clone?.()||v]));
 const angle=(a,b)=>T.MathUtils.radToDeg(a.angleTo(b));
 const rotate=(q)=>{const aux=clone();for(const n of ['left_eye','right_eye','jaw'])aux[n].sub(aux.head).applyQuaternion(q).add(aux.head);return aux;};
 const turn=deg=>new T.Quaternion().setFromAxisAngle(new T.Vector3(0,1,0),T.MathUtils.degToRad(deg));
 const run=(aux=clone(),p=pose,amount=0,advance=1000/30,sample=true)=>{
   if(sample)clock+=advance;
   S.updateAvatarPose({model:root,rig,motion,pose:p,aux,nameToIndex:JOINTS,allowFeet:true,plantGround:true,groundY:0,useWitness:true,
    timestampMs:amount===0?null:clock,sampleTimestampMs:clock,presentationTimestampMs:clock,headCalibrationKey:calibrationKey});
   return canonical('head');
 };
 const reset=(amount=0)=>{motion=S.createAvatarMotion();S.resetRetargetFilters(rig);S.setRetargetSmoothing(rig,1.5*50/Math.max(1,amount),1.5*50/Math.max(1,amount));return run(clone(),pose,amount);};
 const errors=[];
 for(const e of [[0,45,0],[0,-45,0],[30,0,0],[-30,0,0],[0,0,25],[0,0,-25],[20,40,15]]){
   const initial=reset(),expected=new T.Quaternion().setFromEuler(new T.Euler(...e.map(T.MathUtils.degToRad),'YXZ'));
   const observed=run(rotate(expected)).multiply(initial.clone().invert());
   errors.push(angle(expected,observed));
 }
 check('signed_and_combined_face_orientation',Math.max(...errors)<.2,errors);
 for(const mode of ['missing','collapsed','short','nan']){
   const initial=reset(),aux=clone();
   if(mode==='missing'){delete aux.left_eye;delete aux.right_eye;}
   if(mode==='collapsed')aux.right_eye.copy(aux.left_eye);
   if(mode==='short')aux.right_eye.copy(aux.left_eye).add(new T.Vector3(0,0,.002));
   if(mode==='nan')aux.left_eye.x=NaN;
   const moved=angle(initial,run(aux));check('neutral_'+mode,moved<.2,moved);
 }
 reset();const target=rotate(turn(35));run(target);
 const held=q('head'),heldTorso=canonical('spine2'),missing={...target};delete missing.left_eye;delete missing.right_eye;
 const atLoss=q('head');run(missing);check('short_occlusion_hold',angle(atLoss,q('head'))<.2,angle(atLoss,q('head')));
 const body=turn(20),turned=Object.fromEntries(Object.entries(missing).map(([n,v])=>[n,v?.clone?v.clone().applyQuaternion(body):v]));
 const movedPose=pose.map(v=>new T.Vector3(...v).applyQuaternion(body).toArray());
 run(turned,movedPose);const bodyDelta=q('head').multiply(held.clone().invert());
 const torsoDelta=canonical('spine2').multiply(heldTorso.clone().invert());
 check('occlusion_follows_body',angle(bodyDelta,torsoDelta)<.3,angle(bodyDelta,torsoDelta));
 let maxDecayStep=0,previous=canonical('head');
 for(let i=0;i<60;i++){const next=run(turned,movedPose);maxDecayStep=Math.max(maxDecayStep,angle(previous,next));previous=next;}
 check('prolonged_loss_relaxes_without_snap',maxDecayStep<6,maxDecayStep);
 let maxRecoveryStep=0;
 const recovered=Object.fromEntries(Object.entries(target).map(([n,v])=>[n,v?.clone?v.clone().applyQuaternion(body):v]));
 for(let i=0;i<12;i++){const next=run(recovered,movedPose);maxRecoveryStep=Math.max(maxRecoveryStep,angle(previous,next));previous=next;}
 check('recovery_continuity',maxRecoveryStep<18,maxRecoveryStep);
 check('recovery_reaches_face',angle(previous,turn(55))<.3,angle(previous,turn(55)));
 reset();const before=q('head'),outlier=clone();[outlier.left_eye,outlier.right_eye]=[outlier.right_eye,outlier.left_eye];run(outlier);
 check('single_frame_orientation_flip_rejected',angle(before,q('head'))<.3,S.getHeadRetargetDiagnostics(rig));
 reset(50);const dupBefore=q('head');run(rotate(turn(45)),pose,50,0,false);
 check('duplicate_timestamp_does_not_reset_filter',angle(dupBefore,q('head'))<.2,angle(dupBefore,q('head')));
 const response={};
 for(const amount of [0,50,100]){
   reset(amount);let settle=null;
   for(let i=0;i<30;i++){const actual=run(rotate(turn(45)),pose,amount);if(settle==null&&angle(actual,turn(45))<4.5)settle=(i+1)*1000/30;}
   response[amount]=settle;
 }
 check('slider_bypass_and_response',response[0]===1000/30&&response[50]<=200&&response[100]<=350,response);
 reset(50);const filtered=[];
 for(let i=0;i<60;i++)filtered.push(T.MathUtils.radToDeg(new T.Euler().setFromQuaternion(run(rotate(turn(i%2?.4:-.4)),pose,50),'YXZ').y));
 const amplitude=Math.max(...filtered.slice(20))-Math.min(...filtered.slice(20));
 check('slider_filters_stationary_jitter',amplitude<.65,{inputPeakToPeak:.8,outputPeakToPeak:amplitude});
 reset();let maxNeckYaw=0,maxHeadRelativeYaw=0,finite=true;
 for(let i=0;i<60;i++){
   const rotation=new T.Quaternion().setFromEuler(new T.Euler(.4*Math.sin(i*.2),2*Math.sin(i*.15),.8*Math.sin(i*.1),'YXZ'));
   run(rotate(rotation));
   const torso=canonical('spine2'),neck=canonical('neck'),head=canonical('head');
   maxNeckYaw=Math.max(maxNeckYaw,Math.abs(T.MathUtils.radToDeg(new T.Euler().setFromQuaternion(torso.clone().invert().multiply(neck),'YXZ').y)));
   maxHeadRelativeYaw=Math.max(maxHeadRelativeYaw,Math.abs(T.MathUtils.radToDeg(new T.Euler().setFromQuaternion(neck.clone().invert().multiply(head),'YXZ').y)));
   finite&&=[...rig.bones.values()].every(r=>r.bone.quaternion.toArray().every(Number.isFinite));
 }
 check('relative_anatomical_limits',finite&&maxNeckYaw<=40.2&&maxHeadRelativeYaw<=65.2,{maxNeckYaw,maxHeadRelativeYaw});
 reset();const bent=pose.map(v=>v.slice()),sh=new T.Vector3(...bent[JOINTS.left_shoulder]),el=sh.clone().add(new T.Vector3(.3,0,0));
 bent[JOINTS.left_elbow]=el.toArray();bent[JOINTS.left_wrist]=el.clone().add(new T.Vector3(0,0,.3)).toArray();
 run(null,bent);const bentQ=q('leftArm');const straight=bent.map(v=>v.slice());straight[JOINTS.left_wrist]=el.clone().add(new T.Vector3(.3,0,0)).toArray();
 run(null,straight);check('straight_elbow_keeps_twist',angle(bentQ,q('leftArm'))<.3,angle(bentQ,q('leftArm')));
 const palm=clone();palm.left_index=palm.left_wrist.clone().add(new T.Vector3(.01,.08,.02));palm.left_pinky=palm.left_index.clone().add(new T.Vector3(0,0,.002));
 const axes=S.computeHandPalmAxes(palm,'left');check('tiny_palm_span_does_not_create_twist',axes?.across===null,axes?.across?.toArray()||null);
 reset();calibrationKey='preview';const preview=run();
 const real=clone();real.left_eye.y=real.right_eye.y=1.725;
 calibrationKey='webcam';const realNeutral=run(real);
 check('real_capture_does_not_inherit_demo_calibration',angle(preview,realNeutral)<.2,angle(preview,realNeutral));
 reset();run(rotate(turn(35)));const sampleClock=clock;clock+=500;
 S.updateAvatarPose({model:root,rig,motion,pose,aux:rotate(turn(35)),nameToIndex:JOINTS,allowFeet:true,
   sampleTimestampMs:sampleClock,presentationTimestampMs:clock,headCalibrationKey:calibrationKey});
 check('repainting_stale_sample_does_not_renew_confidence',S.getHeadRetargetDiagnostics(rig).status==='held',S.getHeadRetargetDiagnostics(rig));
 return {avatar:a.avatarId,checks,pass:checks.every(c=>c.ok)};
}"""

with sync_playwright() as pw:
    errors = []
    reports = []
    for avatar in ["boxer-prism31", "boxeador", "fighter-web"]:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.on("pageerror", lambda e: errors.append(str(e)))
        harness = HARNESS.replace("select.onchange=create;await create();", "select.onchange=create;select.value="+json.dumps(avatar)+";await create();")
        page.route("**/static/retarget-audit", lambda r: r.fulfill(status=200, content_type="text/html", body=harness))
        page.goto("http://127.0.0.1:8780/static/retarget-audit", wait_until="domcontentloaded")
        page.wait_for_function("window.cornerDebug?.state().loaded || window.auditError", timeout=60000)
        assert not page.evaluate("window.auditError"), page.evaluate("window.auditError")
        report = page.evaluate(TEST)
        reports.append(report)
        print(avatar, "PASS" if report["pass"] else "FAIL", json.dumps([c for c in report["checks"] if not c["ok"]]), flush=True)
        browser.close()
result = {"avatars": reports, "pageErrors": errors}
(OUT / "regression.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
assert not errors and all(r["pass"] for r in reports), "See experiments/retarget_pose_fixes/regression.json"
