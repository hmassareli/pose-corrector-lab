from pathlib import Path
import json
from playwright.sync_api import sync_playwright
root=Path('pose_corrector_lab/experiments/fight_night_refresh')
with sync_playwright() as p:
 b=p.chromium.launch(args=['--use-angle=d3d11','--ignore-gpu-blocklist'])
 page=b.new_page(viewport={'width':1440,'height':900})
 page.goto('http://127.0.0.1:8780/static/boxing.html')
 page.wait_for_function('window.cornerDebug?.state().loaded',timeout=90000)
 page.wait_for_timeout(1000)
 page.screenshot(path=str(root/'before/lobby.png'))
 page.evaluate('''async()=>{const d=cornerDebug,c=await import('/static/boxing_core.mjs');d.enter();window.poseTimer=setInterval(()=>d.reviewPose(c.neutralPose()),40);}''')
 page.wait_for_timeout(1600)
 page.screenshot(path=str(root/'before/arena.png'))
 result=page.evaluate('''async()=>{let times=[],last=performance.now();await new Promise(resolve=>{function f(t){times.push(t-last);last=t;if(times.length<180)requestAnimationFrame(f);else resolve()}requestAnimationFrame(f)});times.sort((a,b)=>a-b);return {medianMs:times[90],p95Ms:times[171],calls:cornerDebug.renderer.info.render.calls,triangles:cornerDebug.renderer.info.render.triangles,geometries:cornerDebug.renderer.info.memory.geometries,textures:cornerDebug.renderer.info.memory.textures}}''')
 (root/'before/metrics.json').write_text(json.dumps(result,indent=2))
 print(result)
 b.close()
