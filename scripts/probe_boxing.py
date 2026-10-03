from playwright.sync_api import sync_playwright
with sync_playwright() as p:
 b=p.chromium.launch(args=['--use-angle=d3d11','--ignore-gpu-blocklist'])
 page=b.new_page()
 page.goto('http://127.0.0.1:8780/static/boxing.html',wait_until='domcontentloaded')
 page.wait_for_function('window.cornerDebug?.state().loaded')
 page.evaluate("cornerDebug.paused=true;document.getElementById('train').click();cornerDebug.snapCamera=true;cornerDebug.frame(performance.now())")
 print(page.evaluate("async()=>{const T=await import('three');return cornerDebug.actors.map(a=>({scale:a.root.scale.toArray(),position:a.root.position.toArray(),group:a.group.position.toArray(),bones:Object.fromEntries(['head','leftFoot','rightFoot','leftHand','rightHand'].map(n=>[n,a.rig.bones.get(n)?.bone.getWorldPosition(new T.Vector3()).toArray()]))}));}"),flush=True)
 b.close()
