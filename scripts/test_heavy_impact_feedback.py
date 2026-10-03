"""Before/after native KO/head trajectories and actual narrator/impact visuals."""
import json,time
from pathlib import Path
from playwright.sync_api import sync_playwright
root=Path(__file__).resolve().parents[1];out=root/'experiments/heavy_hands_gauntlet';before=out/'impact-feedback-before'
MOTION=r'''async()=>{
 const T=await import('three'),core=await import('/static/boxing_core.mjs'),feet=await import('/static/boxing_feet.js'),d=cornerDebug;
 d.paused=true;await new Promise(r=>requestAnimationFrame(r));d.enter();d.reviewPose(core.neutralPose());d.fighters[0].tracking=false;
 const real=performance.now.bind(performance);let clock=real();Object.defineProperty(performance,'now',{value:()=>clock,configurable:true});
 const render=d.renderer.render.bind(d.renderer);d.renderer.render=()=>{};
 for(let i=0;i<24;i++)d.frame(clock+=1000/60);
 const f=d.fighters[1],a=d.actors[1],head=a.rig.bones.get('head').bone;
 const at=()=>head.getWorldPosition(new T.Vector3());let old=at(),headSpeed=0;
 d.reviewEffect({kind:'chin',forceN:1200,victim:1,dir:[0,0,1],head:true,hand:0});
 for(let i=0;i<50;i++){d.frame(clock+=1000/60);const p=at();headSpeed=Math.max(headSpeed,p.distanceTo(old)*60);old=p;}
 f.reaction={kind:'finisher',power:1,dir:[0,0,1],head:true,start:d.presentation().vclock};
 d.finish({winner:0,ko:true,reason:'knockout'});const start=d.presentation().vclock;
 let lastZ=a.group.position.z,lastTime=start,maxSlide=0,maxSpeed=0,minGround=1e9;const rows=[];
 for(let i=0;i<210;i++){
  d.frame(clock+=1000/60);const t=d.presentation().vclock,p=a.group.position;
  if(t>lastTime)maxSpeed=Math.max(maxSpeed,Math.abs(p.z-lastZ)/((t-lastTime)/1000));
  lastZ=p.z;lastTime=t;maxSlide=Math.max(maxSlide,Math.abs(p.z-f.z));
  const ground=Math.min(...['leftFoot','rightFoot'].map(n=>feet.soleBottom(a,a.rig.bones.get(n).bone)),...(a.headSurface?.points||[]).map(q=>head.localToWorld(q.clone()).y));minGround=Math.min(minGround,ground);
  if(i%6===0)rows.push({ms:t-start,root:p.toArray(),head:at().toArray(),ground});
 }
 d.renderer.render=render;Object.defineProperty(performance,'now',{value:real,configurable:true});
 return {headPeakWorldSpeed:headSpeed,KOmaxSlide:maxSlide,KOmaxSlideSpeed:maxSpeed,minGround,rows};
}'''
with sync_playwright() as p:
 b=p.chromium.launch(args=['--use-angle=d3d11','--ignore-gpu-blocklist']);results={};errors=[]
 for label in ['before','after']:
  ctx=b.new_context(viewport={'width':1440,'height':900});page=ctx.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
  if label=='before':
   for name in ['boxing.js','boxing_core.mjs','boxing_ui.css']:
    page.route('**/static/'+name,lambda route,request,n=name:route.fulfill(path=str(before/n)))
  page.goto('http://127.0.0.1:8780/static/boxing.html');page.wait_for_function('window.cornerDebug?.state().loaded',timeout=90000)
  results[label]=page.evaluate(MOTION)
  page.screenshot(path=str(out/('impact-'+label+'-ko.png')));ctx.close()
 assert results['after']['KOmaxSlide']<=.221,results
 assert results['after']['KOmaxSlideSpeed']<.32,results
 assert results['after']['minGround']>=.016,results
 assert results['after']['headPeakWorldSpeed']<results['before']['headPeakWorldSpeed']*.8,results
 results['errors']=errors;results['result']='PASS' if not errors else 'FAIL'
 (out/'impact-feedback-test.json').write_text(json.dumps(results,indent=2));print(json.dumps({k:{x:y for x,y in v.items() if x!='rows'} if isinstance(v,dict) else v for k,v in results.items()},indent=2),flush=True);b.close();assert not errors,errors
