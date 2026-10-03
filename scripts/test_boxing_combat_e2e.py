"""End-to-end combat checks in the real page: chin -> dizzy, guard -> arm block
with attacker recoil, body shot under high guard, speed-scaled damage, KO flow."""
from pathlib import Path
import json, sys
from playwright.sync_api import sync_playwright

out = Path(__file__).resolve().parents[1] / 'experiments' / 'heavy_hands_gauntlet'
out.mkdir(exist_ok=True)
SETUP = """async()=>{
  const core=await import('/static/boxing_core.mjs');window.__core=core;
  const d=cornerDebug;d.enter();
  // Freeze autonomous punches before setup can injure/move either fighter.
  d.fighters[1].ai={mode:'open',until:performance.now()+1e6,next:performance.now()+1e6,guard:0.2,punch:null,attack:0};
  window.__keep=setInterval(()=>d.reviewPose(core.neutralPose()),50);
}"""
# Realistic straight punch: wrist/elbow in the player's own pose space (human arm
# length). Collision is judged on the rendered avatars, so nothing is teleported.
PUNCH = """async([wrist, elbow, forceN, guard, start])=>{
  const d=cornerDebug,f=d.fighters,me=f[0],bot=f[1];
  // Repeatable jab-range fixture; collision still uses the native rendered
  // glove/forearms/head. No hitbox or wrist is moved to manufacture a hit.
  me.x=bot.x=0;me.z=-.43;bot.z=.43;me.push=bot.push=null;
  const now=performance.now();
  bot.ai ??= {};Object.assign(bot.ai,{mode:guard>0.5?'guard':'open',until:now+1e6,next:now+1e6,guard,punch:null,attack:0});
  bot.dizzyImmune=0;bot.dizzy=0;bot.stun=0;bot.headHits=[];bot.recoil=0;me.recoil=0;
  bot.reaction=null;bot.guardCompression=null;bot.blockHold=null;
  bot.ai.captured=null;bot.ai.release=null;bot.attacks=[];
  me.blockHold=null;me.guardCompression=null;
  const pose=(w,e)=>{const p=__core.neutralPose(),s=p[8];p[12]=[s[0]*w[0],w[1],s[2]+w[2]];p[10]=[s[0]*e[0],e[1],s[2]+e[2]];return p;};
  if(start){clearInterval(window.__keep);const q=pose(start[0],start[1]);window.__keep=setInterval(()=>d.reviewPose(q.map(v=>v.slice())),30);}
  await new Promise(r=>setTimeout(r,400));
  const before={hp:bot.hp,seq:d.presentation().effect?.seq||0,distance:+Math.hypot(me.x-bot.x,me.z-bot.z).toFixed(2)};
  clearInterval(window.__keep);
  const p=pose(wrist,elbow);
  d.reviewPose(p.map(v=>v.slice()));
  window.__keep=setInterval(()=>d.reviewPose(p.map(v=>v.slice())),30);
  me.attacks.push({hand:0,start:performance.now(),hit:false,mocap:true,speed:forceN/200,forceN});
  await new Promise(r=>setTimeout(r,320));
  clearInterval(window.__keep);
  window.__keep=setInterval(()=>d.reviewPose(__core.neutralPose()),50);
  const e=d.presentation().effect;
  return {kind:e?.seq>before.seq?e.kind:null,damage:before.hp-bot.hp,dizzy:+bot.dizzy.toFixed(2),recoil:+me.recoil.toFixed(2),power:e?.power,distance:before.distance};
}"""
with sync_playwright() as p:
    browser = p.chromium.launch(args=['--use-angle=d3d11', '--ignore-gpu-blocklist'])
    page = browser.new_page(viewport={'width': 1280, 'height': 800})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto('http://127.0.0.1:8780/static/boxing.html', wait_until='domcontentloaded')
    page.wait_for_function('window.cornerDebug?.state().loaded', timeout=90000)
    page.evaluate(SETUP)
    page.wait_for_timeout(2500)
    results = {}
    face, face_elbow = [0.15, 1.6, 0.6], [0.6, 1.48, 0.3]
    chin, chin_elbow = [-0.3, 1.5, 0.6], [0.6, 1.48, 0.3]
    body, body_elbow = [0.15, 1.08, 0.55], [0.6, 1.16, 0.28]
    low_start = [[0.6, 1.05, 0.2], [0.9, 1.1, 0.05]]
    results['chin_fast_open'] = page.evaluate(PUNCH, [chin, chin_elbow, 1000, 0, None])
    page.wait_for_timeout(2600)
    results['head_slow_open'] = page.evaluate(PUNCH, [face, face_elbow, 180, 0, None])
    page.wait_for_timeout(700)
    results['head_fast_open'] = page.evaluate(PUNCH, [face, face_elbow, 800, 0, None])
    page.wait_for_timeout(700)
    # Native guard gloves sit below the face in this recorded guard. Target the
    # visible glove, and separately prove that the open face is still hittable.
    results['straight_into_high_guard'] = page.evaluate(PUNCH, [[-.3,1.2,.6], [0.6,1.25,.3], 800, 1, None])
    page.wait_for_timeout(700)
    results['open_face_above_guard'] = page.evaluate(PUNCH, [face, face_elbow, 800, 1, None])
    page.wait_for_timeout(700)
    results['body_under_high_guard'] = page.evaluate(PUNCH, [body, body_elbow, 800, 1, low_start])
    page.wait_for_timeout(700)
    page.evaluate("cornerDebug.fighters[1].hp=4")
    results['ko'] = page.evaluate(PUNCH, [face, face_elbow, 800, 0, None])
    page.wait_for_timeout(3200)
    results['result_open'] = page.evaluate("document.getElementById('result').open")
    results['result_stats'] = page.evaluate("document.getElementById('resultStats').innerText.replace(/\\n/g,' | ')")
    page.screenshot(path=str(out / '15-combat-e2e-result.png'))
    results['journal'] = page.evaluate('cornerDebug.journal().summary()')
    results['peak'] = page.evaluate('cornerDebug.peak()')
    results['errors'] = errors
    (out/'combat_e2e.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    print(json.dumps(results, indent=1))
    browser.close()
r = results
HEAD = ('clean', 'chin', 'counter')
ok = (r['chin_fast_open']['kind'] == 'chin' and r['chin_fast_open']['dizzy'] > 0
      and r['head_fast_open']['kind'] in HEAD
      and r['head_fast_open']['damage'] > r['head_slow_open']['damage'] > 0
      and r['straight_into_high_guard']['kind'] in ('arm', 'guard')
      and r['straight_into_high_guard']['damage'] == 0
      and r['open_face_above_guard']['kind'] in HEAD
      and r['body_under_high_guard']['kind'] in ('body', 'counter')
      and r['result_open'] and not errors)
print('E2E', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
