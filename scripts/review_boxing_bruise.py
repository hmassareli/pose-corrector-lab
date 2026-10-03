"""Close-up renders of the bruise shader on each avatar's face (before/after hits)."""
from pathlib import Path
from playwright.sync_api import sync_playwright

out = Path(__file__).resolve().parents[1] / 'experiments' / 'boxing_redesign' / 'after'
out.mkdir(parents=True, exist_ok=True)
CLOSEUP = """(tag)=>{const d=cornerDebug,a=d.actors[1],f=d.fighters;
 const head=a.rig.bones.get('head').bone.getWorldPosition(a.root.position.clone().set(0,0,0));
 const dir={x:f[0].x-f[1].x,z:f[0].z-f[1].z};const n=Math.hypot(dir.x,dir.z);
 d.camera.position.set(head.x+dir.x/n*.55+.12,head.y+.12,head.z+dir.z/n*.55);
 d.camera.fov=40;d.camera.updateProjectionMatrix();d.camera.lookAt(head.x,head.y+.08,head.z);
 d.renderer.render(d.scene,d.camera);}"""
with sync_playwright() as p:
    browser = p.chromium.launch(args=['--use-angle=d3d11', '--ignore-gpu-blocklist'])
    page = browser.new_page(viewport={'width': 900, 'height': 700})
    page.on('pageerror', lambda e: print('PAGEERROR', e, flush=True))
    page.goto('http://127.0.0.1:8780/static/boxing.html', wait_until='domcontentloaded')
    page.wait_for_function('window.cornerDebug?.state().loaded', timeout=90000)
    page.evaluate("document.getElementById('train').click()")
    page.evaluate("async()=>{const {neutralPose}=await import('/static/boxing_core.mjs');cornerDebug.reviewPose(neutralPose());}")
    page.wait_for_timeout(800)
    page.evaluate("cornerDebug.paused=true")
    page.wait_for_timeout(300)
    page.evaluate(CLOSEUP, 'clean')
    page.screenshot(path=str(out / '13-face-clean.png'))
    page.evaluate("cornerDebug.paused=false;requestAnimationFrame(cornerDebug.frame)")
    page.evaluate("()=>{cornerDebug.reviewEffect({victim:1,kind:'chin',power:1,head:true,dir:[0,.2,1],hand:1});}")
    page.wait_for_timeout(400)
    page.evaluate("()=>{cornerDebug.reviewEffect({victim:1,kind:'clean',power:.9,head:true,dir:[.5,0,1],hand:0});}")
    page.wait_for_timeout(900)
    page.evaluate("cornerDebug.paused=true")
    page.wait_for_timeout(300)
    page.evaluate(CLOSEUP, 'bruised')
    page.screenshot(path=str(out / '14-face-bruised.png'))
    print(page.evaluate("JSON.stringify(cornerDebug.presentation().bruises[1].map(b=>b.w))"))
    browser.close()
