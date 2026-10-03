"""Reach probe: fully extended jab (rendered glove) vs opponent's rendered head, per fighter distance.

Prints the gap (m) between glove centre and the head hit sphere surface; <= 0 means the jab lands.
Usage: python scripts/probe_boxing_reach.py [avatar]
"""
import json, sys
from playwright.sync_api import sync_playwright

avatar = sys.argv[1] if len(sys.argv) > 1 else 'boxer-prism31'
PROBE = """async(distances)=>{
  const d=cornerDebug,{neutralPose}=await import('/static/boxing_core.mjs');
  // Menu state: no simulation moves the fighters, so the distance is exactly what we set.
  const f=d.fighters,out={};
  for(const dist of distances){
    // Straight jab at face height: left wrist 0.6 m in front, aimed at the opponent's face.
    const p=neutralPose();p[12]=[p[8][0]*0.15,p[15][1]-0.12,p[8][2]+0.6];p[10]=[p[8][0]*0.6,p[8][1]+0.05,p[8][2]+0.3];
    for(let k=0;k<20;k++){
      Object.assign(f[0],{x:0,z:-dist/2,yaw:0});Object.assign(f[1],{x:0,z:dist/2,yaw:Math.PI});
      f[1].ai={mode:'open',until:1e12,next:1e12,guard:0,punch:null,attack:0};
      d.reviewPose(p.map(v=>v.slice()));await new Promise(r=>requestAnimationFrame(r));}
    const hb=d.presentation().hitboxes,g=hb[0].gloves[0],h=hb[1].head;
    out[dist]=+(Math.hypot(g[0]-h.c[0],g[1]-h.c[1],g[2]-h.c[2])-h.r).toFixed(3);
  }
  return out;}"""
with sync_playwright() as p:
    b = p.chromium.launch(args=['--use-angle=d3d11', '--ignore-gpu-blocklist'])
    pg = b.new_page()
    pg.add_init_script("localStorage.setItem('labAvatarId','%s')" % avatar)
    pg.goto('http://127.0.0.1:8780/static/boxing.html')
    pg.wait_for_function('window.cornerDebug?.state().loaded', timeout=90000)
    print(avatar, json.dumps(pg.evaluate(PROBE, [0.7, 0.8, 0.9, 0.95, 1.05, 1.2])), flush=True)
    b.close()
