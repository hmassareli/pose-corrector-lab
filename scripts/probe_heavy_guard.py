import ast,json
from pathlib import Path
from playwright.sync_api import sync_playwright
src=ast.parse(Path('tests/test_boxing_combat_e2e.py').read_text())
constants={n.targets[0].id:ast.literal_eval(n.value) for n in src.body if isinstance(n,ast.Assign) and isinstance(n.value,ast.Constant) and n.targets[0].id in ('SETUP','PUNCH')}
with sync_playwright() as p:
 b=p.chromium.launch(args=['--use-angle=d3d11','--ignore-gpu-blocklist']);page=b.new_page();page.goto('http://127.0.0.1:8780/static/boxing.html');page.wait_for_function('window.cornerDebug?.state().loaded',timeout=90000);page.evaluate(constants['SETUP']);page.wait_for_timeout(1500)
 rows=[]
 for x,y,z in [(x,y,.6) for x in [-.6,-.3,0,.3,.6] for y in [1.1,1.2,1.3]]:
  page.evaluate("()=>{const f=cornerDebug.fighters;f[0].x=f[1].x=0;f[0].z=-.43;f[1].z=.43;for(const a of f){a.hp=100;a.push={x:0,z:0};a.attacks=[];a.dizzy=0;a.stun=0;a.combo=0;}}")
  r=page.evaluate(constants['PUNCH'],[[x,y,z],[.6,1.48,.3],800,1,None]);rows.append({'pose':[x,y,z],**r});print(rows[-1],flush=True)
 print(json.dumps(page.evaluate('cornerDebug.presentation().hitboxes'),indent=2));Path('experiments/heavy_hands_gauntlet/guard-grid.json').write_text(json.dumps(rows,indent=2));b.close()


