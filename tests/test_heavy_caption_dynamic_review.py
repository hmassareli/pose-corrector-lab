"""Independent moving NLF pose + current skinned vertices + actual DOM review."""
import hashlib,json
from pathlib import Path
import numpy as np
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'experiments/heavy_hands_gauntlet'
cam=np.load(ROOT/'benchmarks/punch_cadence_20261002.nlf.npz')['cam']
scale=1.72/float(np.median(cam[150:450,15,1]-np.minimum(cam[150:450,5,1],cam[150:450,6,1])))
poses=[]
for frame in cam[150:1350:60]:
 q=frame.copy();q[:,0]-=frame[0,0];q[:,2]-=frame[0,2];q[:,1]-=min(frame[5,1],frame[6,1]);poses.append((q*scale).tolist())
PROBE=r'''async ({poses,view})=>{
 const T=await import('three'),{characterScreenRegions}=await import('/static/boxing_caption_bounds.js'),{VoiceCaption}=await import('/static/boxing_voice_caption.js'),d=cornerDebug;
 d.paused=true;await new Promise(r=>requestAnimationFrame(r));d.audio.setEnabled(false);d.enter();
 document.getElementById('view').value=view;d.view();d.reviewPose(poses[0]);d.frame(performance.now());
 const cold=d.actors.map(a=>{const start=performance.now(),regions=characterScreenRegions(a,d.camera,innerWidth,innerHeight);return {avatar:a.id,ms:performance.now()-start,regions:regions.length};});
 const hot=[];for(let i=0;i<80;i++){const start=performance.now();d.actors.forEach(a=>characterScreenRegions(a,d.camera,innerWidth,innerHeight));hot.push(performance.now()-start);}
 const shadow=document.getElementById('voiceCaption').cloneNode(true);shadow.id='independentCaptionBenchmark';document.body.append(shadow);
 const c=new VoiceCaption(shadow,()=>d.actors.flatMap(a=>characterScreenRegions(a,d.camera,innerWidth,innerHeight)),()=>true);
 c.line={text:'PERFECT COUNTER'};shadow.querySelector('strong').textContent=c.line.text;const layout=[];
 for(let i=0;i<80;i++){const start=performance.now();c.update();layout.push(performance.now()-start);}c.clear();shadow.remove();
 d.audio.setEnabled(true);await d.audio.start();d.audio.resetFight();d.audio.setVolume(.5);d.audio.setVoiceVolume(.85);
 const frames=[];let outsideRegions=0,sampleCount=0;
 for(let i=0;i<poses.length;i++){
  d.reviewPose(poses[i]);d.fighters[1].x=.35*Math.sin(i*.38);d.fighters[1].z=.25*Math.cos(i*.29);
  d.audio.say(i%2?'counter_perfect_counter':'pressure_guard_up',100);await new Promise(r=>setTimeout(r,35));
  d.frame(performance.now());
  const el=document.getElementById('voiceCaption'),animation=el.getAnimations()[0];
  if(animation){animation.pause();animation.currentTime=[80,200,450,1000][i%4];}
  const rect=el.getBoundingClientRect(),visible=!el.hidden&&+getComputedStyle(el).opacity>.01;
  let covered=0,samples=0,missed=0;
  for(const a of d.actors){
   const regions=characterScreenRegions(a,d.camera,innerWidth,innerHeight),headBones=[a.rig.bones.get('head')?.bone,a.rig.bones.get('neck')?.bone];
   a.group.traverse(m=>{
    if(!m.isMesh)return;for(let n=m;n;n=n.parent)if(!n.visible)return;
    if(m.isSkinnedMesh)m.skeleton.update();
    for(let v=0;v<m.geometry.attributes.position.count;v+=29){
     if(a.clip?.active.value>.5&&m.isSkinnedMesh){let weight=0;
      for(let j=0;j<4;j++)if(headBones.includes(m.skeleton.bones[m.geometry.attributes.skinIndex.getComponent(v,j)]))weight+=m.geometry.attributes.skinWeight.getComponent(v,j);
      if(weight>.08)continue;
     }
     const p=m.getVertexPosition(v,new T.Vector3()).applyMatrix4(m.matrixWorld).project(d.camera);
     const x=(p.x+1)*innerWidth/2,y=(1-p.y)*innerHeight/2;
     if(p.z<-1||p.z>1||x<0||x>innerWidth||y<0||y>innerHeight)continue;samples++;
     if(!regions.some(r=>x>=r.x&&x<=r.x+r.width&&y>=r.y&&y<=r.y+r.height))missed++;
     if(visible&&x>=rect.left&&x<=rect.right&&y>=rect.top&&y<=rect.bottom)covered++;
    }
   });
  }
  const overlaps=[];
  if(visible)for(const selector of ['header','#hud','#guide','footer','#banner','#combatMessage','#fxLayer .pow'])for(const node of document.querySelectorAll(selector)){
   if(node.hidden||+getComputedStyle(node).opacity===0||!node.textContent)continue;const b=node.getBoundingClientRect();
   if(b.width&&b.height&&rect.left<b.right&&rect.right>b.left&&rect.top<b.bottom&&rect.bottom>b.top)overlaps.push(selector);
  }
  outsideRegions+=missed;sampleCount+=samples;
  frames.push({pose:i,visible,text:el.textContent,samples,missed,covered,overlaps,rect:{x:rect.x,y:rect.y,width:rect.width,height:rect.height}});
 }
 d.audio.resetFight();const sorted=a=>a.slice().sort((x,y)=>x-y),stat=a=>({mean:a.reduce((x,y)=>x+y,0)/a.length,p50:sorted(a)[Math.floor(a.length*.5)],p95:sorted(a)[Math.floor(a.length*.95)],max:Math.max(...a)});
 return {cold,hotBoundsBothActors:stat(hot),hotBoundsAndLayout:stat(layout),frames,sampleCount,outsideRegions,visibleFrames:frames.filter(f=>f.visible).length};
}'''
rows=[];errors=[]
with sync_playwright() as p:
 b=p.chromium.launch(args=['--use-angle=d3d11','--ignore-gpu-blocklist','--autoplay-policy=no-user-gesture-required'])
 for width,height,view in [(1280,800,'third'),(1280,800,'first'),(390,844,'third'),(390,844,'first')]:
  page=b.new_page(viewport={'width':width,'height':height});page.on('pageerror',lambda e:errors.append(str(e)))
  page.goto('http://127.0.0.1:8780/static/boxing.html');page.wait_for_function('window.cornerDebug?.state().loaded',timeout=90000)
  source_before=hashlib.sha256((ROOT/'viewer/boxing_caption_bounds.js').read_bytes()).hexdigest()
  data=page.evaluate(PROBE,{'poses':poses,'view':view})
  source_after=hashlib.sha256((ROOT/'viewer/boxing_caption_bounds.js').read_bytes()).hexdigest()
  rows.append({'viewport':[width,height],'view':view,'boundsHashBefore':source_before,'boundsHashAfter':source_after,**data});page.close()
 b.close()
geometry_pass=not errors and all(not r['outsideRegions'] and all(not f['covered'] and not f['overlaps'] for f in r['frames']) for r in rows)
presentation_all=all(r['visibleFrames']>0 for r in rows)
result={'cases':rows,'errors':errors,'geometryPass':geometry_pass,'presentationVisibleInEveryCase':presentation_all,'result':('PASS' if presentation_all else 'GEOMETRY_PASS_PRESENTATION_PARTIAL') if geometry_pass else 'FAIL','limitations':'Every29th native vertex; 20 moving cached NLF poses and moving roots per viewport. Visibility measured explicitly; hidden captions do not count as presentation success. No live human camera.'}
(OUT/'independent-caption-dynamic-review.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps({**result,'cases':[{k:v for k,v in r.items() if k!='frames'} for r in rows]},indent=2))
