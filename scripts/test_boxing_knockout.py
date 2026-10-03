"""Deterministic KO integration checks on the three actual rigs, no webcam.
Includes pose takeover, bounded motion, floor, finite bones, and reset.
"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'experiments/performance_audit_20261003'
OUT.mkdir(parents=True,exist_ok=True)
RUN=r'''async ({fps,direction,victim})=>{
 const T=await import('three'),c=await import('/static/boxing_core.mjs'),d=cornerDebug;
 d.paused=true;await new Promise(r=>requestAnimationFrame(r));
 d.reviewPose(c.neutralPose());d.enter();d.fighters.forEach(f=>f.tracking=false);
 const real=performance.now.bind(performance);let clock=real();
 Object.defineProperty(performance,'now',{value:()=>clock,configurable:true});
 const render=d.renderer.render;d.renderer.render=()=>{};
 for(let i=0;i<20;i++)d.frame(clock+=1000/60);
 const a=d.actors[victim],f=d.fighters[victim];
 const head=a.rig.bones.get('head').bone;
 const startHead=head.getWorldPosition(new T.Vector3());
 f.reaction={kind:'finisher',power:1,dir:direction,start:d.presentation().vclock};
 d.finish({winner:1-victim,ko:true,reason:'knockout'});d.presentation().ko.delay=1e9;
 const start=d.presentation().vclock;
 let maxSlide=0,maxHeadY=startHead.y,minFloor=Infinity,maxJoint=0,maxRootStep=0,previous=a.group.position.clone();
 let settled=null,maxUpStep=0;const rows=[],cpuMs=[];
 // Input continues changing after KO, but the skeleton must belong to KO.
 for(let i=0;i<fps*6;i++){
   f.pose=c.neutralPose();f.pose[12][1]+=(i%2)*.3;
   const cpuStart=real();d.frame(clock+=1000/fps);cpuMs.push(real()-cpuStart);
   const elapsed=(d.presentation().vclock-start)/1000;
   if(elapsed<.12)previous.copy(a.group.position);
   maxUpStep=Math.max(maxUpStep,a.group.position.y-previous.y);
   maxRootStep=Math.max(maxRootStep,a.group.position.distanceTo(previous));previous.copy(a.group.position);
   maxSlide=Math.max(maxSlide,Math.hypot(a.group.position.x-f.x,a.group.position.z-f.z));
   maxHeadY=Math.max(maxHeadY,head.getWorldPosition(new T.Vector3()).y);
   for(const j of a.knockout.joints){
     maxJoint=Math.max(maxJoint,j.bone.quaternion.angleTo(j.base));
     if(j.bone.quaternion.angleTo(j.base)>j.limit+.0001)throw Error('joint exceeds limit '+j.name);
   }
   for(const p of a.knockout.pose)if(p.bone.position.distanceTo(p.position)>1e-8)throw Error('bone length changed');
   a.root.traverse(b=>{if(b.isBone&&!b.matrixWorld.elements.every(Number.isFinite))throw Error('nonfinite bone');});
   if(i%Math.max(1,Math.floor(fps/5))===0)rows.push({elapsed,root:a.group.position.toArray(),head:head.getWorldPosition(new T.Vector3()).toArray()});
   if(elapsed>3&&!settled)settled=a.knockout.joints.map(j=>j.bone.quaternion.clone());
 }
 // Independent full vertex scan validates the sparse runtime floor support.
 const p=new T.Vector3();
 a.root.traverse(m=>{if(!m.isSkinnedMesh)return;m.skeleton.update();
   for(let i=0;i<m.geometry.attributes.position.count;i++){
     p.fromBufferAttribute(m.geometry.attributes.position,i);m.applyBoneTransform(i,p);m.localToWorld(p);minFloor=Math.min(minFloor,p.y);
   }
 });
 const drift=Math.max(...a.knockout.joints.map((j,i)=>j.bone.quaternion.angleTo(settled[i])));
 cpuMs.sort((a,b)=>a-b);
 const result={avatar:a.avatarId,fps,victim,direction,maxSlide,maxHeadRise:maxHeadY-startHead.y,minFloor,maxJoint,maxRootStep,maxUpStep,drift,
   sleeping:!!a.knockout.settled,cpuFrameMs:{p50:cpuMs[Math.floor(cpuMs.length*.5)],p95:cpuMs[Math.floor(cpuMs.length*.95)]},rows};
 d.renderer.render=render;Object.defineProperty(performance,'now',{value:real,configurable:true});
 d.camera.position.set(f.x+3,1.6,f.z+2);d.camera.lookAt(f.x,.6,f.z);d.renderer.render(d.scene,d.camera);
 return result;
}'''

with sync_playwright() as p:
    browser=p.chromium.launch(args=['--use-angle=d3d11','--ignore-gpu-blocklist'])
    page=browser.new_page(viewport={'width':1366,'height':768})
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto('http://127.0.0.1:8780/static/boxing.html')
    page.wait_for_function('window.cornerDebug?.state().loaded',timeout=120000)
    results=[]
    for avatar in ['boxer-prism31','boxeador','fighter-web']:
        page.evaluate('cornerDebug.exit()')
        page.select_option('#avatarSelect',avatar,force=True)
        page.wait_for_function('(id)=>cornerDebug.actors[0]?.avatarId===id',arg=avatar,timeout=120000)
        for fps,direction in [(60,[0,0,-1]),(30,[1,0,0]),(144,[-.7,0,-.7])]:
            result=page.evaluate(RUN,{'fps':fps,'direction':direction,'victim':0})
            results.append(result)
            page.screenshot(path=str(OUT/f'ko-{avatar}-{fps}.png'))
            print(json.dumps({k:v for k,v in result.items() if k!='rows'}),flush=True)
            page.evaluate('''()=>{cornerDebug.exit();if(cornerDebug.actors.some(a=>a.knockout))throw Error('KO not reset');}''')
    result=page.evaluate(RUN,{'fps':60,'direction':[0,0,1],'victim':1});results.append(result)
    report={'results':results,'errors':errors}
    (OUT/'knockout-validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    browser.close()
    assert not errors,errors
    for r in results:
        assert r['maxSlide']<=.221,r
        assert r['maxHeadRise']<.15,r
        assert r['minFloor']>=.010,r
        assert r['maxJoint']>.15,r
        assert r['drift']<.05,r
        assert r['maxUpStep']<.08,r
        assert r['sleeping'],r
    print('PASS: all rigs, 30/60/144 FPS, both victims, bounded joints/root, floor, settling, reset')
