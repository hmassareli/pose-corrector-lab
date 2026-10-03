from pathlib import Path
import json
from playwright.sync_api import sync_playwright
OUT=Path('pose_corrector_lab/experiments/fight_night_refresh/after');OUT.mkdir(exist_ok=True)
with sync_playwright() as p:
 b=p.chromium.launch(args=['--use-angle=d3d11','--ignore-gpu-blocklist'])
 page=b.new_page(viewport={'width':1440,'height':900})
 errors=[]
 page.on('pageerror',lambda e: errors.append(str(e)))
 page.on('console',lambda m: errors.append(m.text) if m.type=='error' and ('THREE' in m.text or 'shader' in m.text.lower()) else None)
 page.goto('http://127.0.0.1:8780/static/boxing.html')
 page.wait_for_function('window.cornerDebug?.state().loaded',timeout=90000)
 page.wait_for_timeout(1000)
 page.screenshot(path=str(OUT/'lobby.png'))
 page.locator('#settingsButton').click();page.screenshot(path=str(OUT/'settings.png'));page.locator('[data-close=settings]').click()
 page.evaluate('''async()=>{const d=cornerDebug,c=await import('/static/boxing_core.mjs');d.enter();window.poseTimer=setInterval(()=>d.reviewPose(c.neutralPose()),40);}''')
 page.wait_for_timeout(1600)
 page.screenshot(path=str(OUT/'arena.png'))
 result=page.evaluate('''async()=>{let times=[],last=performance.now();await new Promise(resolve=>{function f(t){times.push(t-last);last=t;if(times.length<180)requestAnimationFrame(f);else resolve()}requestAnimationFrame(f)});times.sort((a,b)=>a-b);const r=cornerDebug.renderer;const meshes=[];cornerDebug.scene.traverse(o=>{if(o.isMesh)meshes.push({name:o.name,triangles:(o.geometry.index?.count||o.geometry.attributes.position.count)/3,instances:o.count||1,shadow:o.castShadow,material:o.material.type})});return {medianMs:times[90],p95Ms:times[171],calls:r.info.render.calls,triangles:r.info.render.triangles,geometries:r.info.memory.geometries,textures:r.info.memory.textures,meshes:meshes.sort((a,b)=>b.triangles*b.instances-a.triangles*a.instances).slice(0,12)}}''')
 page.evaluate('''()=>{clearInterval(poseTimer);cornerDebug.paused=true;}''');page.wait_for_timeout(80)
 page.evaluate('''()=>{const d=cornerDebug;d.reviewEffect({kind:'finisher',forceN:1800,victim:1,dir:[0,.15,1],head:true,hand:0});d.vfx.fx.update(.065);d.renderer.render(d.scene,d.camera);}''')
 page.screenshot(path=str(OUT/'finisher.png'))
 result['particles']=page.evaluate('''()=>({sparks:cornerDebug.vfx.fx.sparks.mesh.geometry.instanceCount,mist:cornerDebug.vfx.fx.mist.mesh.geometry.instanceCount,drops:cornerDebug.vfx.fx.drops.mesh.geometry.instanceCount,words:document.querySelectorAll('.pow').length})''')
 result['errors']=errors
 (OUT/'metrics.json').write_text(json.dumps(result,indent=2))
 print(json.dumps(result,indent=2))
 b.close()
 assert not errors,errors
