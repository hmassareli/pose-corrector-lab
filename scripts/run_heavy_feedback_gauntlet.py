"""Follow-up impact/narrator checks against the final source snapshot."""
import hashlib,json,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'experiments/heavy_hands_gauntlet'
sources=['viewer/'+name for name in ['boxing.js','boxing_core.mjs','boxing_audio.js','boxing.html','boxing_ui.css','boxing_voice_caption.js','boxing_caption_bounds.js']]
hashes=lambda:{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in sources}
commands=[['node','tests/test_boxing_core.mjs'],[sys.executable,'tests/test_heavy_impact_feedback.py'],[sys.executable,'tests/test_heavy_voice_caption.py'],[sys.executable,'tests/test_heavy_audio.py'],[sys.executable,'tests/test_boxing_combat_e2e.py'],[sys.executable,'tests/test_boxing_browser.py'],[sys.executable,'tests/test_boxing_browser.py','p2p'],[sys.executable,'tests/test_heavy_hands_geometry_review.py'],[sys.executable,'tests/test_heavy_ui_review.py']]
before=hashes();rows=[]
for command in commands:
 name=Path(command[1]).stem+('-'+command[2] if len(command)>2 else '');print('Running',name,flush=True);start=time.perf_counter()
 with (OUT/('feedback-'+name+'.log')).open('w',encoding='utf8') as log:result=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
 rows.append({'command':command,'exitCode':result.returncode,'seconds':round(time.perf_counter()-start,2),'log':'feedback-'+name+'.log'});print('PASS' if not result.returncode else 'FAIL',name,flush=True)
after=hashes();ok=before==after and all(row['exitCode']==0 for row in rows)
(OUT/'feedback-suite-result.json').write_text(json.dumps({'result':'PASS' if ok else 'FAIL','sourcesStable':before==after,'sha256':after,'checks':rows},indent=2),encoding='utf8')
sys.exit(0 if ok else 1)
