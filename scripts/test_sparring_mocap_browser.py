"""Exercise real bot playback and blocking in the existing local game page."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parents[1] / 'experiments/sparring_capture_20261002'
with sync_playwright() as p:
    browser = p.chromium.launch(args=['--use-angle=d3d11', '--ignore-gpu-blocklist'])
    page = browser.new_page(viewport={'width': 1280, 'height': 800})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto('http://127.0.0.1:8780/static/boxing.html', wait_until='domcontentloaded')
    page.wait_for_function('window.cornerDebug?.state().loaded && window.cornerDebug.sparringMotion().loaded', timeout=90000)
    page.evaluate("""async()=>{
      window.lib=await (await fetch('/static/sparring_mocap.json')).json();
      window.core=await import('/static/boxing_core.mjs');
      cornerDebug.enter();
      window.keep=setInterval(()=>cornerDebug.reviewPose(core.neutralPose()),40);
      window.samples=[];
      window.observe=()=>{
        const b=cornerDebug.fighters[1];
        samples.push({id:b.ai?.punch?.clip?.id, launched:b.ai?.punch?.launched,
          wrist:b.pose[12+(b.ai?.punch?.hand||0)], attack:b.attacks.some(a=>a.mocap)});
        requestAnimationFrame(observe);
      };
      requestAnimationFrame(observe);
    }""")
    page.wait_for_timeout(200)
    results = []
    for i in range(4):
        clip = page.evaluate("""i=>{
          const d=cornerDebug,b=d.fighters[1],now=d.presentation().vclock,c=lib.clips[i];
          b.hp=100;b.dizzy=0;b.stun=0;b.recoil=0;b.attacks=[];
          b.x=0;b.z=1.5;d.fighters[0].z=-1.5;
          b.ai={mode:'guard',until:now+1e6,next:now+1e6,guard:1,attack:0,lastHand:c.hand,
            punch:{clip:c,hand:c.hand,start:now,launched:false,blockedAt:0,speed:c.speed}};
          return {id:c.id,duration:c.duration,launch:c.launch};
        }""", i)
        page.wait_for_function('cornerDebug.fighters[1].ai.punch?.launched === true', timeout=5000)
        page.wait_for_timeout(150)
        page.screenshot(path=str(OUT / (clip['id'] + '_game.png')))
        page.wait_for_function('cornerDebug.fighters[1].ai.punch === null', timeout=5000)
        results.append(clip)
    samples = page.evaluate('samples')
    for c in results:
        observed = [s for s in samples if s.get('id') == c['id']]
        assert len(observed) >= 2, c
        assert any(s.get('launched') and s.get('attack') for s in observed), c
        assert len({tuple(s['wrist']) for s in observed}) >= 2, c
    # Block a launched recording; the timeline must return to guard and finish.
    page.evaluate("""()=>{
      const b=cornerDebug.fighters[1],now=cornerDebug.presentation().vclock,c=lib.clips[0];
      b.ai.punch={clip:c,hand:c.hand,start:now-400,launched:true,blockedAt:now,blockedValue:1};
    }""")
    page.wait_for_function('cornerDebug.fighters[1].ai.punch === null', timeout=3000)
    assert not errors, errors
    report = {'result':'PASS','clips':results,'samples':len(samples),'errors':errors,
              'checks':['library loaded by actual page','all four recorded attacks animate and launch',
                        'all four return to idle','blocked recording retracts','no browser errors'],
              'limitation':'Automated local playback; subjective naturalness needs human review.'}
    (OUT / 'browser_report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
    browser.close()
