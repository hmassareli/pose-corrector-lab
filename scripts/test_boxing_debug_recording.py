"""Actual browser encoders + ZIP integrity + streaming sink. No human camera/NLF."""
import json, zipfile
import cv2
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'experiments' / 'boxing_debug_recording'
OUT.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(args=['--use-angle=d3d11', '--ignore-gpu-blocklist'])
    page = browser.new_page(viewport={'width':1280,'height':800}, accept_downloads=True)
    errors=[]
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto('http://127.0.0.1:8780/static/boxing.html', wait_until='domcontentloaded')
    page.wait_for_function('window.cornerDebug?.state().loaded && document.querySelector("#tracker").contentWindow.cornerTracking', timeout=90000)
    # Asymmetric physical point: the same horizontal reflection as the webcam,
    # independent of the tracker's selfie calibration. Coordinates stay intact.
    page.evaluate('''async()=>{
      const {projectWebcamSkeleton}=await import('/static/boxing_debug_recording.js');
      const rect={left:20,top:30,width:384,height:216},raw=[[.6,.3,3]],before=JSON.stringify(raw);
      const info={size:[640,360],fov:55};
      const expected=projectWebcamSkeleton({debug:{rawCameraJoints:raw},cameraInfo:info},rect);
      const mirrored=projectWebcamSkeleton({cameraPose:[[-.6,-.3,-3]],cameraInfo:{...info,selfieMirrored:true}},rect);
      const plain=projectWebcamSkeleton({cameraPose:[[.6,-.3,-3]],cameraInfo:{...info,selfieMirrored:false}},rect);
      if(expected[0][0]>=rect.left+rect.width/2 || expected[0][1]<=rect.top+rect.height/2
        || JSON.stringify(expected)!==JSON.stringify(mirrored) || JSON.stringify(expected)!==JSON.stringify(plain)
        || JSON.stringify(raw)!==before) throw new Error('Webcam / skeleton reflection mismatch');
    }''')
    # No camera: clear UI feedback without a second camera permission request.
    page.click('#debugRecord')
    assert not page.evaluate('cornerDebug.recorder.recording')
    assert page.locator('#combatMessage').inner_text() in ('Sem webcam','No camera')
    # Moving test video, independent of real capture/inference. Feed real adapter.
    page.evaluate('''async()=>{
      const canvas=document.createElement('canvas');canvas.width=640;canvas.height=360;
      const ctx=canvas.getContext('2d');let count=0;
      window.testTimer=setInterval(()=>{ctx.fillStyle=count++%2?'#cc5333':'#3388cc';ctx.fillRect(0,0,640,360);ctx.fillStyle='white';ctx.fillRect(count%500,80,80,180);},50);
      const video=document.querySelector('#tracker').contentWindow.cornerTracking.video;
      video.srcObject=canvas.captureStream(20);video.muted=true;await video.play();
      const {neutralPose}=await import('/static/boxing_core.mjs');cornerDebug.reviewPose(neutralPose());cornerDebug.enter(false);
      window.feedDebugPose=async index=>{
        const pose=neutralPose();pose[3][1]+=.15*(index%2);pose[12][0]-=.05;
        const cameraPose=pose.map(p=>[p[0],p[1]-.9,p[2]-4]);
        window.dispatchEvent(new MessageEvent('message',{origin:location.origin,source:document.querySelector('#tracker').contentWindow,
          data:{type:'corner-pose',backend:'nlf',time:performance.now(),pose,cameraPose,cameraInfo:{size:[640,360],fov:55},
            debug:{frameId:index,capture:{absoluteMs:performance.timeOrigin+performance.now()-30,webcamTime:video.currentTime},rawCameraJoints:cameraPose,serverMs:20}}}));
      };
    }''')
    page.evaluate("()=>{window.showDirectoryPicker=async()=>{throw new DOMException('cancel','AbortError')};}")
    page.click('#debugRecord')
    page.wait_for_function('!cornerDebug.recorder.busy')
    assert not page.evaluate('cornerDebug.recorder.recording')
    assert page.evaluate("document.querySelector('#tracker').contentWindow.cornerTracking.video.srcObject.getVideoTracks()[0].readyState")=='live'
    # Fallback: start/stop by the visible red button and validate actual download.
    page.evaluate('window.showDirectoryPicker=undefined')
    page.click('#debugRecord')
    page.wait_for_function('cornerDebug.recorder.recording')
    for i in range(12):
        page.evaluate('i=>feedDebugPose(i)',i)
        page.wait_for_timeout(120)
    page.screenshot(path=str(OUT/'recording-ui.png'))
    with page.expect_download(timeout=30000) as download:
        page.click('#debugRecord')
    archive=OUT/'capture.zip'; download.value.save_as(str(archive))
    page.wait_for_function('!cornerDebug.recorder.busy')
    assert page.evaluate("document.querySelector('#tracker').contentWindow.cornerTracking.video.srcObject.getVideoTracks()[0].readyState")=='live'
    assert not page.evaluate("document.querySelector('#tracker').contentWindow.cornerTracking.debugRecording")
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        manifest=json.loads(z.read('manifest.json'))
        timeline=[json.loads(line) for line in z.read('timeline.ndjson').splitlines()]
        frames=[r for r in timeline if r['type']=='frame']; poses=[r for r in timeline if r['type']=='pose']
        assert manifest['error'] is None, manifest
        assert len(frames)>=5 and len(poses)==12, (len(frames),len(poses))
        assert [r['tMs'] for r in frames]==sorted(r['tMs'] for r in frames)
        assert poses[0]['input']['debug']['frameId']==0
        assert all(r['actors'][0]['rig']['bones'] and r['actors'][1]['rig']['bones'] for r in frames)
        assert any(set(r['stages']['0'])=={'retarget','handAlignment','feetAndReaction','blockHold','selfContact'} for r in frames)
        assert frames[-1]['poseSequence']==12 and frames[-1]['sourceAgeMs']>=0
        prints=[n for n in z.namelist() if n.startswith('prints/')]
        assert prints
        z.extract(prints[0],OUT)
        video_paths=[]
        for video in manifest['videos']:
            data=z.read(video['path']); assert len(data)>1000
            path=OUT/video['path'];path.write_bytes(data);video_paths.append(path)
    # Decode with browser to verify real playable recordings (not just nonempty files).
    playback=page.evaluate('''async()=>{
      const zip=cornerDebug.recorder.lastResult.blob;
      // Stored ZIP local entries are sufficient for playback validation.
      const data=new Uint8Array(await zip.arrayBuffer()),view=new DataView(data.buffer);let at=0,results=[];
      while(view.getUint32(at,true)===0x04034b50){
        const size=view.getUint32(at+18,true),nl=view.getUint16(at+26,true),el=view.getUint16(at+28,true);
        const name=new TextDecoder().decode(data.slice(at+30,at+30+nl)),start=at+30+nl+el;
        if(name.endsWith('.webm')||name.endsWith('.mp4')){
          const v=document.createElement('video');v.muted=true;const url=URL.createObjectURL(new Blob([data.slice(start,start+size)]));v.src=url;
          await new Promise((resolve,reject)=>{v.onloadeddata=resolve;v.onerror=()=>reject(new Error('Cannot decode '+name));});
          results.push({name,width:v.videoWidth,height:v.videoHeight});URL.revokeObjectURL(url);
        }at=start+size;
      }return results;
    }''')
    assert len(playback)==2 and all(v['width']>0 for v in playback),playback
    decoded={}
    for path in video_paths:
        cap=cv2.VideoCapture(str(path));count=0;variations=[]
        while True:
            ok,image=cap.read()
            if not ok: break
            count+=1;variations.append(float(image.std()))
        cap.release();assert count>=5 and max(variations)>20,(path,count,variations)
        decoded[path.name]=count
    # FileSystemAccess path: ordered appends to persistent writable handles.
    page.evaluate('''()=>{
      window.savedFiles={};window.closedFiles=[];
      const directory=prefix=>({getDirectoryHandle:async name=>directory(prefix+name+'/'),
        getFileHandle:async name=>({createWritable:async()=>({
          write:async data=>{(savedFiles[prefix+name]||=[]).push(data);},
          close:async()=>{closedFiles.push(prefix+name);}
        })})});
      window.showDirectoryPicker=async()=>directory('');
    }''')
    page.click('#viewButton')
    page.click('#debugRecord');page.wait_for_function('cornerDebug.recorder.recording')
    for i in range(3): page.evaluate('i=>feedDebugPose(i+20)',i);page.wait_for_timeout(160)
    page.click('#debugRecord');page.wait_for_function('!cornerDebug.recorder.busy')
    streamed=page.evaluate('''async()=>{
      const files=Object.keys(savedFiles);const name=files.find(n=>n.endsWith('manifest.json'));
      const manifest=JSON.parse(await new Blob(savedFiles[name]).text());
      return {manifest,files,closed:closedFiles,live:document.querySelector('#tracker').contentWindow.cornerTracking.video.srcObject.getVideoTracks()[0].readyState};
    }''')
    assert streamed['manifest']['storage']=='folder' and streamed['manifest']['error'] is None,streamed
    assert streamed['manifest']['initial']['first'] is True
    assert len(streamed['closed'])==len(streamed['files']) and streamed['live']=='live'
    # Real iframe capture -> JPEG -> WS -> NLF result -> parent adapter, with
    # inference mocked. No model/GPU benchmark and no access to a human webcam.
    neutral=page.evaluate("async()=>{const m=await import('/static/boxing_core.mjs');return m.neutralPose();}")
    joints=[[-x,-y,-z] for x,y,z in neutral]
    camera=[[-x,.9-y,4-z] for x,y,z in neutral]
    page.evaluate('''async fixture=>{
      const f=document.querySelector('#tracker').contentWindow,stream=f.cornerTracking.video.srcObject;
      f.cornerTracking.stop();
      const originalFetch=f.fetch.bind(f);
      f.fetch=async (url,opts)=>String(url).includes('/api/nlf_warmup')||String(url).includes('/api/nlf_status')
        ? new Response(JSON.stringify({device:'test',backend:'mock',ws_url:'ws://corner-debug-test/nlf'}),{headers:{'Content-Type':'application/json'}})
        : originalFetch(url,opts);
      f.WebSocket=class {
        static OPEN=1;static CONNECTING=0;
        constructor(){this.readyState=0;setTimeout(()=>{this.readyState=1;this.onopen?.();},5);}
        close(){this.readyState=3;this.onclose?.();}
        send(message){
          const data=typeof message==='string'?{type:'warmup',ok:true}:
            {type:'pose',ok:true,frame_id:new DataView(message).getUint32(4,true),joints:fixture.joints,
              camera_joints:fixture.camera,image_size:[640,360],camera_fov:55,ms:7,smplx55:[],smplx55_names:[]};
          setTimeout(()=>this.onmessage?.({data:JSON.stringify(data)}),5);
        }
      };
      f.navigator.mediaDevices.getUserMedia=async()=>stream;
      await f.cornerTracking.start();
    }''',{'joints':joints,'camera':camera})
    page.click('#debugRecord');page.wait_for_function('cornerDebug.recorder.recording')
    page.wait_for_function('cornerDebug.recorder.latest?.debug?.capture',timeout=20000)
    source=page.evaluate('cornerDebug.recorder.latest.debug')
    for key,expected in [('rawJoints',joints),('rawCameraJoints',camera)]:
        assert len(source[key])==len(expected)
        error=max(abs(a-b) for got,want in zip(source[key],expected) for a,b in zip(got,want))
        assert error<1e-9,(key,error,source[key][:2],expected[:2])
    assert source['capture']['absoluteMs']<=source['receivedAbsoluteMs'] and source['capture']['webcamTime']>=0
    assert source['frameId']>0 and source['serverMs']==7
    page.click('#debugRecord');page.wait_for_function('!cornerDebug.recorder.busy')
    page.evaluate("document.querySelector('#tracker').contentWindow.cornerTracking.stop()")
    assert not errors, errors
    report={'result':'PASS','frames':len(frames),'poses':len(poses),'playback':playback,'decodedFrames':decoded,'streamedFiles':len(streamed['files']),
      'checks':['no-camera feedback','cancel picker','visible button start/stop','ZIP CRC integrity','both videos decode','raw input timestamp/ID',
                'all native bones for both avatars','five independent retarget stages','snapshot JPEG','streaming appends and closes','repeat recording','webcam survives stop',
                'real iframe JPEG/WS/pose adapter path with mocked inference','raw NLF output and capture timestamp preserved','first and third person capture',
                'webcam overlay reflection with both selfie calibration modes'], 'errors':errors}
    (OUT/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report),flush=True)
    page.evaluate('clearInterval(window.testTimer)');browser.close()
