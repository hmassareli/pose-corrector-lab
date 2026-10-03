"""Browser regression for bounded 3D VFX, trails, quality presets and UI.
Uses synthetic poses/effects; does not claim webcam latency or weak-PC FPS.
"""
from pathlib import Path
import json
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'experiments/fight_night_refresh/after'
OUT.mkdir(parents=True,exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch(args=['--use-angle=d3d11','--ignore-gpu-blocklist'])
    context=browser.new_context(viewport={'width':1440,'height':900},locale='pt-BR')
    page=context.new_page(); errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.on('console',lambda m:errors.append(m.text) if m.type=='error' and ('THREE' in m.text or 'shader' in m.text.lower()) else None)
    page.goto('http://127.0.0.1:8780/static/boxing.html')
    page.wait_for_function('window.cornerDebug?.state().loaded',timeout=90000)
    page.wait_for_timeout(1300)
    assert page.locator('#train').is_enabled()
    assert page.locator('#fighterPrev').inner_text()=='‹'
    assert page.locator('#tip').inner_text()=='Afaste-se até o corpo inteiro aparecer na câmera.'
    page.screenshot(path=str(OUT/'lobby.png'))
    page.locator('#settingsButton').click()
    page.screenshot(path=str(OUT/'settings.png'))
    assert page.locator('#artStyle').input_value()=='modern'
    page.locator('[data-close=settings]').click()
    page.evaluate('''async()=>{const d=cornerDebug,c=await import('/static/boxing_core.mjs');
      d.enter();d.fighters[1].ai={mode:'open',until:performance.now()+1e7,next:performance.now()+1e7,guard:.2,punch:null,attack:0};
      window.poseTimer=setInterval(()=>d.reviewPose(c.neutralPose()),40);}''')
    page.wait_for_timeout(2800)
    page.screenshot(path=str(OUT/'arena.png'))
    metrics={}
    for quality in ['high','balanced','low','high']:
        page.evaluate('''q=>{const e=document.getElementById('quality');e.value=q;e.dispatchEvent(new Event('change'));}''',quality)
        page.wait_for_timeout(550)
        result=page.evaluate('''async()=>{const d=cornerDebug,r=d.renderer;let times=[],last=performance.now();
          await new Promise(resolve=>{function f(t){times.push(t-last);last=t;if(times.length<180)requestAnimationFrame(f);else resolve()}requestAnimationFrame(f)});
          times.sort((a,b)=>a-b);return {medianMs:times[90],p95Ms:times[171],calls:r.info.render.calls,triangles:r.info.render.triangles,
          pixelRatio:r.getPixelRatio(),shadows:r.shadowMap.enabled,geometries:r.info.memory.geometries,textures:r.info.memory.textures};}''')
        metrics[quality]=result
        page.screenshot(path=str(OUT/('arena-'+quality+'.png')))
        assert result['shadows']==(quality!='low')
        assert result['pixelRatio']==(.85 if quality=='low' else 1)
    page.evaluate('''()=>{clearInterval(poseTimer);cornerDebug.paused=true;cornerDebug.audio.setEnabled(false);}''')
    page.wait_for_timeout(90)
    tests=page.evaluate('''async()=>{
      const T=await import('three'),d=cornerDebug,{fx,trails}=d.vfx;
      const origin=new T.Vector3(0,1.5,0),velocity=new T.Vector3(4,0,0);
      fx.clear();fx.motion(origin,velocity,1,true,0,.04);fx.update(.01);
      const slow=fx.sparks.mesh.geometry.instanceCount;
      fx.motion(origin,velocity,4,false,0,.04);fx.update(.01);const notStunned=fx.sparks.mesh.geometry.instanceCount;
      fx.motion(origin,velocity,4,true,0,.04);fx.update(.01);const fast=fx.sparks.mesh.geometry.instanceCount;
      if(slow!==0||notStunned!==0||fast===0)throw Error('Finisher velocity/stun gate failed');
      fx.clear();fx.motion(origin,velocity,20,true,0,.04);fx.update(.01);
      if(fx.sparks.mesh.geometry.instanceCount!==0)throw Error('Tracking teleport emitted particles');
      // Stress real pool with repeated impacts, ensuring capacities never grow.
      const memory=[];
      for(let pass=0;pass<3;pass++){
        for(let i=0;i<100;i++){fx.hit([0,1.5,0],i%2?'finisher':'guard',1,[0,.2,1]);fx.update(.016);}
        d.renderer.render(d.scene,d.camera);memory.push({...d.renderer.info.memory});
      }
      const counts=[fx.sparks,fx.mist,fx.drops].map(b=>b.mesh.geometry.instanceCount);
      if(counts.some((n,i)=>n>[160,32,64][i]))throw Error('Unbounded pool');
      if(memory[1].geometries!==memory[2].geometries||memory[1].textures!==memory[2].textures)throw Error('VFX GPU resource leak');
      for(let i=0;i<80;i++)fx.update(1/60);
      if([fx.sparks,fx.mist,fx.drops].some(b=>b.mesh.visible))throw Error('Particles did not expire');
      const trail=trails[0][0];trail.reset();
      for(let i=0;i<12;i++)trail.update(new T.Vector3(i*.04,1.5,0),1,'#009dff',.13,d.camera,1/60);
      const a=trail.position;const width=Math.hypot(a[0]-a[3],a[1]-a[4],a[2]-a[5]);
      if(Math.abs(width-.26)>.001)throw Error('Glove trail width regression');
      if(!Array.from(a).every(Number.isFinite))throw Error('Invalid ribbon vertices');
      trail.update(new T.Vector3(5,1.5,0),1,'#009dff',.13,d.camera,1/60);
      if(trail.mesh.visible)throw Error('Teleport bridged by trail');
      for(let i=0;i<90;i++)trail.update(new T.Vector3(5,1.5,0),0,'#009dff',.13,d.camera,1/60);
      if(trail.mesh.visible)throw Error('Idle trail did not fade');
      trail.reset();fx.clear();
      return {slow,notStunned,fast,counts,memory,trailWidth:width,words:document.querySelectorAll('.pow').length};
    }''')
    # Side-on review: impact source on visible native head surface; synthetic swing.
    page.evaluate('''async()=>{const T=await import('three'),d=cornerDebug;
      d.camera.position.set(2.5,2.25,-2.1);d.camera.lookAt(0,1,0);d.camera.updateMatrixWorld();
      const head=d.actors[1].rig.bones.get('head').bone.getWorldPosition(new T.Vector3());
      head.add(new T.Vector3(.12,.07,-.08));d.vfx.fx.hit(head.toArray(),'finisher',1,[1,.25,-.3]);
      for(let i=0;i<5;i++)d.vfx.fx.update(1/60);
      const hand=new T.Vector3(...d.presentation().hitboxes[0].gloves[1]);window.reviewHand=hand;
      const trail=d.vfx.trails[0][1];trail.reset();
      for(let i=0;i<12;i++){const a=(i-11)*.07,p=hand.clone().add(new T.Vector3(-Math.sin(a)*.85,Math.cos(a)*.35-.35,-a*.5));trail.update(p,1,'#ff9b0a',.14,d.camera,1/60);}
      d.renderer.render(d.scene,d.camera);}''')
    page.screenshot(path=str(OUT/'finisher.png'))
    page.evaluate('''async()=>{const T=await import('three'),d=cornerDebug;d.vfx.fx.clear();d.vfx.trails.flat().forEach(t=>t.reset());
      d.vfx.fx.hit(reviewHand.toArray(),'guard',.7,[1,.2,-.3]);for(let i=0;i<4;i++)d.vfx.fx.update(1/60);d.renderer.render(d.scene,d.camera);}''')
    page.screenshot(path=str(OUT/'block.png'))
    # First-person camera and alternate venue run through the real frame callback.
    page.evaluate('''()=>{const d=cornerDebug;d.view('first');d.frame(performance.now()+17);d.renderer.render(d.scene,d.camera);}''')
    page.screenshot(path=str(OUT/'first-person.png'))
    page.evaluate('''()=>{const e=document.getElementById('venue');e.value='dawn';e.dispatchEvent(new Event('change'));cornerDebug.frame(performance.now()+17);}''')
    page.screenshot(path=str(OUT/'dawn.png'))
    page.evaluate('''()=>{cornerDebug.finish({winner:0,ko:false});cornerDebug.presentation().ko.start-=2000;cornerDebug.frame(performance.now()+17);}''')
    page.screenshot(path=str(OUT/'result.png'))
    page.locator('#again').click()
    page.set_viewport_size({'width':800,'height':600});page.wait_for_timeout(150)
    page.screenshot(path=str(OUT/'small-lobby.png'))
    page.evaluate('''()=>{const e=document.getElementById('quality');e.value='low';e.dispatchEvent(new Event('change'));}''')
    page.reload();page.wait_for_function('window.cornerDebug?.state().loaded',timeout=90000)
    assert page.locator('#quality').input_value()=='low'
    assert not page.evaluate('cornerDebug.renderer.shadowMap.enabled')
    assert not errors,errors
    (OUT/'validation.json').write_text(json.dumps({'metrics':metrics,'tests':tests,'errors':errors},indent=2),encoding='utf-8')
    print(json.dumps({'metrics':metrics,'tests':tests,'errors':errors},indent=2))
    browser.close()
print('Fight-night presentation PASS')

