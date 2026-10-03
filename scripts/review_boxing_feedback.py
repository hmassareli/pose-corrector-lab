"""Controlled presentation-latency probe and first-person regression views.
Synthetic inputs isolate render delay; they do not measure live webcam latency.
"""
import json,sys
from pathlib import Path
from playwright.sync_api import sync_playwright

out=Path(__file__).resolve().parents[1]/'experiments'/'boxing_review'
label=sys.argv[1] if len(sys.argv)>1 else 'after'
with sync_playwright() as pw:
 browser=pw.chromium.launch(args=['--use-angle=d3d11','--ignore-gpu-blocklist'])
 page=browser.new_page(viewport={'width':1440,'height':900});errors=[]
 page.on('pageerror',lambda e:errors.append(str(e)))
 page.goto('http://127.0.0.1:8780/static/boxing.html',wait_until='domcontentloaded')
 page.wait_for_function('window.cornerDebug?.state().loaded',timeout=60000)
 page.evaluate('cornerDebug.paused=true');page.wait_for_timeout(100)
 page.locator('#viewButton').click()
 result=page.evaluate("""async()=>{
  const {neutralPose}=await import('/static/boxing_core.mjs');
  const {Vector3}=await import('three');
  document.getElementById('smooth').value=50;
  document.getElementById('smooth').dispatchEvent(new Event('input'));
  cornerDebug.reviewPose(neutralPose());cornerDebug.enter();
  let t=performance.now();
  for(let i=0;i<18;i++){
   if(i%2===0)cornerDebug.reviewPose(neutralPose());
   cornerDebug.frame(t+=1000/60);
  }
  const actor=cornerDebug.actors[0];
  const hand=()=>actor.group.worldToLocal(actor.rig.bones.get('leftHand').bone.getWorldPosition(new Vector3()));
  const origin=hand(),target=neutralPose();target[12]=[-.12,1.48,.75];target[10]=[.35,1.43,.43];
  const samples=[];
  for(let i=0;i<36;i++){
   if(i%2===0)cornerDebug.reviewPose(target.map(v=>v.slice()));
   cornerDebug.frame(t+=1000/60);samples.push({ms:i*1000/60,p:hand().toArray()});
  }
  const delta=new Vector3(...samples.at(-1).p).sub(origin),len=delta.lengthSq();
  const progress=samples.map(s=>({ms:s.ms,ratio:new Vector3(...s.p).sub(origin).dot(delta)/len}));
  return {slider:50,firstResponseMs:progress.find(s=>s.ratio>.05)?.ms,halfResponseMs:progress.find(s=>s.ratio>=.5)?.ms,progress,limitations:'Synthetic pose-to-render probe; excludes camera and inference.'};
 }""")
 page.evaluate("document.getElementById('view').value='first';cornerDebug.view();cornerDebug.snapCamera=true;cornerDebug.frame(performance.now())")
 page.screenshot(path=str(out/f'feedback-{label}-first.png'))
 page.evaluate("""async()=>{
  const {neutralPose}=await import('/static/boxing_core.mjs');const p=neutralPose();
  p[8][2]=.36;p[10]=[.16,1.56,.52];p[12]=[-.04,1.62,.7];
  cornerDebug.reviewPose(p);cornerDebug.frame(performance.now()+1000);cornerDebug.snapCamera=true;cornerDebug.frame(performance.now()+1017);
 }""")
 page.screenshot(path=str(out/f'feedback-{label}-shoulder.png'))
 if label!='before':
  page.wait_for_function('!!window.cornerDebug?.audio.buffers.punch3',timeout=15000)
  audio=page.evaluate('({onsets:cornerDebug.audio.onsets,baseLatency:cornerDebug.audio.ctx.baseLatency})')
  assert all(.15<audio['onsets'][name]<.4 for name in ['punch1','punch2','punch3']),audio
  result['audio']=audio
  recoil=page.evaluate("""async()=>{
   const {Quaternion}=await import('three');
   const actor=cornerDebug.actors[1],bone=actor.rig.bones.get('head').bone;
   cornerDebug.fighters[0].tracking=false;
   cornerDebug.frame(performance.now());const base=bone.quaternion.clone();
   cornerDebug.reviewImpact(1,[1,0,0]);const start=performance.now();
   cornerDebug.frame(start+40);const peak=base.angleTo(bone.quaternion);
   cornerDebug.frame(start+650);const recovered=base.angleTo(bone.quaternion);
   return {peakDegrees:peak*180/Math.PI,recoveredDegrees:recovered*180/Math.PI};
  }""")
  assert recoil['peakDegrees']>1,recoil
  assert recoil['recoveredDegrees']<1,recoil
  result['headReaction']=recoil
  page.evaluate("cornerDebug.reviewImpact(1,[1,0,0]);cornerDebug.frame(performance.now()+40)")
  page.screenshot(path=str(out/'feedback-after-impact.png'))
 result['pageErrors']=errors
 if label!='before':
  pose=page.evaluate("async()=>{const {neutralPose}=await import('/static/boxing_core.mjs');cornerDebug.enter();cornerDebug.reviewPose(neutralPose());return neutralPose();}")
  tracker=next(f for f in page.frames if '/live?' in f.url)
  tracker.evaluate("pose=>parent.postMessage({type:'corner-pose',pose,backend:'nlf',time:performance.now()},location.origin)",pose)
  page.wait_for_timeout(20)
  shifted=[[v[0]+.1,v[1],v[2]] for v in pose]
  tracker.evaluate("pose=>parent.postMessage({type:'corner-pose',pose,backend:'nlf',time:performance.now()},location.origin)",shifted)
  page.wait_for_function('cornerDebug.fighters[0].lateralTarget>.2')
  movement=page.evaluate("""()=>{
   const t=performance.now();cornerDebug.frame(t+17);cornerDebug.frame(t+34);
   const start={x:cornerDebug.fighters[0].x,z:cornerDebug.fighters[0].z};
   for(let i=3;i<18;i++)cornerDebug.frame(t+i*17);
   const end={x:cornerDebug.fighters[0].x,z:cornerDebug.fighters[0].z};
   return {stepX:start.x,heldLateralDrift:Math.abs(end.x-start.x)};
  }""")
  assert movement['stepX']>.12,movement
  assert movement['heldLateralDrift']<.04,movement
  result['webcamLateralMapping']=movement
  target=page.evaluate('cornerDebug.fighters[0].lateralTarget')
  page.locator('#calibrate').click()
  tracker.evaluate("pose=>parent.postMessage({type:'corner-pose',pose,backend:'nlf',time:performance.now()},location.origin)",shifted)
  page.wait_for_timeout(20)
  assert abs(page.evaluate('cornerDebug.fighters[0].lateralTarget')-target)<1e-6
  result['recalibrationPreservesRingPosition']=True
 (out/f'feedback-{label}.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
 print(json.dumps({k:v for k,v in result.items() if k!='progress'},indent=2),flush=True)
 assert not errors,errors
 browser.close()
