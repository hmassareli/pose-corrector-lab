"""Full11-minute recorded joint replay through actual avatar render corrections.
GPU drawing is skipped during quantitative replay; native skin/bones still update.
"""
import json,time
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'experiments/heavy_hands_gauntlet';data=json.loads((OUT/'live11-render-poses.json').read_text())
PROBE=r'''async data=>{
 const T=await import('three'),core=await import('/static/boxing_core.mjs'),{soleBottom}=await import('/static/boxing_feet.js');const d=cornerDebug;
 d.paused=true;await new Promise(r=>requestAnimationFrame(r));d.enter();document.getElementById('smooth').value=0;document.getElementById('smooth').dispatchEvent(new Event('input'));
 const realNow=performance.now.bind(performance),render=d.renderer.render.bind(d.renderer);let virtual=realNow(),base=virtual;
 Object.defineProperty(performance,'now',{value:()=>virtual,configurable:true});d.renderer.render=()=>{};
 const legs=['leftUpLeg','leftLeg','leftFoot','rightUpLeg','rightLeg','rightFoot'];let nativeLegs=[];let maxLegChange=0;
 let maxLegComponentChange=0;
 d.recorder.stage=(i,name,a)=>{if(name==='retarget')nativeLegs[i]=legs.map(n=>a.rig.bones.get(n).bone.quaternion.clone());if(name==='selfContact')legs.forEach((n,k)=>{const q=a.rig.bones.get(n).bone.quaternion;maxLegChange=Math.max(maxLegChange,nativeLegs[i][k].clone().normalize().angleTo(q.clone().normalize()));for(const key of ['x','y','z','w'])maxLegComponentChange=Math.max(maxLegComponentChange,Math.abs(nativeLegs[i][k][key]-q[key]));});};
 let count=0,floorGood=0,floorMax=0,overlaps=0,maxDepth=0,minDistance=1e9,contactMin=1e9,wristMax=0,positionIndex=0;const bad=[];
 const at=b=>b.getWorldPosition(new T.Vector3());
 for(const row of data.frames){
  virtual=base+row.t;
  while(positionIndex+1<data.positions.length&&data.positions[positionIndex+1].t<=row.t)positionIndex++;
  const recorded=data.positions[positionIndex]?.fighters;
  if(recorded)for(let i=0;i<2;i++){const r=recorded[i],f=d.fighters[i];Object.assign(f,{x:r.x,z:r.z,yaw:r.yaw,pose:r.pose,tracking:false,reaction:null});f.aux=Object.fromEntries(Object.entries(r.aux||{}).map(([k,v])=>[k,Array.isArray(v)&&v.length===3?new T.Vector3(...v):v]));}
  d.reviewPose(row.pose);d.fighters[0].tracking=false;d.frame(virtual);
  const boxes=d.presentation().hitboxes;const depth=core.capsulePenetration(...boxes.map(b=>({...b.body,r:b.body.r-.08}))).depth;
  maxDepth=Math.max(maxDepth,depth);if(depth>.00001){overlaps++;if(bad.length<10)bad.push({t:row.t,depth});}
  minDistance=Math.min(minDistance,Math.hypot(d.fighters[0].x-d.fighters[1].x,d.fighters[0].z-d.fighters[1].z));
  for(const a of d.actors){
   const low=Math.min(...['leftFoot','rightFoot'].map(n=>soleBottom(a,a.rig.bones.get(n).bone))),error=Math.abs(low-.026);floorMax=Math.max(floorMax,error);if(error<=.02)floorGood++;
   for(let h=0;h<2;h++){
    const basis=a.handBasis[h],fore=a.rig.bones.get((h?'right':'left')+'ForeArm').bone,axis=at(basis.hand).sub(at(fore)).normalize(),actual=basis.axis.clone().applyQuaternion(basis.hand.getWorldQuaternion(new T.Quaternion()));
    wristMax=Math.max(wristMax,T.MathUtils.radToDeg(axis.angleTo(actual)));contactMin=Math.min(contactMin,a.guardContact.measure(a.guardContact.hands[h]).gap);
   }
  }
  count++;
  if(count%500===0){console.log('REPLAY '+count+'/'+data.frames.length);await new Promise(r=>setTimeout(r,0));}
 }
 const edge=[];
 for(const [x,z] of [[2.55,2.55],[-2.55,2.55],[2.55,-2.55],[-2.55,-2.55],[0,0]]){
  for(let i=0;i<2;i++){d.fighters[i].x=x;d.fighters[i].z=z;d.fighters[i].yaw=i?Math.PI:0;d.fighters[i].pose=core.neutralPose();d.fighters[i].tracking=false;}
  virtual+=34;d.frame(virtual);edge.push({x,z,depth:core.capsulePenetration(...d.presentation().hitboxes.map(b=>({...b.body,r:b.body.r-.08}))).depth});
 }
 Object.defineProperty(performance,'now',{value:realNow,configurable:true});d.renderer.render=render;d.frame(realNow());
 return {frames:count,avatar:'Prism, both fighters',floorWithin2cm:floorGood/(count*2),floorMax,overlaps,maxDepth,minDistance,contactMin,wristMax,maxLegChangeRadians:maxLegChange,maxLegComponentChange,edge,bad,limitation:'Every accepted joint sample rendered, GPU draw skipped. Source is old NLF output; original bot/root poses held between60saved samples. Does not assert human punch ground truth or skin triangle collision beyond native capsules.'};
}'''
with sync_playwright() as p:
 b=p.chromium.launch(args=['--use-angle=d3d11','--ignore-gpu-blocklist']);page=b.new_page(viewport={'width':1280,'height':800});errors=[];page.on('pageerror',lambda e:errors.append(str(e)));page.on('console',lambda e:print(e.text,flush=True) if e.text.startswith('REPLAY ') else None)
 page.goto('http://127.0.0.1:8780/static/boxing.html');page.wait_for_function('window.cornerDebug?.state().loaded',timeout=90000);start=time.perf_counter();result=page.evaluate(PROBE,data);result.update(seconds=time.perf_counter()-start,errors=errors)
 result['result']='PASS' if result['overlaps']==0 and result['floorWithin2cm']>=.95 and result['wristMax']<10 and result['maxLegChangeRadians']<1e-6 and max(e['depth'] for e in result['edge'])<=.00001 and not errors else 'FAIL'
 (OUT/'live11-geometry-test.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2),flush=True);page.screenshot(path=str(OUT/'live11-last-frame.png'));b.close();assert result['result']=='PASS',result
