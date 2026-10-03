import json, sys, threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from playwright.sync_api import sync_playwright
sys.path[:0]=['scripts']
from check_palm_fidelity import Handler

LAB=Path('.').resolve()
OUT=LAB/'experiments/bone_crook'

class H(Handler):
    def translate_path(self, path):
        from urllib.parse import unquote, urlparse
        route=unquote(urlparse(path).path)
        if route.startswith('/poses/'):
            return str(OUT/route[len('/poses/'):])
        return super().translate_path(route)

SETUP = """
() => {
  const THREE = window.__BAKE_THREE__;
  const av = window.__BAKE_AVATAR__;
  const rig = window.__BAKE_RIG__;
  const cam = window.__BAKE_CAMERA__;
  av.updateWorldMatrix(true,true);
  if (!window.__SKEL__) {
    const sk = new THREE.SkeletonHelper(av);
    sk.material.depthTest=false; sk.material.depthWrite=false; sk.material.transparent=true; sk.material.opacity=1;
    if (sk.material.color) sk.material.color.setHex(0x7dd3fc);
    let root=av; while(root.parent) root=root.parent;
    root.add(sk); window.__SKEL__=sk;
    const g=new THREE.Group(); root.add(g);
    const geo=new THREE.SphereGeometry(0.018,12,12);
    const colors={hips:0x3ddea5,spine:0x6ea8fe,spine1:0x6ea8fe,spine2:0x6ea8fe,neck:0xc084fc,head:0xc084fc,
      leftShoulder:0xffdd44,rightShoulder:0xffdd44,leftArm:0xff8c42,rightArm:0xff8c42,
      leftUpLeg:0xffffff,rightUpLeg:0xffffff,leftLeg:0xaaaaaa,rightLeg:0xaaaaaa,
      leftFoot:0xff6b9d,rightFoot:0xff6b9d,leftHand:0x3de0ff,rightHand:0x3de0ff,
      leftForeArm:0x88ff88,rightForeArm:0x88ff88};
    window.__MARKS__=[];
    for (const [k,r] of rig.bones) {
      const mat=new THREE.MeshBasicMaterial({color:colors[k]??0xe2e8f0, depthTest:false, transparent:true, opacity:0.95});
      const m=new THREE.Mesh(geo, mat); m.renderOrder=20; g.add(m);
      window.__MARKS__.push({bone:r.bone, mesh:m});
    }
    av.traverse(n=>{ if(n.isMesh&&n.material){ const mats=Array.isArray(n.material)?n.material:[n.material]; for(const mat of mats){ mat.transparent=true; mat.opacity=0.28; mat.depthWrite=false; mat.needsUpdate=true; } }});
  }
  for (const m of window.__MARKS__) m.mesh.position.copy(m.bone.getWorldPosition(new THREE.Vector3()));
  if (cam) { cam.position.set(1.9, 1.05, 0.15); cam.up.set(0,1,0); cam.lookAt(0,0.85,0); cam.updateProjectionMatrix(); }
  if (window.__bakeRender) window.__bakeRender();
  return true;
}
"""

srv=ThreadingHTTPServer(('127.0.0.1',0),H)
threading.Thread(target=srv.serve_forever,daemon=True).start()
url=f'http://127.0.0.1:{srv.server_port}'
with sync_playwright() as pw:
    b=pw.chromium.launch(headless=True)
    for av, tag in [('fighter-web','upright'), ('fighter-web','sit')]:
        page=b.new_page(viewport={'width':720,'height':960})
        page.goto(f"{url}/bake_seq?pose=/poses/pose_{tag}.json&avatar={av}&side=1&fps=1&ui=0", wait_until='domcontentloaded', timeout=180000)
        page.wait_for_function('() => window.__BAKE_READY__ || window.__BAKE_ERROR__', timeout=240000)
        err=page.evaluate('() => window.__BAKE_ERROR__')
        if err: print('ERR',av,tag,err); page.close(); continue
        try: page.evaluate('() => window.__bakeSeqStep && window.__bakeSeqStep()')
        except Exception: pass
        page.evaluate(SETUP)
        page.screenshot(path=str(OUT/f'after_{av}_{tag}.png'))
        print('ok', av, tag)
        page.close()
    b.close()
srv.shutdown()

# contact sheet: before/after for sit + upright
from PIL import Image, ImageDraw
pairs=[('sit','sentado'),('upright','em pe'),('lean','inclinado')]
tiles=[]
for tag,label in pairs:
    for v in ['before','after']:
        f=OUT/f'ab_{v}_{tag}.png'
        im=Image.open(f).convert('RGB'); im.thumbnail((300,400))
        tiles.append((f'{label} {v}',im))
W=sum(t.width for _,t in tiles); Hh=max(t.height for _,t in tiles)+26
sheet=Image.new('RGB',(W,Hh),(18,18,22))
d=ImageDraw.Draw(sheet)
x=0
for label,t in tiles:
    sheet.paste(t,(x,26)); d.text((x+6,6), label, fill=(255,255,120)); x+=t.width
sheet.save(OUT/'ab_contact.jpg', quality=92)
print('saved', OUT/'ab_contact.jpg', sheet.size)
