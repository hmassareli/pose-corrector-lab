"""Read-only audit of current real avatar rigs and retargeting, without gameplay edits.
Raw x55 replay measures agreement with the INPUT estimate, not human ground truth.
Independent face rotations detect missing head degrees of freedom.
"""
import hashlib,json,sys
from pathlib import Path
import numpy as np
from playwright.sync_api import sync_playwright

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'src'))
from pose_lab.skeleton import smplx55_to_lab,smplx55_avatar_aux_json
from analyze_palm_raw import karcher_mean,ang
from check_palm_fidelity import quat_to_mat
out=root/(sys.argv[sys.argv.index('--out')+1] if '--out' in sys.argv else 'experiments/retarget_audit_current')
out.mkdir(parents=True,exist_ok=True)
data=np.load(root/'experiments/nlf_fit_webcam1/fit_smplx.npz',allow_pickle=True)
frames=[]
for points in data['x55'].astype(float)/1000:
    points=points-points[:1]
    frames.append({'pose':smplx55_to_lab(points).tolist(),'aux':smplx55_avatar_aux_json(points)})

PROBE=r"""async frames=>{
 const THREE=await import('three'),S=await import('/static/mikapo_mixamo_solver.js');
 const {JOINTS,neutralPose}=await import('/static/boxing_core.mjs');
 const a=cornerDebug.actors[0],rig=a.rig,root=a.root;
 const V=p=>new THREE.Vector3(p[0],-p[1],-p[2]);
 const deg=(a,b)=>a.angleTo(b)*180/Math.PI;
 const q=n=>root.getWorldQuaternion(new THREE.Quaternion()).invert().multiply(rig.bones.get(n).bone.getWorldQuaternion(new THREE.Quaternion()));
 const direction=n=>{const r=rig.bones.get(n);return r.child?r.child.getWorldPosition(new THREE.Vector3()).sub(r.bone.getWorldPosition(new THREE.Vector3())).applyQuaternion(root.getWorldQuaternion(new THREE.Quaternion()).invert()).normalize():r.restLocalDirection.clone().applyQuaternion(q(n)).normalize();};
 const map={hips:['pelvis','spine1'],spine:['spine1','spine2'],spine1:['spine2','spine3'],spine2:['spine3','neck'],neck:['neck','head'],
 leftShoulder:['left_collar','left_shoulder'],rightShoulder:['right_collar','right_shoulder'],
 leftArm:['left_shoulder','left_elbow'],rightArm:['right_shoulder','right_elbow'],leftForeArm:['left_elbow','left_wrist'],rightForeArm:['right_elbow','right_wrist'],
 leftHand:['left_wrist','left_hand'],rightHand:['right_wrist','right_hand'],leftUpLeg:['left_hip','left_knee'],rightUpLeg:['right_hip','right_knee'],
 leftLeg:['left_knee','left_ankle'],rightLeg:['right_knee','right_ankle'],leftFoot:['left_ankle','left_foot'],rightFoot:['right_ankle','right_foot']};
 const allBones=[];root.traverse(n=>{if(n.isBone)allBones.push(n.name)});
 const mapped=Object.fromEntries([...rig.bones].map(([k,r])=>[k,{bone:r.bone.name,child:r.child?.name||null}]));
 const transform=f=>{
   const pose=f.pose.map(V).map(v=>v.toArray()),aux=Object.fromEntries(Object.entries(f.aux).map(([k,v])=>[k,V(v)]));aux.kind='smpl';
   // Reproduce the game's deliberate hip-facing clamp before measuring it.
   const across=new THREE.Vector3(...pose[1]).sub(new THREE.Vector3(...pose[2]));
   const heading=Math.atan2(-across.z,across.x),angle=THREE.MathUtils.clamp(heading,-Math.PI/15,Math.PI/15)-heading;
   const turn=new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0,1,0),angle);
   const floor=Math.min(pose[5][1],pose[6][1]);
   for(let i=0;i<pose.length;i++)pose[i]=new THREE.Vector3(...pose[i]).applyQuaternion(turn).toArray();
   for(const v of Object.values(aux))if(v?.isVector3)v.applyQuaternion(turn);
   return {pose:pose.map(v=>[v[0],v[1]-floor,v[2]]),aux,points:Object.fromEntries(Object.entries(JOINTS).map(([k,i])=>[k,new THREE.Vector3(...pose[i])]))};
 };
 let motion=S.createAvatarMotion();
 const run=(pose,aux,time=null)=>S.updateAvatarPose({model:root,rig,pose,aux,nameToIndex:JOINTS,motion,allowFeet:true,footMode:'yawFromDir',plantGround:true,groundY:0,useWitness:true,timestampMs:time,sampleTimestampMs:time,presentationTimestampMs:time});
 const rows=[];
 S.setRetargetSmoothing(rig,1.5,1.5);S.setRetargetBoneSmoothing(rig,['leftShoulder','rightShoulder','leftArm','rightArm','leftForeArm','rightForeArm','leftHand','rightHand'],4,4);S.resetRetargetFilters(rig);
 for(let i=0;i<frames.length;i++){
   const f=transform(frames[i]);run(f.pose,f.aux,1000+i*1000/30);
   if(i%4!==0)continue;
   const row={frame:i,directionErrors:{},headQ:q('head').toArray(),neckQ:q('neck').toArray()};
   for(const [name,[start,end]] of Object.entries(map))if(rig.bones.has(name)){
     const p=f.aux[start]||f.points[start],c=f.aux[end]||f.points[end];
     if(p&&c)row.directionErrors[name]=deg(direction(name),c.clone().sub(p));
   }
   // Facial frame uses eye midpoint vs head, not the solver's neck->head up.
   const across=f.aux.left_eye.clone().sub(f.aux.right_eye).normalize();
   const forward=f.aux.left_eye.clone().add(f.aux.right_eye).multiplyScalar(.5).sub(f.aux.head);
   forward.addScaledVector(across,-forward.dot(across)).normalize();
   const up=forward.clone().cross(across).normalize();
   row.sourceFaceQ=new THREE.Quaternion().setFromRotationMatrix(new THREE.Matrix4().makeBasis(across,up,forward)).toArray();
   rows.push(row);
 }
 // Each trial starts from the same neutral input, with smoothing bypassed.
 const neutral=neutralPose(), base={kind:'smpl'};
 for(const [name,i]of Object.entries(JOINTS))base[name]=new THREE.Vector3(...neutral[i]);
 Object.assign(base,{spine1:new THREE.Vector3(0,1.04,0),spine2:new THREE.Vector3(0,1.2,0),spine3:new THREE.Vector3(0,1.4,0),
   neck:new THREE.Vector3(0,1.55,0),head:new THREE.Vector3(0,1.72,0),left_eye:new THREE.Vector3(.035,1.75,.08),right_eye:new THREE.Vector3(-.035,1.75,.08),jaw:new THREE.Vector3(0,1.66,.06)});
 const clone=()=>Object.fromEntries(Object.entries(base).map(([k,v])=>[k,v?.clone?.()||v]));
 const headTrials=[];
 const reset=()=>{motion=S.createAvatarMotion();S.resetRetargetFilters(rig);run(neutral,clone());return {head:q('head'),neck:q('neck')};};
 for(const [axis,angle]of [['yaw',45],['yaw',-45],['pitch',30],['pitch',-30],['roll',25],['roll',-25]]){
   const before=reset(),aux=clone(),rotation=new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(axis==='pitch'?1:0,axis==='yaw'?1:0,axis==='roll'?1:0),angle*Math.PI/180);
   for(const k of ['left_eye','right_eye','jaw'])aux[k].sub(aux.head).applyQuaternion(rotation).add(aux.head);
   run(neutral,aux);
   headTrials.push({axis,inputDegrees:angle,headDegrees:before.head.angleTo(q('head'))*180/Math.PI,neckDegrees:before.neck.angleTo(q('neck'))*180/Math.PI});
 }
 for(const mode of ['missing_eyes','collapsed_eyes','short_eyes']){
   const before=reset(),aux=clone();
   if(mode==='missing_eyes'){delete aux.left_eye;delete aux.right_eye;}
   if(mode==='collapsed_eyes')aux.right_eye.copy(aux.left_eye);
   if(mode==='short_eyes')aux.right_eye.copy(aux.left_eye).add(new THREE.Vector3(0,0,.002));
   run(neutral,aux);
   headTrials.push({axis:mode,inputDegrees:0,headDegrees:before.head.angleTo(q('head'))*180/Math.PI,neckDegrees:before.neck.angleTo(q('neck'))*180/Math.PI});
 }
 // Pose-33 secondary path: neutral face forward (+Z), skull up (+Y).
 const before=reset(),face={left_ear:new THREE.Vector3(.08,1.72,0),right_ear:new THREE.Vector3(-.08,1.72,0),left_eye:new THREE.Vector3(.035,1.75,.08),right_eye:new THREE.Vector3(-.035,1.75,.08),nose:new THREE.Vector3(0,1.73,.11)};
 run(neutral,face);
 const pose33={headDegrees:before.head.angleTo(q('head'))*180/Math.PI,neckDegrees:before.neck.angleTo(q('neck'))*180/Math.PI};
 reset();
 window.auditRenderer?.dispose();document.getElementById('auditCanvas')?.remove();document.getElementById('auditTitle')?.remove();
 const renderer=new THREE.WebGLRenderer({antialias:true,preserveDrawingBuffer:true});renderer.setSize(900,800);renderer.setPixelRatio(1);
 renderer.domElement.id='auditCanvas';Object.assign(renderer.domElement.style,{position:'fixed',left:'0',top:'0',zIndex:10000});document.body.append(renderer.domElement);
 const title=document.createElement('div');title.id='auditTitle';Object.assign(title.style,{position:'fixed',left:'24px',top:'20px',zIndex:10001,color:'white',font:'20px sans-serif',background:'#17212ecc',padding:'12px'});document.body.append(title);
 const scene=new THREE.Scene();scene.background=new THREE.Color('#202c3c');scene.add(a.group);a.group.position.set(0,0,0);a.group.rotation.set(0,0,0);
 scene.add(new THREE.HemisphereLight('#d8edff','#786c64',2));const light=new THREE.DirectionalLight('#fff1db',3);light.position.set(2,3,4);scene.add(light);
 const camera=new THREE.PerspectiveCamera(30,900/800,.01,100),arrows=new THREE.Group();scene.add(arrows);
 window.auditRenderer=renderer;
 window.auditCapture=(axis,angle)=>{
   const before=reset(),aux=clone(),rotation=new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(axis==='pitch'?1:0,axis==='yaw'?1:0,axis==='roll'?1:0),angle*Math.PI/180);
   if(axis==='missing_eyes'){delete aux.left_eye;delete aux.right_eye;}
   else for(const k of ['left_eye','right_eye','jaw'])aux[k].sub(aux.head).applyQuaternion(rotation).add(aux.head);
   run(neutral,aux);a.group.updateWorldMatrix(true,true);
   const head=rig.bones.get('head').bone.getWorldPosition(new THREE.Vector3());
   camera.position.copy(head).add(axis==='pitch'?new THREE.Vector3(2.3,.07,.5):new THREE.Vector3(.1,.07,2.3));camera.lookAt(head.clone().add(new THREE.Vector3(0,-.14,0)));
   arrows.clear();
   const axisVector=axis==='roll'?new THREE.Vector3(0,1,0):new THREE.Vector3(0,0,1),origin=head.clone().add(axis==='pitch'?new THREE.Vector3(.35,0,.32):new THREE.Vector3(-.16,-.1,.65));
   const measured=q('head').multiply(before.head.clone().invert());
   arrows.add(new THREE.ArrowHelper(axisVector.clone().applyQuaternion(rotation),origin,.28,0xff806f,.04,.025),new THREE.ArrowHelper(axisVector.clone().applyQuaternion(measured),origin,.25,0x69d9e7,.04,.025));
   title.textContent=a.avatarId+' / '+axis+' '+angle+'° — vermelho: pedido; azul: avatar';renderer.render(scene,camera);
 };
 return {mapped,allBones,rows,headTrials,pose33};
}"""

reports={}
page_errors=[]
HARNESS='''<!doctype html><html><head><script type="importmap">{"imports":{"three":"https://unpkg.com/three@0.160.0/build/three.module.js","three/addons/":"https://unpkg.com/three@0.160.0/examples/jsm/"}}</script></head><body><select id="avatarSelect"><option>boxer-prism31</option><option>boxeador</option><option>fighter-web</option></select><script type="module">
import * as T from 'three';import * as S from '/static/mikapo_mixamo_solver.js';
import {loadAvatar,CANONICAL_SKELETON_HEIGHT} from '/static/avatar_assets.js';import {JOINTS,neutralPose} from '/static/boxing_core.mjs';
window.cornerDebug={actors:[],paused:true,state:()=>({loaded:!!cornerDebug.actors[0]})};
const select=document.getElementById('avatarSelect');
async function create(){select.disabled=true;try{
const {root}=await loadAvatar(select.value);root.scale.multiplyScalar(1.72/CANONICAL_SKELETON_HEIGHT);const group=new T.Group();group.add(root);
let rig=S.buildAvatarRig(root),motion=S.createAvatarMotion(),pose=neutralPose(),aux={kind:'smpl'};
for(const [name,i]of Object.entries(JOINTS))aux[name]=new T.Vector3(...pose[i]);
for(const [name,v]of Object.entries({spine1:[0,1.05,0],spine2:[0,1.2,0],spine3:[0,1.4,0],left_collar:[.075,1.43,0],right_collar:[-.075,1.43,0],left_eye:[.035,1.74,.075],right_eye:[-.035,1.74,.075],left_foot:[.19,.05,.24],right_foot:[-.19,.05,.09]}))aux[name]=new T.Vector3(...v);aux.head.z+=.065;
S.updateAvatarPose({model:root,rig,motion,pose,aux,nameToIndex:JOINTS,allowFeet:true,plantGround:true,groundY:0});root.updateWorldMatrix(true,true);
const head=rig.bones.get('head').bone.getWorldPosition(new T.Vector3()).y,foot=Math.min(...['leftFoot','rightFoot'].map(n=>rig.bones.get(n).bone.getWorldPosition(new T.Vector3()).y));
root.scale.multiplyScalar(1.72/Math.max(.5,head-foot));rig=S.buildAvatarRig(root);cornerDebug.actors[0]={root,group,rig,avatarId:select.value};
}catch(e){window.auditError=String(e);console.error(e)}finally{select.disabled=false}}
select.onchange=create;await create();
</script></body></html>'''
with sync_playwright() as pw:
    browser=pw.chromium.launch(args=[] if '--default-gpu' in sys.argv else ['--use-angle=d3d11','--ignore-gpu-blocklist'])
    page=browser.new_page(viewport={'width':1440,'height':900})
    page.on('pageerror',lambda e:page_errors.append(str(e)))
    if '--solver-before' in sys.argv:
        before=root/sys.argv[sys.argv.index('--solver-before')+1]
        page.route('**/static/mikapo_mixamo_solver.js',lambda route:route.fulfill(status=200,content_type='text/javascript',body=before.read_text(encoding='utf-8')))
    avatars=[sys.argv[sys.argv.index('--avatar')+1]] if '--avatar' in sys.argv else ['boxer-prism31','boxeador','fighter-web']
    harness=HARNESS.replace('select.onchange=create;await create();','select.onchange=create;select.value='+json.dumps(avatars[0])+';await create();')
    page.route('**/static/retarget-audit',lambda route:route.fulfill(status=200,content_type='text/html',body=harness))
    page.goto('http://127.0.0.1:8780/static/retarget-audit',wait_until='domcontentloaded')
    page.wait_for_function('window.cornerDebug?.state().loaded',timeout=60000)
    page.evaluate('cornerDebug.paused=true')
    for avatar in avatars:
        if page.evaluate('cornerDebug.actors[0].avatarId')!=avatar:
            page.evaluate("id=>{const e=document.getElementById('avatarSelect');e.value=id;e.dispatchEvent(new Event('change'));}",avatar)
            page.wait_for_function('!document.getElementById("avatarSelect").disabled',timeout=60000)
        visual_only='--visual-only' in sys.argv
        report=page.evaluate(PROBE,[] if visual_only else frames)
        for axis,angle in ([] if '--no-images' in sys.argv else [('yaw',45),('pitch',30),('roll',25),('missing_eyes',0)]):
            page.evaluate('args=>auditCapture(args[0],args[1])',[axis,angle])
            page.locator('#auditCanvas').screenshot(path=str(out/f'{avatar}-{axis}.png'))
        if visual_only: continue
        raw=report.pop('rows')
        (out/f'{avatar}-samples.json').write_text(json.dumps(raw),encoding='utf-8')
        report['sourceFrames']=len(frames)
        report['sampledFrames']=len(raw)
        report['directions']={name:{'p50':round(float(np.percentile([r['directionErrors'][name] for r in raw],50)),2),'p95':round(float(np.percentile([r['directionErrors'][name] for r in raw],95)),2)} for name in raw[0]['directionErrors']}
        facial=np.array([quat_to_mat(np.array(r['sourceFaceQ'])) for r in raw])
        skull=np.array([quat_to_mat(np.array(r['headQ'])) for r in raw])
        residual_frames=np.einsum('tji,tjk->tik',facial,skull)
        offset=karcher_mean(residual_frames)
        residual=[ang(offset.T@e) for e in residual_frames]
        report['faceOrientationResidual']={'p50':float(np.percentile(residual,50)),'p95':float(np.percentile(residual,95)),
            'method':'Residual vs raw eye-midpoint/head facial basis after removing ONE constant rig offset, not human truth.'}
        report['uniqueBoneNames']=len(set(report['allBones']))
        reports[avatar]=report
        print(avatar,json.dumps({'mapped':len(report['mapped']),'headTrials':report['headTrials'],'neck':report['directions']['neck']}),flush=True)
    browser.close()
if '--visual-only' in sys.argv: raise SystemExit(0)
solver_path=root/sys.argv[sys.argv.index('--solver-before')+1] if '--solver-before' in sys.argv else root/'viewer/mikapo_mixamo_solver.js'
report={'solverSha256':hashlib.sha256(solver_path.read_bytes()).hexdigest(),
        'headModuleSha256':hashlib.sha256((root/'viewer/avatar_head.js').read_bytes()).hexdigest() if '--solver-before' not in sys.argv else None,
        'method':'Game rig creation/calibration reproduced in an isolated harness, actual assets and current solver. Raw NLF x55 from existing 1056-frame sequence; default smoothing 50%, game-facing clamp, before game leg IK. Head synthetic probes bypass smoothing.',
        'limitations':['Input agreement is not human ground truth.','No live human recording or end-to-end latency measurement.','Clavicle/spine definitions differ across rigs; raw angle includes authored offsets.','Head independent trials rotate eyes/jaw around a stationary skull joint, isolating head orientation.'],
        'avatars':reports,'observedPageErrors':page_errors}
(out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
