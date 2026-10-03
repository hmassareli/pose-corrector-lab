"""Frame-rate probe: cartoon (outlines) vs classic materials, and the original build."""
import sys
from playwright.sync_api import sync_playwright

MEASURE = """async()=>{const {neutralPose}=await import('/static/boxing_core.mjs');cornerDebug.enter();
const k=setInterval(()=>cornerDebug.reviewPose(neutralPose()),50);await new Promise(r=>setTimeout(r,1500));
let n=0;const t0=performance.now();await new Promise(r=>{function f(){n++;if(performance.now()-t0<3000)requestAnimationFrame(f);else r();}requestAnimationFrame(f);});
clearInterval(k);return {fps:+(n/3).toFixed(1),calls:cornerDebug.renderer.info.render.calls,tris:cornerDebug.renderer.info.render.triangles};}"""
url = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8780/static/boxing.html'
with sync_playwright() as p:
    b = p.chromium.launch(args=['--use-angle=d3d11', '--ignore-gpu-blocklist'])
    for style in ['on', 'off']:
        pg = b.new_page(viewport={'width': 1366, 'height': 768})
        pg.add_init_script("localStorage.setItem('cornerToon','%s')" % style)
        pg.goto(url)
        pg.wait_for_function('window.cornerDebug?.state().loaded', timeout=90000)
        pg.wait_for_timeout(2500)
        print('toon', style, pg.evaluate(MEASURE), flush=True)
        pg.close()
    b.close()
