"""Limb twist benchmark: fails when any arm/leg bone twists past the candy-wrap limit
or jumps between neighbouring poses (the full-extension jab flip)."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parents[1] / 'experiments/twist_audit.json'
JUMP_DEG = 35
TEST = r'''async()=>{
 const core=await import('/static/boxing_core.mjs'),audit=await import('/static/avatar_twist_audit.js');
 const d=cornerDebug;d.paused=true;d.enter();
 const real=performance.now.bind(performance);let time=real();Object.defineProperty(performance,'now',{value:()=>time,configurable:true});
 const arm=(p,h,wrist,elbow)=>{const s=p[8+h],x=h?-1:1;p[12+h]=[s[0]+x*wrist[0],s[1]+wrist[1],s[2]+wrist[2]];p[10+h]=[s[0]+x*elbow[0],s[1]+elbow[1],s[2]+elbow[2]];return p;};
 const jab=e=>p=>{for(const h of[0,1])arm(p,h,[0,0,.53*e],[0,-.27*Math.sqrt(Math.max(0,1-e*e)),.265*e]);return p;};
 const sweeps={jab:[.6,.7,.8,.9,.95,.98,.995,1].map(e=>[`jab ${e}`,jab(e)]),
  shapes:[['guard',p=>p],['hook',p=>arm(p,0,[-.25,.02,.35],[.12,0,.25])],['uppercut',p=>arm(p,0,[-.05,.15,.35],[.02,-.2,.2])],
   ['elbowUp',p=>arm(p,0,[-.05,.15,.25],[.15,.05,.12])],['handsDown',p=>{p[12][1]-=.5;p[13][1]-=.5;return p;}]]};
 const rows=[];
 for(const [sweep,list] of Object.entries(sweeps)){let previous=null;
  for(const [name,fn] of list){
   for(let k=0;k<25;k++){time+=33;d.reviewPose(fn(core.neutralPose()));d.frame(time);}
   const r=audit.twistReport(d.actors[d.state().self].rig);
   const jump=previous&&sweep==='jab'?Math.max(...Object.keys(r).map(b=>Math.abs(r[b]-previous[b]))):0;
   const [bone,deg]=Object.entries(r).sort((a,b)=>b[1]-a[1])[0];
   rows.push({pose:name,worstBone:bone,twist:Math.round(deg),jump:Math.round(jump)});previous=r;}}
 Object.defineProperty(performance,'now',{value:real,configurable:true});
 return {limit:audit.TWIST_LIMIT_DEG,rows};
}'''
with sync_playwright() as p:
    b = p.chromium.launch(args=['--use-angle=d3d11', '--ignore-gpu-blocklist'])
    page = b.new_page(); errors = []; page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto('http://127.0.0.1:8780/static/boxing.html')
    page.wait_for_function('window.cornerDebug?.state().loaded', timeout=120000)
    report = {}
    for fighter in page.evaluate("[...document.getElementById('avatarSelect').options].map(o=>o.value)"):
        page.evaluate("v=>{const s=document.getElementById('avatarSelect');s.value=v;s.onchange();}", fighter)
        page.wait_for_function('window.cornerDebug?.state().loaded', timeout=120000)
        page.wait_for_timeout(1500)
        report[fighter] = page.evaluate(TEST)
        page.evaluate("cornerDebug.exit?.()")
    b.close()
failures = [(f, r) for f, rep in report.items() for r in rep['rows'] if r['twist'] > rep['limit'] or r['jump'] > JUMP_DEG]
for f, rep in report.items():
    print(f, ' '.join(f"{r['pose']}:{r['twist']}{'!' if r['jump'] > JUMP_DEG else ''}" for r in rep['rows']))
OUT.write_text(json.dumps({'report': report, 'failures': failures, 'errors': errors}, indent=2))
assert not errors, errors
assert not failures, failures
print('TWIST PASS')
