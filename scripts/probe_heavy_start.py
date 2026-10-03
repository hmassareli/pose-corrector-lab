from playwright.sync_api import sync_playwright
import json
from pathlib import Path
out=Path('experiments/heavy_hands_gauntlet');out.mkdir(exist_ok=True)
with sync_playwright() as p:
 b=p.chromium.launch(args=['--use-angle=d3d11','--ignore-gpu-blocklist'])
 page=b.new_page(viewport={'width':1440,'height':900});errors=[]
 page.on('pageerror',lambda e: errors.append(str(e)))
 page.goto('http://127.0.0.1:8780/static/boxing.html',wait_until='domcontentloaded')
 try:page.wait_for_function('window.cornerDebug?.state().loaded',timeout=60000)
 except Exception:print('LOAD FAILED',page.locator('#loadStatus').inner_text())
 print(json.dumps({'errors':errors,'title':page.title(),'state':page.evaluate('window.cornerDebug?.state()')},indent=2))
 page.wait_for_timeout(1200)
 page.screenshot(path=str(out/'01-lobby.png'))
 if not errors:
  page.locator('#settingsButton').click();page.screenshot(path=str(out/'02-settings.png'))
 b.close()
