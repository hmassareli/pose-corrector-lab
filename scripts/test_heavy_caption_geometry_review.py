"""Independent review of rendered caption transform envelope, no NLF process."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
rows = []
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for width, height in [(1280, 800), (390, 844), (844, 390)]:
        page = browser.new_page(viewport={'width': width, 'height': height})
        page.goto('http://127.0.0.1:8780/static/boxing.html', wait_until='domcontentloaded')
        page.set_content('<link rel="stylesheet" href="/static/boxing_ui.css"><div id="voiceCaption" class="voice-caption"><strong></strong></div>')
        page.wait_for_timeout(300)
        for text in ['GUARD UP', 'PERFECT COUNTER', 'KEEP IT GOING', 'NOT EVEN CLOSE']:
            row = page.evaluate('''async text=>{
              const {VoiceCaption}=await import('/static/boxing_voice_caption.js');
              const el=document.getElementById('voiceCaption');
              const caption=new VoiceCaption(el,()=>[],()=>true);
              caption.show({clip:'review',text,duration:1.7,priority:80});
              const samples=[];
              for(const time of [0,100,240,440,1000]) {
                const animation=el.getAnimations()[0]; if(animation){animation.pause();animation.currentTime=time;}
                const r=el.getBoundingClientRect();
                samples.push({time,hidden:el.hidden,box:{x:r.x,y:r.y,width:r.width,height:r.height},
                  nominal:{x:parseFloat(el.style.left),y:parseFloat(el.style.top),width:el.offsetWidth,height:el.offsetHeight},
                  scrollWidth:el.scrollWidth,clientWidth:el.clientWidth,opacity:getComputedStyle(el).opacity});
              }
              caption.clear();return {text,samples};
            }''', text)
            rows.append({'viewport': [width, height], **row})
        page.close()
    browser.close()
(ROOT / 'experiments/heavy_hands_gauntlet/independent-caption-geometry-review.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
print(json.dumps(rows, indent=2))
