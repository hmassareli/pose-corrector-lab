"""Replay a recorded webcam video through webcam -> NLF -> game and audit the player's guard.

Usage: python scripts/review_boxing_guard_replay.py <video.y4m> <tag> [seconds]
Writes front-view screenshots of the player's avatar and a JSON with, per sample:
NLF wrist separation vs avatar glove separation (both divided by shoulder width), wrist heights
relative to the head, and the avatar palm normal vs the NLF palm (from knuckles).
"""
import json, sys
from pathlib import Path
from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parents[1]
video = Path(sys.argv[1])
tag = sys.argv[2] if len(sys.argv) > 2 else 'guard'
seconds = int(sys.argv[3]) if len(sys.argv) > 3 else 36
page_path = sys.argv[4] if len(sys.argv) > 4 else '/static/boxing.html'
out = root / 'experiments' / 'boxing_redesign' / 'guard_video'
out.mkdir(parents=True, exist_ok=True)
SAMPLE = """()=>{const d=cornerDebug,s=d.state().self,a=d.actors[s],f=d.fighters[s];
 const V=a.root.position.constructor,loc=n=>a.group.worldToLocal(a.rig.bones.get(n).bone.getWorldPosition(new V()));
 const P=f.pose,dist=(x,y)=>Math.hypot(x[0]-y[0],x[1]-y[1],x[2]-y[2]);
 const nShoulder=dist(P[8],P[9]),nWrist=dist(P[12],P[13]);
 const aL=loc('leftHand'),aR=loc('rightHand'),aSL=loc('leftArm'),aSR=loc('rightArm'),aHead=loc('head');
 const aShoulder=aSL.distanceTo(aSR);
 // Palm normal: across(index->pinky) x forward(wrist->knuckles); NLF aux vs avatar hand bone axes.
 const aux=f.aux||{},palm={};
 for(const side of ['left','right']){const w=aux[side+'_wrist'],i=aux[side+'_index'],p=aux[side+'_pinky'];
   if(w&&i&&p){const fw=i.clone().add(p).multiplyScalar(.5).sub(w).normalize(),ac=p.clone().sub(i).normalize();palm[side]={nlfNormal:ac.clone().cross(fw).normalize().toArray().map(v=>+v.toFixed(2))};}
   const hb=a.rig.bones.get(side+'Hand').bone,q=hb.getWorldQuaternion(new a.root.quaternion.constructor()),gq=a.group.getWorldQuaternion(new a.root.quaternion.constructor()).invert();
   const axes=['x','y','z'].map((k,j)=>{const e=new V(j==0?1:0,j==1?1:0,j==2?1:0).applyQuaternion(q).applyQuaternion(gq);return e.toArray().map(v=>+v.toFixed(2));});
   palm[side]={...(palm[side]||{}),avatarAxes:axes};}
 return {t:+performance.now().toFixed(0),nlfWristSepRel:+(nWrist/nShoulder).toFixed(2),avatarGloveSepRel:+(aL.distanceTo(aR)/aShoulder).toFixed(2),
   nlfWristBelowHead:[12,13].map(j=>+(P[15][1]-P[j][1]).toFixed(3)),avatarHandBelowHead:[aL,aR].map(h=>+(aHead.y-h.y).toFixed(3)),
   nlfWristFwd:[12,13].map(j=>+(P[j][2]-P[0][2]).toFixed(3)),guarded:document.getElementById('stun0').textContent,palm};}"""
SHOT = """()=>{const d=cornerDebug,s=d.state().self,a=d.actors[s],f=d.fighters[s];
 const V=a.root.position.constructor,c=a.rig.bones.get('neck').bone.getWorldPosition(new V());
 const fw={x:Math.sin(f.yaw),z:Math.cos(f.yaw)};d.fighters[1-s];d.actors[1-s].group.visible=false;
 d.camera.clearViewOffset();d.camera.fov=34;d.camera.updateProjectionMatrix();
 d.camera.position.set(c.x+fw.x*2.1,c.y,c.z+fw.z*2.1);d.camera.lookAt(c.x,c.y-0.15,c.z);d.renderer.render(d.scene,d.camera);d.actors[1-s].group.visible=true;}"""
with sync_playwright() as p:
    b = p.chromium.launch(args=['--use-angle=d3d11', '--ignore-gpu-blocklist', '--use-fake-ui-for-media-stream',
                                '--use-fake-device-for-media-stream', '--use-file-for-fake-video-capture=' + str(video)])
    ctx = b.new_context(viewport={'width': 1000, 'height': 700}, permissions=['camera'])
    ctx.add_init_script("localStorage.setItem('cornerOutline','off');localStorage.setItem('labAvatarId','boxer-prism31');")
    pg = ctx.new_page()
    errors = []
    pg.on('pageerror', lambda e: errors.append(str(e)))
    pg.goto('http://127.0.0.1:8780' + page_path, wait_until='domcontentloaded')
    pg.wait_for_function('window.cornerDebug?.state().loaded', timeout=90000)
    pg.locator('#train').click()
    pg.wait_for_function("document.getElementById('trackingStatus').textContent.includes('rastreamento ativo')", timeout=180000)
    pg.evaluate("document.querySelectorAll('header,section,aside,footer,.vignette,#banner,#combatMessage,#fxLayer').forEach(e=>e.style.display='none');setInterval(()=>{cornerDebug.fighters[0].hp=100;cornerDebug.fighters[1].hp=100;},300)")
    samples = []
    for k in range(seconds * 2):
        pg.wait_for_timeout(500)
        samples.append(pg.evaluate(SAMPLE))
        if k % 6 == 0:
            pg.evaluate('cornerDebug.paused=true')
            pg.wait_for_timeout(120)
            pg.evaluate(SHOT)
            pg.screenshot(path=str(out / f'{tag}-{k:02d}.png'))
            pg.evaluate('cornerDebug.paused=false;requestAnimationFrame(cornerDebug.frame)')
    (out / f'{tag}.json').write_text(json.dumps({'samples': samples, 'errors': errors}, indent=1), encoding='utf-8')
    print(json.dumps({'n': len(samples), 'errors': errors}))
    b.close()
