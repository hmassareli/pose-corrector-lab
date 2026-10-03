"""Actual browser webcam→JPEG→NLF→Live bridge→game, using a prerecorded camera.

Uses no keyboard or synthetic pose hook. Does not certify a new human session.
"""
import json,statistics,time,sys,subprocess
from pathlib import Path
from playwright.sync_api import sync_playwright

root=Path(__file__).resolve().parents[1]
out=root/'experiments'/'heavy_hands_gauntlet'
out.mkdir(exist_ok=True)
source_replay=root/'experiments/boxing_review/webcam-replay.y4m'
replay=source_replay if 'raw-recorded' in sys.argv else out/'webcam-calibrated-replay.y4m'
if not replay.exists():
 # Calibration explicitly asks the player to hold still for half a second.
 # The eight-second boxing fixture has continuous punches: prefix two seconds
 # of its own first camera image, then retain every original moving frame.
 subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(source_replay),'-vf','tpad=start_mode=clone:start_duration=2','-pix_fmt','yuv420p',str(replay)],check=True)
with sync_playwright() as p:
 browser=p.chromium.launch(args=([] if 'default-gpu' in sys.argv else ['--use-angle=d3d11','--ignore-gpu-blocklist'])+['--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream','--use-file-for-fake-video-capture='+str(replay)])
 context=browser.new_context(viewport={'width':1440,'height':900},permissions=['camera'])
 context.add_init_script("localStorage.setItem('poseLab.handRetarget.v1', JSON.stringify({selfieMirror:true}));")
 if 'hidden-no-raf' in sys.argv:
  context.add_init_script("if(location.search.includes('gameBridge')) window.requestAnimationFrame = () => 0;")
 page=context.new_page();errors=[]
 page.on('pageerror',lambda e:errors.append(str(e)))
 page.goto('http://127.0.0.1:8780/static/boxing.html',wait_until='domcontentloaded')
 page.wait_for_function('window.cornerDebug?.state().loaded',timeout=60000)
 assert not page.frame_locator('#tracker').locator('#chkSelfieMirror').is_checked()
 assert page.evaluate("JSON.parse(localStorage.getItem('poseLab.handRetarget.v1')).selfieMirror") is True
 page.evaluate("window.trackingSamples=[];window.addEventListener('message',e=>{if(e.data.type==='corner-pose')trackingSamples.push({time:performance.now(),backend:e.data.backend,pelvis:e.data.pose[0],cameraPelvis:e.data.cameraPose?.[0],feetVisible:cornerDebug.fighters[0].footVisible,contacts:cornerDebug.fighters[0].footContacts});})")
 page.locator('#lobbyCamera').click()
 try:
  page.wait_for_function('!document.getElementById("train").disabled',timeout=120000)
 except Exception:
  failure=page.evaluate("({phase:'menu calibration',samples:trackingSamples.length,recent:trackingSamples.slice(-10),state:cornerDebug.state(),fighter:{tracking:cornerDebug.fighters[0].tracking,reference:cornerDebug.fighters[0].footwork.reference,stable:cornerDebug.fighters[0].footwork.stable},status:document.getElementById('trackingStatus').textContent,tracker:(()=>{const t=document.getElementById('tracker').contentWindow;const v=t.cornerTracking?.video;return {status:t.cornerTracking?.status(),videoTime:v?.currentTime,paused:v?.paused,readyState:v?.readyState}})()})")
  failure['errors']=errors
  (out/'recorded-webcam-failure.json').write_text(json.dumps(failure,indent=2),encoding='utf-8')
  print(json.dumps(failure),flush=True);raise
 menu_scale=page.evaluate('cornerDebug.fighters[0].footwork.reference.scale')
 page.locator('#train').click()
 assert page.evaluate('cornerDebug.fighters[0].footwork.reference?.scale')==menu_scale,'Training discarded the calibrated camera scale'
 page.wait_for_function("cornerDebug.fighters[cornerDebug.state().self].tracking",timeout=120000)
 page.wait_for_timeout(15000 if 'hidden-no-raf' in sys.argv else 5000)
 # Backend warmup/rebalancing can pause inference after the first pose. Wait
 # for enough actual observations instead of treating that startup as gait.
 try:
  page.wait_for_function('trackingSamples.length >= 20 && cornerDebug.state().clock < 89',timeout=45000)
 except Exception:
  failure=page.evaluate("({samples:trackingSamples.length,state:cornerDebug.state(),tracker:(()=>{const t=document.getElementById('tracker').contentWindow;const v=t.cornerTracking?.video;return {status:t.cornerTracking?.status(),videoTime:v?.currentTime,paused:v?.paused,readyState:v?.readyState}})()})")
  failure['errors']=errors
  (out/'recorded-webcam-failure.json').write_text(json.dumps(failure,indent=2),encoding='utf-8')
  print(json.dumps(failure),flush=True)
  raise
 samples=page.evaluate('trackingSamples');state=page.evaluate('cornerDebug.state()');poses=page.evaluate('cornerDebug.fighters.map(f=>({x:f.x,z:f.z,hp:f.hp,pose:f.pose}))')
 assert len(samples)>=15,(len(samples),state)
 assert all(s['backend']=='nlf' for s in samples)
 assert all(s.get('cameraPelvis') and s['cameraPelvis'][2]<-.2 for s in samples), 'NLF camera translation missing'
 assert state['clock']<89 and state['cameraOn']
 assert not errors,errors
 page.screenshot(path=str(out/'07-recorded-nlf-third.png'))
 page.locator('#viewButton').click()
 page.wait_for_function('cornerDebug.actors[cornerDebug.state().self].clip.active.value === 1',timeout=15000)
 first_view=page.evaluate("()=>{const a=cornerDebug.actors[cornerDebug.state().self], c=cornerDebug.camera;return {headClip:a.clip.active.value,camera:c.position.toArray(),head:a.clip.head.value.toArray()}}")
 page.screenshot(path=str(out/'08-recorded-nlf-first.png'))
 page.locator('#cameraButton').click();page.wait_for_timeout(400)
 paused=page.evaluate('cornerDebug.state().clock');page.wait_for_timeout(400)
 assert page.evaluate('cornerDebug.state().clock')==paused
 gaps=[samples[i]['time']-samples[i-1]['time'] for i in range(1,len(samples))]
 if 'hidden-no-raf' in sys.argv:
  assert max(gaps)<500, max(gaps)
 nlf_status=page.evaluate("async()=>await (await fetch('/api/nlf_status')).json()")
 report={'result':'PASS','input':'henrique_webcam_1.mp4, seconds 10–18, 640×360@15fps via fake camera','checks':['actual webcam pipeline','JPEG upload','NLF-S inference','pose bridge','game follows poses','both camera screenshots','camera stop pauses round'],'nlfBackend':nlf_status.get('backend'),'nlfDevice':nlf_status.get('device'),'samples':len(samples),'receivedPoseFps':1000/statistics.median(gaps),'renderedState':state,'fighters':poses,'pageErrors':errors,'limitations':'Recorded replay, not live human latency/accuracy validation.'}
 report['hiddenIframeAnimationDisabled']='hidden-no-raf' in sys.argv
 report['maxPoseGapMs']=max(gaps)
 report['cameraTranslationPreserved']=True
 report['calibrationInput']='Original continuous recording' if replay==source_replay else 'Two seconds of first recorded camera image, followed by all original moving frames; half-second stability requirement unchanged'
 report['menuCalibrationPreservedOnEntry']=True
 report['firstPerson']=first_view
 report['inferredFootFrames']=sum(1 for s in samples if s.get('feetVisible') and not all(s['feetVisible']))
 report['cameraRootDepthRange']=[min(-s['cameraPelvis'][2] for s in samples),max(-s['cameraPelvis'][2] for s in samples)]
 if 'hidden-no-raf' in sys.argv:
  count=page.evaluate('trackingSamples.length')
  page.locator('#cameraButton').click()
  page.wait_for_function('(count)=>trackingSamples.length > count + 10',arg=count,timeout=15000)
  assert not errors,errors
  report['checks']+=['capture without iframe animation frames','no pose gaps over 500 ms in 15 seconds','camera restart resumes poses']
  page.locator('#cameraButton').click()
 (out/'recorded-webcam-test.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
 print(json.dumps({k:v for k,v in report.items() if k!='fighters'},indent=2),flush=True)
 browser.close()
