import ast,json
from pathlib import Path
from playwright.sync_api import sync_playwright
s=ast.parse(Path('scripts/test_boxing_combat_e2e.py').read_text()); c={n.targets[0].id:ast.literal_eval(n.value) for n in s.body if isinstance(n,ast.Assign) and isinstance(n.value,ast.Constant) and n.targets[0].id in ('SETUP','PUNCH')}
with sync_playwright() as p:
 b=p.chromium.launch(args=['--use-angle=d3d11','--ignore-gpu-blocklist']); pg=b.new_page();pg.goto('http://127.0.0.1:8780/static/boxing.html');pg.wait_for_function('window.cornerDebug?.state().loaded',timeout=90000);pg.evaluate(c['SETUP']);pg.wait_for_timeout(1500);rows=[]
 for x in [-.3,0,.15,.3]:
  for y in [1.4,1.45,1.5,1.55]:
   pg.evaluate('()=>{for(const f of cornerDebug.fighters){f.hp=100;f.dizzy=0;f.stun=0;f.push=null;f.reaction=null;}const f=cornerDebug.fighters;f[0].x=f[1].x=0;f[0].z=-.43;f[1].z=.43;}')
   r=pg.evaluate(c['PUNCH'],[[x,y,.6],[.6,1.48,.3],1000,0,None]);rows.append({'wrist':[x,y,.6],**r});print(rows[-1],flush=True)
 Path('experiments/heavy_hands_gauntlet/chin-grid-final.json').write_text(json.dumps(rows,indent=2));b.close()

