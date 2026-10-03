import json, sys, threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from playwright.sync_api import sync_playwright
import sys
sys.path[:0]=['scripts']
from check_palm_fidelity import Handler

LAB=Path('.').resolve()
DATA=LAB/'experiments/nlf_fit_webcam1/render'   # verts.bin joints.bin faces.bin meta.json

class H(Handler):
    def translate_path(self, path):
        from urllib.parse import unquote, urlparse
        route=unquote(urlparse(path).path)
        if route.startswith('/fitdata/'):
            return str(DATA/route[len('/fitdata/'):])
        return super().translate_path(route)

srv=ThreadingHTTPServer(('127.0.0.1',0),H)
threading.Thread(target=srv.serve_forever,daemon=True).start()
url=f'http://127.0.0.1:{srv.server_port}'
OUT=LAB/'experiments/bone_crook'

STEP="""
(n) => {
  // advance to frame n
  while (window.__BAKE_SEQ_FRAME__ < n) { if (window.__bakeSeqStep() == null) break; }
  const THREE = window.__BAKE_THREE__;
  // side view like the user's screenshot
  window.__bakeLookAt([2.6, 0.9, 0.1], [0, 0.15, 0]);
  // add joint chain overlay on top of the mesh if not yet
  if (window.__BAKE_MESH__ && !window.__CHAIN__) {
    // joints buffer lives inside; grab via global if exposed — else skip
  }
  window.__bakeRender();
  return window.__BAKE_SEQ_FRAME__;
}
"""

with sync_playwright() as pw:
    b=pw.chromium.launch(headless=True)
    for mode in ['mesh','skeleton']:
        p=b.new_page(viewport={'width':720,'height':960})
        p.goto(f'{url}/smpl_fit_seq?data=/fitdata&mode={mode}&side=1', wait_until='domcontentloaded', timeout=120000)
        p.wait_for_function('() => window.__BAKE_READY__ || window.__BAKE_ERROR__', timeout=240000)
        err=p.evaluate('() => window.__BAKE_ERROR__')
        if err: print('ERR', mode, err); p.close(); continue
        for n in [37, 65, 1052]:
            got=p.evaluate(STEP, n)
            p.screenshot(path=str(OUT/f'fit_{mode}_f{n:04d}.png'))
            print(mode, 'frame', got, 'ok')
        p.close()
    b.close()
srv.shutdown()
