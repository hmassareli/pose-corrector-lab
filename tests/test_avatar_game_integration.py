"""Game and Live bridge integration for the head solver, using real assets."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parents[1]
out = root / "experiments/retarget_pose_fixes"
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": 1366, "height": 768})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto("http://127.0.0.1:8780/static/boxing.html", wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    status = page.locator("#loadStatus").text_content()
    print("loadStatus", status, flush=True)
    if not page.evaluate("window.cornerDebug?.state().loaded"):
        print(errors, flush=True)
    page.wait_for_function("window.cornerDebug?.state().loaded", timeout=10000)
    result = page.evaluate(r"""async()=>{
      const S=await import('/static/mikapo_mixamo_solver.js'),T=await import('three');
      const {neutralPose}=await import('/static/boxing_core.mjs');
      cornerDebug.paused=true;const a=cornerDebug.actors[0];
      document.getElementById('smooth').value=0;document.getElementById('smooth').dispatchEvent(new Event('input'));
      cornerDebug.reviewPose(neutralPose());cornerDebug.enter();
      const f=cornerDebug.fighters[0],p=neutralPose();
      const aux={...f.aux,head:new T.Vector3(0,1.72,0),neck:new T.Vector3(0,1.55,0),
        left_eye:new T.Vector3(.035,1.75,.08),right_eye:new T.Vector3(-.035,1.75,.08),jaw:new T.Vector3(0,1.66,.06)};
      S.resetHeadCalibration(a.rig);
      let now=performance.now();const feed=async aux=>{
        await new Promise(r=>setTimeout(r,34));now=performance.now();window.dispatchEvent(new MessageEvent('message',{origin:location.origin,source:document.getElementById('tracker').contentWindow,
          data:{type:'corner-pose',backend:'nlf',time:now,pose:p,aux}}));cornerDebug.frame(now);
      };
      const q=()=>a.root.getWorldQuaternion(new T.Quaternion()).invert().multiply(a.rig.bones.get('head').bone.getWorldQuaternion(new T.Quaternion()));
      await feed(aux);const baseline=q(),pitch=new T.Quaternion().setFromAxisAngle(new T.Vector3(1,0,0),Math.PI/6);
      const rotated=Object.fromEntries(Object.entries(aux).map(([k,v])=>[k,v?.clone?.()||v]));
      for(const n of ['left_eye','right_eye','jaw'])rotated[n].sub(aux.head).applyQuaternion(pitch).add(aux.head);
      await feed(rotated);const delta=q().multiply(baseline.clone().invert());
      const error=T.MathUtils.radToDeg(delta.angleTo(pitch));
      document.getElementById('view').value='first';cornerDebug.view();cornerDebug.frame(now+16);
      document.getElementById('view').value='third';cornerDebug.view();cornerDebug.frame(now+32);
      const before=S.getHeadRetargetDiagnostics(a.rig);document.getElementById('calibrate').click();
      const after=S.getHeadRetargetDiagnostics(a.rig);
      const contactReset=a.guardContact.hands.every(h=>h.previous===null);
      p[10]=[.32,1.38,.12];p[11]=[-.32,1.38,.12];p[12]=[.12,1.67,.02];p[13]=[-.12,1.67,.02];
      for(const [side,i]of [['left',12],['right',13]]){
        const w=new T.Vector3(...p[i]);rotated[side+'_wrist']=w;rotated[side+'_hand']=w.clone().add(new T.Vector3(0,.06,.01));
        rotated[side+'_index']=w.clone().add(new T.Vector3(.025,.06,.01));rotated[side+'_pinky']=w.clone().add(new T.Vector3(-.025,.06,.01));
      }
      await feed(rotated);
      return {pitchErrorDegrees:error,before,after,loaded:cornerDebug.state().loaded,contactReset,guardContacts:a.guardContact.diagnostics};
    }""")
    result["errors"] = errors
    (out / "game-integration.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result), flush=True)
    assert result["pitchErrorDegrees"] < .3 and result["after"] is None and not errors
    assert result["contactReset"] and len(result["guardContacts"])==2
    assert all(h['afterGap'] >= .0039 for h in result['guardContacts']),result
    browser.close()
