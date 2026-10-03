import json, sys, threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from playwright.sync_api import sync_playwright
sys.path[:0]=['scripts']
from check_palm_fidelity import Handler

LAB=Path('.').resolve(); OUT=LAB/'experiments/bone_crook'
OLD=LAB/'experiments/_solver_necksh_base.js'

class H(Handler):
    old=False
    def translate_path(self, path):
        from urllib.parse import unquote, urlparse
        route=unquote(urlparse(path).path)
        if H.old and route=='/static/mikapo_mixamo_solver.js':
            return str(OLD)
        if route.startswith('/poses/'):
            return str(OUT/route[len('/poses/'):])
        return super().translate_path(route)

SETUP = """
() => {
  const THREE = window.__BAKE_THREE__;
  const av = window.__BAKE_AVATAR__;
  const cam = window.__BAKE_CAMERA__;
  av.updateWorldMatrix(true,true);
  if (!window.__SKEL__) {
    const sk = new THREE.SkeletonHelper(av);
    sk.material.depthTest=false; sk.material.depthWrite=false; sk.material.transparent=true; sk.material.opacity=0.9;
    if (sk.material.color) sk.material.color.setHex(0x7dd3fc);
    let root=av; while(root.parent) root=root.parent;
    root.add(sk); window.__SKEL__=sk;
    const geo=new THREE.SphereGeometry(0.016,12,12);
    const colors={neck:0xff40c8,head:0xc084fc,leftShoulder:0xffdd44,rightShoulder:0xffdd44,leftArm:0xff8c42,rightArm:0xff8c42};
    window.__MARKS__=[];
    for (const [k,r] of rig_bones()) {
      const c=colors[k]; if(!c) continue;
      const m=new THREE.Mesh(geo,new THREE.MeshBasicMaterial({color:c,depthTest:false,transparent:true,opacity:0.95}));
      m.renderOrder=20; root.add(m); window.__MARKS__.push({bone:r.bone,mesh:m});
    }
    function* rig_bones(){ yield* window.__BAKE_RIG__.bones; }
  }
  for (const m of window.__MARKS__) m.mesh.position.copy(m.bone.getWorldPosition(new THREE.Vector3()));
  // FRONT view (symmetry check)
  if (cam) { cam.position.set(0.0, 1.25, 2.4); cam.up.set(0,1,0); cam.lookAt(0, 0.95, 0); cam.updateProjectionMatrix(); }
  if (window.__bakeRender) window.__bakeRender();
  return true;
}
"""
# fix: generator ref before def — restructure
SETUP = SETUP.replace("for (const [k,r] of rig_bones()) {\n      const c=colors[k]; if(!c) continue;",
                      "for (const [k,r] of window.__BAKE_RIG__.bones) {\n      const c=colors[k]; if(!c) continue;")
SETUP = SETUP.replace("    function* rig_bones(){ yield* window.__BAKE_RIG__.bones; }\n", "")

srv=ThreadingHTTPServer(('127.0.0.1',0),H)
threading.Thread(target=srv.serve_forever,daemon=True).start()
url=f'http://127.0.0.1:{srv.server_port}'
with sync_playwright() as pw:
    b=pw.chromium.launch(headless=True)
    for variant in ['before','after']:
        H.old = (variant=='before')
        for tag in ['upright','mid']:
            p=b.new_page(viewport={'width':720,'height':960})
            p.goto(f"{url}/bake_seq?pose=/poses/pose_{tag}.json&avatar=boxeador&fps=1&ui=0&v={variant}", wait_until='domcontentloaded', timeout=180000)
            p.wait_for_function('() => window.__BAKE_READY__ || window.__BAKE_ERROR__', timeout=240000)
            err=p.evaluate('() => window.__BAKE_ERROR__')
            if err: print('ERR',variant,tag,err); p.close(); continue
            try: p.evaluate('() => window.__bakeSeqStep && window.__bakeSeqStep()')
            except Exception: pass
            p.evaluate(SETUP)
            p.screenshot(path=str(OUT/f'neck_{variant}_{tag}_front.png'))
            print('ok', variant, tag)
            p.close()
    b.close()
srv.shutdown()

from PIL import Image, ImageDraw
tiles=[]
for tag,label in [('upright','em pe'),('mid','meio')]:
    for v in ['before','after']:
        f=OUT/f'neck_{v}_{tag}_front.png'
        im=Image.open(f).convert('RGB')
        im=im.crop((120,80,600,720))  # crop to torso/head
        im.thumbnail((320,420))
        tiles.append((f'{label} {v}',im))
W=sum(t.width for _,t in tiles); Hh=max(t.height for _,t in tiles)+26
sheet=Image.new('RGB',(W,Hh),(18,18,22))
d=ImageDraw.Draw(sheet)
x=0
for label,t in tiles:
    sheet.paste(t,(x,26)); d.text((x+6,6), label, fill=(255,255,120)); x+=t.width
sheet.save(OUT/'neck_ab_contact.jpg', quality=92)
print('saved', OUT/'neck_ab_contact.jpg', sheet.size)

