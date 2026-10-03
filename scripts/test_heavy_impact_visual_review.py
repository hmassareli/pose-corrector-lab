"""Independent rendered impact/KO captures without result modal."""
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'experiments/heavy_hands_gauntlet'
with sync_playwright() as p:
 b=p.chromium.launch(args=['--use-angle=d3d11','--ignore-gpu-blocklist'])
 page=b.new_page(viewport={'width':1440,'height':900})
 page.goto('http://127.0.0.1:8780/static/boxing.html')
 page.wait_for_function('window.cornerDebug?.state().loaded',timeout=90000)
 page.evaluate('''async()=>{
  const core=await import('/static/boxing_core.mjs'),d=cornerDebug;
  d.paused=true;await new Promise(r=>requestAnimationFrame(r));d.enter();d.reviewPose(core.neutralPose());
  d.fighters.forEach(f=>f.tracking=false);for(let i=0;i<24;i++)d.frame(performance.now()+i*17);
  d.reviewEffect({kind:'head',forceN:1200,victim:1,dir:[0,0,1],head:true,hand:0});
 }''')
 page.wait_for_timeout(150)
 page.screenshot(path=str(OUT/'independent-impact-word.png'))
 page.evaluate('''()=>{
  const d=cornerDebug;window.reviewRealNow=performance.now.bind(performance);window.reviewClock=reviewRealNow();
  Object.defineProperty(performance,'now',{value:()=>reviewClock,configurable:true});
  d.fighters[1].reaction={kind:'finisher',power:1,dir:[0,0,1],head:true,start:d.presentation().vclock};
  d.finish({winner:0,ko:true,reason:'knockout'});d.presentation().ko.delay=100000;
  window.reviewStart=d.presentation().vclock;
 }''')
 for phase in [0,500,950,1150]:
  page.evaluate('''phase=>{const d=cornerDebug;let guard=0;
   while(d.presentation().vclock-reviewStart<phase+120&&guard++<900)d.frame(reviewClock+=1000/60);
   d.renderer.render(d.scene,d.camera);
  }''',phase)
  page.screenshot(path=str(OUT/f'independent-impact-ko-{phase}.png'))
 b.close()
print('Independent rendered impact/KO captures complete')
