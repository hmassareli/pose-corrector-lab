"""Tracking-stability diagnosis with the recorded webcam (real webcam->NLF->bridge->game path).

Usage: python scripts/diag_boxing_tracking.py <page-path> <toon on|off> [seconds]
Reports pose rate/gaps, how often the HUD flips between tracking/paused, render fps,
and whether the player's feet float above the canvas.
"""
import json, statistics, sys
from pathlib import Path
from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parents[1]
replay = root / 'experiments' / 'boxing_review' / 'webcam-replay.y4m'
page_path = sys.argv[1] if len(sys.argv) > 1 else '/static/boxing.html'
toon = sys.argv[2] if len(sys.argv) > 2 else 'on'
seconds = int(sys.argv[3]) if len(sys.argv) > 3 else 20
outline = sys.argv[4] if len(sys.argv) > 4 else 'off'
PROBE = """(ms)=>new Promise(resolve=>{
  const d=cornerDebug,status=document.getElementById('trackingStatus');
  const poses=[],flips=[],feet=[];let frames=0,lastActive=document.body.classList.contains('pose-active'),lastText=status.textContent,texts=0;
  addEventListener('message',e=>{if(e.data?.type==='corner-pose')poses.push(performance.now());});
  const t0=performance.now();
  function tick(){frames++;
    const a=document.body.classList.contains('pose-active');if(a!==lastActive){flips.push(Math.round(performance.now()-t0));lastActive=a;}
    if(status.textContent!==lastText){texts++;lastText=status.textContent;}
    if(frames%10===0){const act=d.actors[d.state().self];if(act){const y=n=>act.rig.bones.get(n)?.bone.getWorldPosition(act.root.position.clone().set(0,0,0)).y;
      let sole=Infinity;for(const list of act.nativeSoleVertices?.values()||[])for(const {mesh,index} of list.filter((_,k)=>k%8===0)){mesh.skeleton.update();const p=act.root.position.clone().fromBufferAttribute(mesh.geometry.attributes.position,index);mesh.applyBoneTransform(index,p);mesh.localToWorld(p);sole=Math.min(sole,p.y);}
      const fi=d.fighters[d.state().self],wp=n=>act.group.worldToLocal(act.rig.bones.get(n).bone.getWorldPosition(act.root.position.clone().set(0,0,0)));
      const hp=wp('hips'),L=wp('leftFoot').sub(hp),R=wp('rightFoot').sub(hp),P=fi.pose;
      const legs={src:[5,6].flatMap(j=>[P[j][0]-P[0][0],P[j][1]-P[0][1],P[j][2]-P[0][2]]),avatar:[L.x,L.y,L.z,R.x,R.y,R.z]};
      feet.push({l:y('leftFoot'),r:y('rightFoot'),hips:y('hips'),sole:Number.isFinite(sole)?sole:null,legs,contacts:d.fighters[d.state().self].footContacts,visible:d.fighters[d.state().self].footVisible});}}
    if(performance.now()-t0<ms)requestAnimationFrame(tick);else resolve({poses,flips,feet,frames,texts,ms});}
  requestAnimationFrame(tick);})"""
with sync_playwright() as p:
    b = p.chromium.launch(args=['--use-angle=d3d11', '--ignore-gpu-blocklist', '--use-fake-ui-for-media-stream',
                                '--use-fake-device-for-media-stream', '--use-file-for-fake-video-capture=' + str(replay)])
    ctx = b.new_context(viewport={'width': 1440, 'height': 900}, permissions=['camera'])
    ctx.add_init_script("localStorage.setItem('cornerToon','%s');localStorage.setItem('cornerOutline','%s');localStorage.setItem('poseLab.handRetarget.v1', JSON.stringify({selfieMirror:true}));" % (toon, outline))
    pg = ctx.new_page()
    errors = []
    pg.on('pageerror', lambda e: errors.append(str(e)))
    pg.goto('http://127.0.0.1:8780' + page_path, wait_until='domcontentloaded')
    pg.wait_for_function('window.cornerDebug?.state().loaded', timeout=90000)
    pg.locator('#train').click()
    pg.wait_for_function("document.getElementById('trackingStatus').textContent.includes('rastreamento ativo')", timeout=180000)
    if 'legacy-steps' in sys.argv:
        pg.evaluate("cornerDebug.fighters[cornerDebug.state().self].proceduralFeet=true")
    r = pg.evaluate(PROBE, seconds * 1000)
    gaps = [r['poses'][i] - r['poses'][i - 1] for i in range(1, len(r['poses']))]
    feet = r['feet']
    low = [min(f['l'], f['r']) for f in feet if f['l'] is not None]
    report = {
        'page': page_path, 'toon': toon, 'outline': outline, 'seconds': seconds,
        'poseFps': round(len(r['poses']) / seconds, 2),
        'medianGapMs': round(statistics.median(gaps), 1) if gaps else None,
        'maxGapMs': round(max(gaps), 1) if gaps else None,
        'gapsOver500ms': sum(g > 500 for g in gaps),
        'hudFlips': len(r['flips']), 'statusTextChanges': r['texts'],
        'renderFps': round(r['frames'] / seconds, 1),
        'lowestFootY': {'median': round(statistics.median(low), 3), 'max': round(max(low), 3)} if low else None,
        'hipsY': round(statistics.median([f['hips'] for f in feet if f['hips'] is not None]), 3) if feet else None,
        'soleAboveCanvas': (lambda s: {'median': round(statistics.median(s) - .026, 3), 'max': round(max(s) - .026, 3)} if s else None)([f['sole'] for f in feet if f.get('sole') is not None]),
        'footVisibleSample': feet[-1]['visible'] if feet else None,
        # |Pearson r| between NLF foot offsets (from pelvis) and the avatar's, per axis; 1 = legs follow the player.
        'legFollow': (lambda pairs: {ax: round(statistics.mean(abs(statistics.correlation([s[i] for s, _ in pairs], [a[i] for _, a in pairs]))
            for i in (k, k + 3)), 2) for k, ax in enumerate('xyz')} if len(pairs) > 5 else None)(
            [(f['legs']['src'], f['legs']['avatar']) for f in feet if f.get('legs')]),
        'errors': errors,
    }
    print(json.dumps(report), flush=True)
    b.close()
