"""Two actual browsers, local relay/P2P, authoritative force journal and movement."""
import json,time,sys
from pathlib import Path
from playwright.sync_api import sync_playwright
root=Path(__file__).resolve().parents[1];out=root/'experiments/heavy_hands_gauntlet'
with sync_playwright() as p:
 b=p.chromium.launch(args=['--use-angle=d3d11','--ignore-gpu-blocklist']);ctx=b.new_context(viewport={'width':1366,'height':768});errors=[];pages=[ctx.new_page(),ctx.new_page()]
 for page in pages:
  page.on('pageerror',lambda e:errors.append(str(e)));page.goto('http://127.0.0.1:8780/static/boxing.html');page.wait_for_function('window.cornerDebug?.state().loaded',timeout=90000)
 assert pages[0].locator('#train').is_enabled()
 room='GAUNTLET'+str(int(time.time()));mode=sys.argv[1] if len(sys.argv)>1 else 'relay'
 for page in pages:
  page.evaluate("args=>{document.getElementById('room').value=args.room;document.getElementById('server').value='ws://127.0.0.1:8790';document.getElementById('transport').value=args.mode;document.getElementById('join').click();}",{'room':room,'mode':mode})
 for page in pages:page.wait_for_function('cornerDebug.state().ready',timeout=20000)
 if mode=='p2p':
  for page in pages:page.wait_for_function('cornerDebug.net.dc?.readyState==="open"',timeout=20000)
 assert [pg.evaluate('cornerDebug.state().self') for pg in pages]==[0,1]
 for pg in pages:
  pg.evaluate("async()=>{window.__core=await import('/static/boxing_core.mjs');window.keep=setInterval(()=>cornerDebug.reviewPose(__core.neutralPose()),30);}")
 for step in [0]*60+[1]*20:
  for pg in pages:
   pg.evaluate("""step=>{const pose=__core.neutralPose(),cameraPose=pose.map(v=>[v[0]+.12*step,v[1]-.92,v[2]-4+.1*step]);window.dispatchEvent(new MessageEvent('message',{origin:location.origin,source:document.getElementById('tracker').contentWindow,data:{type:'corner-pose',time:performance.now(),backend:'nlf',pose,cameraPose,cameraInfo:{size:[640,360],fov:55}}}));}""",step)
  pages[0].wait_for_timeout(35)
 pages[0].wait_for_timeout(1000)
 movement=[pg.evaluate('cornerDebug.fighters.map(f=>({x:f.x,z:f.z,radialApplied:f.radialApplied,footContacts:f.footContacts}))') for pg in pages]
 assert all(f['footContacts'] is None for f in movement[0]),movement
 assert all(f['radialApplied']>.04 for f in movement[0]),{'movement':movement,'calibration':[pg.evaluate('cornerDebug.fighters[cornerDebug.state().self].footwork') for pg in pages]}
 assert max(abs(movement[0][i][axis]-movement[1][i][axis]) for i in range(2) for axis in ['x','z'])<.025,movement
 # One remote attempt sent repeatedly is recorded once; air punches cannot PEAK.
 pages[1].evaluate("()=>{const d=cornerDebug,f=d.fighters[1];window.sendAir=()=>d.net.send({type:'input',pose:__core.neutralPose(),tracking:true,aux:null,attacks:[{id:777,hand:0,forceN:1500,speed:4}]});sendAir();}")
 for _ in range(8):pages[1].evaluate('sendAir()');pages[0].wait_for_timeout(40)
 pages[0].wait_for_timeout(400)
 journals=[pg.evaluate('cornerDebug.fighters[1].journal.entries') for pg in pages]
 assert len(journals[0])==1 and len(journals[1])==1,journals
 assert journals[0][0]['forceN']==1500 and not journals[0][0]['landed'],journals
 assert not pages[1].evaluate('cornerDebug.peak().current')
 # Drop authoritative snapshots while >8 attempts accrue, then recover the
 # absolute journal slots in bounded history chunks. This is transport evidence,
 # not a detector test: the host journal entries below are explicit fixtures.
 pages[1].evaluate("()=>{window.deliver=cornerDebug.net.deliver.bind(cornerDebug.net);window.dropStates=true;cornerDebug.net.deliver=m=>{if(!dropStates)deliver(m);};}")
 pages[0].evaluate("()=>{const j=cornerDebug.fighters[1].journal;for(let i=0;i<60;i++){const n=j.attempt({hand:i%2,forceN:600,speed:2},i);j.land(n,{forceN:600,target:'head',combo:1,speed:2});}}")
 # End the fight while those snapshots are still missing. KO must continue
 # history transfer even though active simulation has already stopped.
 pages[0].evaluate("cornerDebug.finish({winner:1,reason:'knockout',ko:true})")
 pages[0].wait_for_timeout(500);pages[1].evaluate('dropStates=false')
 pages[1].wait_for_function('cornerDebug.fighters[1].journal.entries.filter(Boolean).length===61',timeout=15000)
 recovered=[pg.evaluate('cornerDebug.fighters[1].journal.summary(60)') for pg in pages]
 assert recovered[0]==recovered[1] and recovered[1]['total']==36000 and recovered[1]['attempts']==61,recovered
 assert pages[1].evaluate('cornerDebug.peak().current')==600
 pages[1].wait_for_function('document.getElementById("result").open',timeout=10000)
 final_result=pages[1].locator('#resultStats').inner_text()
 assert 'NaN' not in final_result and '36' in final_result,final_result
 # Same authoritative timer after capture stops (tracking timeout + relay transit).
 for pg in pages:pg.evaluate('clearInterval(keep);cornerDebug.fighters[cornerDebug.state().self].tracking=false')
 pages[0].wait_for_timeout(1600);states=[pg.evaluate('cornerDebug.state()') for pg in pages]
 assert abs(states[0]['clock']-states[1]['clock'])<.05,states
 pages[1].evaluate('cornerDebug.net.close()');pages[0].wait_for_function('!cornerDebug.state().ready',timeout=10000)
 assert not errors,errors
 report={'result':'PASS','transport':mode,'checks':['training starts camera','two browsers local signaling','camera translation replicated','no synthetic feet fields','host/guest movement agrees','Newton force replicated','duplicate attempt rejected','air does not set PEAK','60 missing journal entries recovered after KO during dropped snapshots','client1 authoritative totals and PEAK restored','final result has complete totals and no NaN','authoritative timer agrees','disconnect pauses'],'errors':errors,'states':states,'movement':movement,'journals':journals,'recovered':recovered,'finalResult':final_result}
 (out/('browser-'+mode+'-test.json')).write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2),flush=True);b.close()
