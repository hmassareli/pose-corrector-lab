"""NLF-only leg fidelity and camera translation through the actual message adapter."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
root=Path(__file__).resolve().parents[1];out=root/'experiments/heavy_hands_gauntlet'
TEST=r'''async()=>{
 const T=await import('three'),core=await import('/static/boxing_core.mjs'),{soleBottom}=await import('/static/boxing_feet.js');const d=cornerDebug;d.paused=true;await new Promise(r=>requestAnimationFrame(r));d.enter();
 const real=performance.now.bind(performance);let time=real();Object.defineProperty(performance,'now',{value:()=>time,configurable:true});
 document.getElementById('smooth').value=0;document.getElementById('smooth').dispatchEvent(new Event('input'));d.reviewPose(core.neutralPose());
 const f=d.fighters[0],bot=d.fighters[1];bot.ai={mode:'guard',guard:1,until:1e9,next:1e9,punch:null};
 const tracker=document.getElementById('tracker').contentWindow,source=()=>core.neutralPose().map(v=>[v[0],v[1]-.92,v[2]-4]);
 const feed=(points,info={size:[640,360],fov:55})=>{time+=35;window.dispatchEvent(new MessageEvent('message',{origin:location.origin,source:tracker,data:{type:'corner-pose',time,pose:core.neutralPose(),cameraPose:points,cameraInfo:info,backend:'nlf'}}));d.frame(time);};
 for(let i=0;i<20;i++)feed(source());const calibrated=!!f.footwork.reference,rootBefore={x:f.x,z:f.z};
 const at=n=>d.actors[0].rig.bones.get(n).bone.getWorldPosition(new T.Vector3());const feetBefore=[at('leftFoot').toArray(),at('rightFoot').toArray()];
 const lift=source();lift[5][1]+=.22;lift[5][2]+=.35;lift[3][1]+=.08;lift[3][2]+=.22;for(let i=0;i<10;i++)feed(lift);
 const feetAfter=[at('leftFoot').toArray(),at('rightFoot').toArray()],rootAfterFoot={x:f.x,z:f.z};
 const distanceBefore=Math.hypot(f.x-bot.x,f.z-bot.z);const forward=source().map(v=>[v[0]+.12,v[1],v[2]+.2]);for(let i=0;i<12;i++)feed(forward);
 const translation={lateral:f.lateralTarget,radial:f.radialTarget},distanceAfter=Math.hypot(f.x-bot.x,f.z-bot.z),soles=[];
 // Cropping the image never substitutes an inferred gait for those same joints.
 for(let i=0;i<40;i++){feed(forward,{size:[640,210],fov:55});soles.push(Math.min(...['leftFoot','rightFoot'].map(n=>soleBottom(d.actors[0],d.actors[0].rig.bones.get(n).bone))));}
 Object.defineProperty(performance,'now',{value:real,configurable:true});return {calibrated,rootBefore,rootAfterFoot,feetBefore,feetAfter,translation,distanceBefore,distanceAfter,soleMaxError:Math.max(...soles.map(y=>Math.abs(y-.026))),hasSyntheticFeet:Object.hasOwn(f,'footContacts')||Object.hasOwn(f,'footVisible'),sourcePose:f.pose,sourceLegs:forward.slice(1,7)};
}'''
with sync_playwright() as p:
 b=p.chromium.launch(args=['--use-angle=d3d11','--ignore-gpu-blocklist']);page=b.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)));page.goto('http://127.0.0.1:8780/static/boxing.html');page.wait_for_function('window.cornerDebug?.state().loaded',timeout=90000);r=page.evaluate(TEST)
 assert r['calibrated'] and not r['hasSyntheticFeet'] and not errors,r
 assert abs(r['rootAfterFoot']['x']-r['rootBefore']['x'])<.001 and abs(r['rootAfterFoot']['z']-r['rootBefore']['z'])<.001,r
 assert r['feetAfter'][0][1]-r['feetBefore'][0][1]>.03,r
 assert r['translation']['radial']>.15 and r['translation']['lateral']>.1,r
 assert r['soleMaxError']<=.02,r
 r.update(result='PASS',errors=errors,checks=['500ms stable calibration','foot lift follows NLF','foot lift does not invent root step','metric lateral/depth adapter','image crop adds no synthetic gait','sole within2cm']);(out/'footwork-test.json').write_text(json.dumps(r,indent=2));print(json.dumps(r,indent=2),flush=True);b.close()
