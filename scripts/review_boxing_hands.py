"""Close-up of an avatar's guard hands in the lobby pose (palm orientation check)."""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

out = Path(__file__).resolve().parents[1] / 'experiments' / 'boxing_redesign' / 'hands'
out.mkdir(parents=True, exist_ok=True)
tag = sys.argv[1] if len(sys.argv) > 1 else 'probe'
avatar = sys.argv[2] if len(sys.argv) > 2 else 'boxer-prism31'
SHOT = """(view)=>{const d=cornerDebug,a=d.actors[0];
 const L=a.rig.bones.get('leftHand').bone.getWorldPosition(a.root.position.clone().set(0,0,0));
 const R=a.rig.bones.get('rightHand').bone.getWorldPosition(a.root.position.clone().set(0,0,0));
 const c=L.clone().add(R).multiplyScalar(.5);const f=d.fighters[0];
 const fwd={x:Math.sin(f.yaw),z:Math.cos(f.yaw)};
 if(view==='front')d.camera.position.set(c.x+fwd.x*2,c.y+.05,c.z+fwd.z*2);
 else d.camera.position.set(c.x+(fwd.z+fwd.x)*1.45,c.y+.1,c.z+(fwd.z-fwd.x)*1.45);
 d.camera.clearViewOffset();d.camera.fov=32;d.camera.updateProjectionMatrix();d.camera.lookAt(c);d.renderer.render(d.scene,d.camera);}"""
with sync_playwright() as p:
    b = p.chromium.launch(args=['--use-angle=d3d11', '--ignore-gpu-blocklist'])
    pg = b.new_page(viewport={'width': 800, 'height': 600})
    pg.add_init_script("localStorage.setItem('labAvatarId','%s')" % avatar)
    pg.goto('http://127.0.0.1:8780/static/boxing.html')
    pg.wait_for_function('window.cornerDebug?.state().loaded', timeout=90000)
    pg.wait_for_timeout(1500)
    pg.evaluate("document.querySelectorAll('header,main,footer,.vignette').forEach(e=>e.style.display='none');cornerDebug.actors[1].group.visible=false")
    pg.evaluate('cornerDebug.paused=true')
    pg.wait_for_timeout(200)
    for view in ['front', 'side']:
        pg.evaluate(SHOT, view)
        pg.screenshot(path=str(out / f'{tag}-{avatar}-{view}.png'))
    print('lost:', pg.evaluate("document.getElementById('arena').getContext('webgl2').isContextLost()"))
    b.close()
