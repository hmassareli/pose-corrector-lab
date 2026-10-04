"""Native head/glove measurements and kinematic self-contact on all three rigs."""
import ast,json
from pathlib import Path
from playwright.sync_api import sync_playwright

root=Path(__file__).resolve().parents[1]
out=root/'experiments/avatar_self_contact'
out.mkdir(exist_ok=True)
tree=ast.parse((root/'scripts/audit_avatar_retarget.py').read_text(encoding='utf-8'))
harness=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='HARNESS' for t in n.targets))
probe=r'''async()=>{
 const T=await import('three'),S=await import('/static/mikapo_mixamo_solver.js');
 const {NativeGuardContact,sampleBoneSurface}=await import('/static/avatar_self_contact.js');
 const {solveTwoBone}=await import('/static/boxing_ik.js');
 const {neutralPose,JOINTS}=await import('/static/boxing_core.mjs');
 const a=cornerDebug.actors[0];a.group.updateWorldMatrix(true,true);
 let motion=S.createAvatarMotion(),time=1000;
 const auxFor=p=>{
   const x={kind:'smpl'};for(const [n,i]of Object.entries(JOINTS))x[n]=new T.Vector3(...p[i]);
   Object.assign(x,{spine1:new T.Vector3(0,1.04,0),spine2:new T.Vector3(0,1.2,0),spine3:new T.Vector3(0,1.4,0),
   neck:new T.Vector3(0,1.55,0),head:new T.Vector3(0,1.72,0),left_eye:new T.Vector3(.035,1.75,.08),right_eye:new T.Vector3(-.035,1.75,.08),jaw:new T.Vector3(0,1.66,.06)});
   for(const side of ['left','right']){const w=x[side+'_wrist'];x[side+'_hand']=w.clone().add(new T.Vector3(0,.06,.01));
     x[side+'_index']=w.clone().add(new T.Vector3(.025,.06,.01));x[side+'_pinky']=w.clone().add(new T.Vector3(-.025,.06,.01));}
   return x;
 };
 const feed=(p=neutralPose(),angles=[0,0,0])=>{
   time+=1000/30;const aux=auxFor(p),q=new T.Quaternion().setFromEuler(new T.Euler(...angles.map(T.MathUtils.degToRad),'YXZ'));
   for(const n of ['left_eye','right_eye','jaw'])aux[n].sub(aux.head).applyQuaternion(q).add(aux.head);
   S.updateAvatarPose({model:a.root,rig:a.rig,motion,pose:p,aux,nameToIndex:JOINTS,allowFeet:true,plantGround:true,groundY:0,
     sampleTimestampMs:time,presentationTimestampMs:time});a.group.updateWorldMatrix(true,true);
 };
 feed();const contact=new NativeGuardContact(a),dims=contact.dimensions(),rows=[];
 const actualInside=h=>{
   const origin=contact.headBone.getWorldPosition(new T.Vector3()),inverse=contact.headBone.getWorldQuaternion(new T.Quaternion()).invert();
   const q=h.hand.getWorldQuaternion(new T.Quaternion()),w=h.hand.getWorldPosition(new T.Vector3());
   const cloud=sampleBoneSurface(a,h.hand);
   return Math.min(...cloud.map(p=>contact.surface.distance(p.applyQuaternion(q).add(w).sub(origin).applyQuaternion(inverse),0,-Infinity).gap));
 };
 for(const angles of [[0,0,0],[30,0,0],[-25,0,0],[0,40,0],[0,0,25]]){
   for(const z of [-.08,.02,.10,.18,.30,.55]){
     const p=neutralPose();p[10]=[.32,1.38,.12];p[11]=[-.32,1.38,.12];p[12]=[.12,1.67,z];p[13]=[-.12,1.67,z];
     feed(p,angles);contact.reset();
     const headQ=contact.headBone.getWorldQuaternion(new T.Quaternion()).normalize();
     const palms=contact.hands.map(h=>h.hand.getWorldQuaternion(new T.Quaternion()).normalize());
     const lengths=contact.hands.map(h=>[h.arm.getWorldPosition(new T.Vector3()).distanceTo(h.fore.getWorldPosition(new T.Vector3())),h.fore.getWorldPosition(new T.Vector3()).distanceTo(h.hand.getWorldPosition(new T.Vector3()))]);
     const before=contact.hands.map(actualInside);contact.apply(a,time);const after=contact.hands.map(actualInside);
     const headDelta=T.MathUtils.radToDeg(headQ.angleTo(contact.headBone.getWorldQuaternion(new T.Quaternion()).normalize()));
     const palmDelta=Math.max(...contact.hands.map((h,i)=>T.MathUtils.radToDeg(palms[i].angleTo(h.hand.getWorldQuaternion(new T.Quaternion()).normalize()))));
     const lengthDelta=Math.max(...contact.hands.flatMap((h,i)=>[Math.abs(lengths[i][0]-h.arm.getWorldPosition(new T.Vector3()).distanceTo(h.fore.getWorldPosition(new T.Vector3()))),Math.abs(lengths[i][1]-h.fore.getWorldPosition(new T.Vector3()).distanceTo(h.hand.getWorldPosition(new T.Vector3())))]));
     rows.push({angles,z,beforeSkin:before,afterSkin:after,headDelta,palmDelta,lengthDelta,hands:contact.diagnostics});
   }
 }
 // Incoming and withdrawing guards must respond continuously at the contact
 // boundary, with an unchanged fully extended punch outside that band.
 contact.reset();const trajectory=[];
 for(let i=0;i<=40;i++){
   const z=.6-i*.015,p=neutralPose();p[12]=[.12,1.67,z];p[13]=[-.12,1.67,z];feed(p);contact.apply(a,time);
   trajectory.push({z,hand:contact.hands[0].hand.getWorldPosition(new T.Vector3()).toArray(),gap:contact.diagnostics[0].afterGap,correction:contact.diagnostics[0].correction});
 }
 const out=neutralPose();out[12]=[.12,1.67,.65];out[13]=[-.12,1.67,.65];feed(out);contact.apply(a,time);
 const release=contact.diagnostics.map(h=>h.correction);
 contact.reset();const held=neutralPose();held[10]=[.32,1.38,.12];held[11]=[-.32,1.38,.12];held[12]=[.12,1.67,.02];held[13]=[-.12,1.67,.02];
 feed(held);contact.apply(a,time);const heldStart=contact.hands.map(h=>h.hand.getWorldPosition(new T.Vector3()));let heldDrift=0;
 for(let i=0;i<20;i++){feed(held);contact.apply(a,time);for(let j=0;j<2;j++)heldDrift=Math.max(heldDrift,heldStart[j].distanceTo(contact.hands[j].hand.getWorldPosition(new T.Vector3())));}
 // Explicit fast traversal from in front of the face to behind the cranium.
 feed();contact.reset();const h=contact.hands[0],q=h.hand.getWorldQuaternion(new T.Quaternion());
 const headOrigin=contact.headBone.getWorldPosition(new T.Vector3()),headQ=contact.headBone.getWorldQuaternion(new T.Quaternion());
 const middle=new T.Box3().setFromPoints(contact.headPoints).getCenter(new T.Vector3()).applyQuaternion(headQ).add(headOrigin);
 const forward=new T.Vector3(0,0,1).applyQuaternion(a.root.getWorldQuaternion(new T.Quaternion()));
 const place=(center)=>{const wrist=center.clone().sub(h.sphere.center.clone().applyQuaternion(q));solveTwoBone(h.arm,h.fore,h.hand,wrist,forward);h.hand.quaternion.copy(h.hand.parent.getWorldQuaternion(new T.Quaternion()).invert().multiply(q));h.hand.updateWorldMatrix(false,true);};
 place(middle.clone().addScaledVector(forward,.25+h.sphere.radius));contact.apply(a,time+=33);
 place(middle.clone().addScaledVector(forward,-.25-h.sphere.radius));const crossingBefore=contact.measure(h);contact.apply(a,time+=33);
 const crossing={before:crossingBefore.gap,...contact.diagnostics[0]};
 contact.reset();place(middle.clone());const insideBefore=contact.measure(h).gap;contact.apply(a,time+=33);
 const inside={before:insideBefore,...contact.diagnostics[0],skinAfter:actualInside(h)};
 // Isolate the contact solver's cost from camera, rendering and NLF.
 contact.reset();const measureStart=performance.now();for(let i=0;i<100;i++)contact.apply(a,time+=16);
 const millisecondsPerApply=(performance.now()-measureStart)/100;
 window.captureGuard=(enabled)=>{
   const p=neutralPose();p[10]=[.32,1.38,.12];p[11]=[-.32,1.38,.12];p[12]=[.12,1.67,.02];p[13]=[-.12,1.67,.02];feed(p);contact.reset();if(enabled)contact.apply(a,time);
   const scene=new T.Scene();scene.background=new T.Color('#202c3c');scene.add(a.group);
   scene.add(new T.HemisphereLight('#d8edff','#786c64',2));const light=new T.DirectionalLight('#fff1db',3);light.position.set(2,3,4);scene.add(light);
   const r=window.guardRenderer ||= new T.WebGLRenderer({antialias:true,preserveDrawingBuffer:true});r.setSize(900,800);r.setPixelRatio(1);
   r.domElement.id='guardCanvas';document.body.append(r.domElement);Object.assign(r.domElement.style,{position:'fixed',left:'0',top:'0',zIndex:1000});
   const head=contact.headBone.getWorldPosition(new T.Vector3()),camera=new T.PerspectiveCamera(34,900/800,.01,100);
   camera.position.copy(head).add(new T.Vector3(1.45,.16,1.5));camera.lookAt(head.clone().add(new T.Vector3(0,-.18,0)));r.render(scene,camera);
 };
 return {avatar:a.avatarId,dimensions:dims,rows,trajectory,release,crossing,inside,millisecondsPerApply,heldDrift,
  worstSkinBefore:Math.min(...rows.flatMap(r=>r.beforeSkin)),worstSkinAfter:Math.min(...rows.flatMap(r=>r.afterSkin)),
  worstGapAfter:Math.min(...rows.flatMap(r=>r.hands.map(h=>h.afterGap))),
  maximumHeadDelta:Math.max(...rows.map(r=>r.headDelta)),maximumPalmDelta:Math.max(...rows.map(r=>r.palmDelta)),maximumLengthDelta:Math.max(...rows.map(r=>r.lengthDelta)),
  maximumTrajectoryStep:Math.max(...trajectory.slice(1).map((r,i)=>new T.Vector3(...r.hand).distanceTo(new T.Vector3(...trajectory[i].hand))))};
}'''

reports=[]
with sync_playwright() as pw:
 for avatar in ['boxer-prism31','boxeador','fighter-web']:
  browser=pw.chromium.launch()
  page=browser.new_page();errors=[]
  page.on('pageerror',lambda e: errors.append(str(e)))
  html=harness.replace('select.onchange=create;await create();','select.onchange=create;select.value='+json.dumps(avatar)+';await create();')
  page.route('**/static/retarget-audit',lambda r:r.fulfill(status=200,content_type='text/html',body=html))
  page.goto('http://127.0.0.1:8780/static/retarget-audit',wait_until='domcontentloaded')
  page.wait_for_function('window.cornerDebug?.state().loaded || window.auditError',timeout=60000)
  assert not page.evaluate('window.auditError'),page.evaluate('window.auditError')
  print('Loaded '+avatar+'; measuring native skin and contacts',flush=True)
  report=page.evaluate(probe);report['errors']=errors;reports.append(report)
  (out/f'{avatar}.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
  print(json.dumps({k:v for k,v in report.items() if k not in ['rows','trajectory']}),flush=True)
  checks={'native_scale':min(report['dimensions']['headSize'])>.08,
    'guard_no_skin_penetration':report['worstSkinAfter']>=.002,
    'hard_contact':report['worstGapAfter']>=.0039,
    'head_unchanged':report['maximumHeadDelta']<.0001,
    'palm_orientation_preserved':report['maximumPalmDelta']<.0001,
    'native_arm_lengths':report['maximumLengthDelta']<.000001,
    'no_boundary_snap':report['maximumTrajectoryStep']<.025,
    'held_guard_no_drift':report['heldDrift']<.001,
    'immediate_withdrawal':max(report['release'])<.000001,
    'swept_no_tunneling':report['crossing']['swept'] and report['crossing']['afterGap']>=.0039,
    'deep_contact':report['inside']['afterGap']>=.0039 and report['inside']['skinAfter']>=.002,
    'unrestricted_outside_band':all(h['correction']<.000001 for r in report['rows'] for h in r['hands'] if h['beforeGap']>=.024),
    'no_page_errors':not errors}
  report['checks']=checks
  (out/f'{avatar}.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
  for enabled in [False,True]:
   page.evaluate('captureGuard',enabled)
   page.locator('#guardCanvas').screenshot(path=str(out/(avatar+('-after' if enabled else '-before')+'.png')))
  browser.close()
(out/'report.json').write_text(json.dumps(reports,indent=2),encoding='utf-8')
assert all(all(r['checks'].values()) for r in reports),'See experiments/avatar_self_contact/report.json'

