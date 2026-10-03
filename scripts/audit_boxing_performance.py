"""Read-only render/CPU audit with synthetic poses, no webcam or inference load.

Run against the existing local server: python scripts/audit_boxing_performance.py
Numbers are browser presentation timings, NOT GPU execution or mocap latency.
"""
import collections
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'experiments/performance_audit_20261003'
OUT.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(args=['--use-angle=d3d11', '--ignore-gpu-blocklist'])
    page = browser.new_page(viewport={'width': 1366, 'height': 768}, device_scale_factor=1.5)
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto('http://127.0.0.1:8780/static/boxing.html')
    page.wait_for_function('window.cornerDebug?.state().loaded', timeout=120000)
    page.evaluate('''async()=>{
      const d=cornerDebug,c=await import('/static/boxing_core.mjs');
      d.audio.enabled=false; d.reviewPose(c.neutralPose()); d.enter();
      window.auditPose=setInterval(()=>d.reviewPose(c.neutralPose()),33);
      document.getElementById('view').value='third';d.view();
    }''')
    env = page.evaluate('''()=>{
      const d=cornerDebug,g=d.renderer.getContext(),x=g.getExtension('WEBGL_debug_renderer_info');
      const assets=d.actors.map(a=>{let meshes=0,vertices=0,triangles=0;const geometries=new Set(),materials=new Set();
        a.root.traverse(m=>{if(!m.isMesh)return;meshes++;geometries.add(m.geometry);
          for(const mat of Array.isArray(m.material)?m.material:[m.material])materials.add(mat);});
        for(const g of geometries){vertices+=g.attributes.position.count;triangles+=(g.index?.count||g.attributes.position.count)/3;}
        return {id:a.avatarId,meshes,vertices,triangles,materials:materials.size,bones:a.rig.bones.size};});
      return {userAgent:navigator.userAgent,gpu:x?g.getParameter(x.UNMASKED_RENDERER_WEBGL):g.getParameter(g.RENDERER),
        dpr:devicePixelRatio,viewport:[innerWidth,innerHeight],assets};
    }''')
    results=[]
    for level in ['high', 'balanced', 'low', 'low', 'balanced', 'high']:
        page.select_option('#quality', level, force=True)
        page.wait_for_timeout(1800)
        result=page.evaluate('''()=>new Promise(resolve=>{
          const d=cornerDebug,intervals=[],submit=[],original=d.renderer.render;
          d.renderer.render=function(...args){const t=performance.now();const r=original.apply(this,args);submit.push(performance.now()-t);return r;};
          const start=performance.now();let last=start;
          const stats=a=>{a.sort((x,y)=>x-y);return {p50:a[Math.floor(a.length*.5)],p95:a[Math.floor(a.length*.95)],max:a.at(-1)};};
          function tick(t){intervals.push(t-last);last=t;if(t-start<5000)return requestAnimationFrame(tick);
            d.renderer.render=original;const info=d.renderer.info;
            resolve({durationMs:t-start,frames:intervals.length,fps:intervals.length*1000/(t-start),
              frameMs:stats(intervals.slice(1)),renderSubmitMs:stats(submit),calls:info.render.calls,
              triangles:info.render.triangles,memory:info.memory,programs:info.programs.length,
              resolution:[d.renderer.domElement.width,d.renderer.domElement.height]});}
          requestAnimationFrame(tick);
        })''')
        results.append({'quality':level,**result})
        print(json.dumps(results[-1]), flush=True)
    page.select_option('#quality','high',force=True)
    page.wait_for_timeout(1500)
    cdp=page.context.new_cdp_session(page)
    cdp.send('Profiler.enable');cdp.send('Profiler.setSamplingInterval',{'interval':1000})
    cdp.send('Profiler.start');page.wait_for_timeout(5000)
    profile=cdp.send('Profiler.stop')['profile']
    (OUT/'baseline.cpuprofile').write_text(json.dumps(profile),encoding='utf-8')
    nodes={n['id']:n for n in profile['nodes']};counts=collections.Counter(profile.get('samples',[]))
    top=[{'name':nodes[i]['callFrame']['functionName'],'url':nodes[i]['callFrame']['url'],
          'line':nodes[i]['callFrame']['lineNumber']+1,'samples':n} for i,n in counts.most_common(30)]
    report={'environment':env,'scope':'Synthetic neutral pose + procedural sparring; no live inference; headless Chromium; sampling profile collected separately.',
            'runs':results,'cpuTopSelfSamples':top,'errors':errors}
    (OUT/'baseline.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'environment':env,'cpuTopSelfSamples':top[:15],'errors':errors},indent=2),flush=True)
    page.evaluate('clearInterval(auditPose)')
    browser.close()
