"""Review the whole physical collapse, not just its last frame.
Produces contact sheets / individual frames and numeric joint trajectories.
No camera, no online room. Default: three avatars; optional single avatar arg.
"""
import json,sys
from pathlib import Path
from playwright.sync_api import sync_playwright
from PIL import Image,ImageDraw

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'experiments/knockout_ragdoll_20261003'
OUT.mkdir(parents=True,exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch(args=['--use-angle=d3d11','--ignore-gpu-blocklist'])
    page=browser.new_page(viewport={'width':1100,'height':760})
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto('http://127.0.0.1:8780/static/boxing.html')
    page.wait_for_function('window.cornerDebug?.state().loaded',timeout=120000)
    results=[]
    for avatar in (sys.argv[1:] or ['boxer-prism31','boxeador','fighter-web']):
        page.evaluate('cornerDebug.exit()')
        page.select_option('#avatarSelect',avatar,force=True)
        page.wait_for_function('(id)=>cornerDebug.actors[0]?.avatarId===id',arg=avatar,timeout=120000)
        page.evaluate('''async()=>{
          window.T=await import('three');window.core=await import('/static/boxing_core.mjs');
          const d=cornerDebug;d.paused=true;await new Promise(r=>requestAnimationFrame(r));
          d.reviewPose(core.neutralPose());d.enter();d.fighters.forEach(f=>f.tracking=false);
          window.realNow=performance.now.bind(performance);window.testClock=realNow();
          Object.defineProperty(performance,'now',{value:()=>testClock,configurable:true});
          window.actualRender=d.renderer.render.bind(d.renderer);d.renderer.render=()=>{};
          for(let i=0;i<20;i++)d.frame(testClock+=1000/60);
          window.actor=d.actors[0];window.initial={};
          for(const n of ['hips','head','leftUpLeg','leftLeg','leftFoot','rightUpLeg','rightLeg','rightFoot'])
            initial[n]=actor.rig.bones.get(n).bone.getWorldPosition(new T.Vector3()).toArray();
          d.fighters[0].reaction={kind:'finisher',power:1,dir:[0,0,-1],start:d.presentation().vclock};
          d.finish({winner:1,ko:true,reason:'knockout'});d.presentation().ko.delay=1e9;
          window.rows=[];
          window.measure=()=>{
            const pos=n=>actor.rig.bones.get(n).bone.getWorldPosition(new T.Vector3());
            const bend=s=>{const h=pos(s+'UpLeg'),k=pos(s+'Leg'),f=pos(s+'Foot');return k.clone().sub(h).angleTo(f.sub(k))*180/Math.PI;};
            return {t:actor.knockout.time,hips:pos('hips').toArray(),head:pos('head').toArray(),
              knees:[bend('left'),bend('right')],groupQuaternion:actor.group.quaternion.toArray(),...actor.knockout.diagnostics()};
          };
        }''')
        captures=[]
        for t in [0,.2,.4,.65,.9,1.3,2,4,6]:
            info=page.evaluate('''t=>{
              const d=cornerDebug;let guard=0;
              while(actor.knockout.time<t-.001&&!actor.knockout.settled&&guard++<1800){
                d.fighters[0].pose=core.neutralPose();d.frame(testClock+=1000/60);rows.push(measure());
              }
              const info=measure();
              d.camera.position.set(3.4,1.7,2.3);d.camera.lookAt(0,.75,-.65);
              actualRender(d.scene,d.camera);return info;
            }''',t)
            file=OUT/f'{avatar}-{t:.2f}.png';page.screenshot(path=str(file));captures.append((file,t))
            print(json.dumps({'avatar':avatar,'sample':t,**{k:info[k] for k in ['t','hips','head','knees','anchorError','settled']}}),flush=True)
        result=page.evaluate('''()=>{
          let minFloor=Infinity;const p=new T.Vector3();
          actor.root.traverse(m=>{if(!m.isSkinnedMesh)return;m.skeleton.update();
            for(let i=0;i<m.geometry.attributes.position.count;i++){
              p.fromBufferAttribute(m.geometry.attributes.position,i);m.applyBoneTransform(i,p);m.localToWorld(p);minFloor=Math.min(minFloor,p.y);
            }});
          const result={avatar:actor.avatarId,initial,rows,minFloor};
          cornerDebug.renderer.render=actualRender;Object.defineProperty(performance,'now',{value:realNow,configurable:true});
          cornerDebug.exit();return result;
        }''');results.append(result)
        sheet=Image.new('RGB',(1650,1170),'#11151c');draw=ImageDraw.Draw(sheet)
        for i,(path,t) in enumerate(captures):
            im=Image.open(path);im.thumbnail((550,370));x=(i%3)*550;y=(i//3)*390
            sheet.paste(im,(x,y));draw.text((x+12,y+371),f'{avatar} | {t:.2f}s physics',fill='white')
        sheet.save(OUT/f'{avatar}-sequence.jpg',quality=90)
    (OUT/'review.json').write_text(json.dumps({'results':results,'errors':errors},indent=2),encoding='utf-8')
    print('Browser errors:',errors,flush=True)
    browser.close()
    assert not errors,errors
