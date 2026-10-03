import json, sys, threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from playwright.sync_api import sync_playwright
sys.path[:0]=['scripts']
from compare_palm_frames import Handler, step_to

LAB=Path('.').resolve()
OUT=LAB/'experiments/bone_crook'

srv=ThreadingHTTPServer(('127.0.0.1',0),Handler)
threading.Thread(target=srv.serve_forever,daemon=True).start()
url=f'http://127.0.0.1:{srv.server_port}'

with sync_playwright() as pw:
    b=pw.chromium.launch(headless=True)
    for mode in ['mesh','skeleton']:
        p=b.new_page(viewport={'width':720,'height':960})
        msgs=[]
        p.on('console', lambda m: msgs.append(f'{m.type}:{m.text}'))
        p.on('pageerror', lambda e: msgs.append(f'ERR:{e}'))
        p.goto(f'{url}/seq?data=/data&mode={mode}&side=1', wait_until='domcontentloaded', timeout=120000)
        try:
            p.wait_for_function('() => window.__BAKE_READY__ || window.__BAKE_ERROR__', timeout=240000)
        except Exception:
            print(mode, 'TIMEOUT', msgs[:8]); p.close(); continue
        err=p.evaluate('() => window.__BAKE_ERROR__')
        if err: print('ERR', mode, err, msgs[:5]); p.close(); continue
        for n in [37, 65, 1052]:
            step_to(p, n)
            # side view framing on torso
            p.evaluate("() => window.__bakeLookAt([2.6, 0.9, 0.1], [0, 0.15, 0])")
            p.evaluate("(t) => window.__bakeSetLabel(t)", f'{mode} f{n}')
            p.locator('#stage').screenshot(path=str(OUT/f'fit_{mode}_f{n:04d}.png'))
            print(mode, 'frame', n, 'ok')
        p.close()
    b.close()
srv.shutdown()
print('done')
