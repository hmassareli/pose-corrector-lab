import json
from pathlib import Path
from playwright.sync_api import sync_playwright
out=Path('experiments/heavy_hands_gauntlet')
with sync_playwright() as p:
 b=p.chromium.launch(args=['--use-angle=d3d11','--ignore-gpu-blocklist']);page=b.new_page(viewport={'width':1440,'height':900});page.goto('http://127.0.0.1:8780/static/boxing.html');page.wait_for_function('window.cornerDebug?.state().loaded',timeout=90000);page.wait_for_timeout(1000)
 for avatar in ['boxer-prism31','boxeador','fighter-web']:
  page.evaluate("id=>{const s=document.getElementById('avatarSelect');s.value=id;s.dispatchEvent(new Event('change'));}",avatar);page.wait_for_function('!document.getElementById("avatarSelect").disabled');page.wait_for_timeout(300);page.screenshot(path=str(out/('final-lobby-'+avatar+'.png')))
 page.locator('#settingsButton').click();page.screenshot(path=str(out/'final-settings-pt.png'));page.select_option('#language','en');page.screenshot(path=str(out/'final-settings-en.png'));b.close()
