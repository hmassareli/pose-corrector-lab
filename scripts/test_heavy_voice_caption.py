"""Actual Victor playback, priorities, rendered captions and restored impact words."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'experiments/heavy_hands_gauntlet'
manifest=json.loads((ROOT/'assets/boxing_audio/victor_clips/manifest.json').read_text())['clips']
SETUP=r'''async view=>{
 const T=await import('three'),core=await import('/static/boxing_core.mjs'),d=cornerDebug;
 d.paused=true;await new Promise(r=>requestAnimationFrame(r));d.enter();d.reviewPose(core.neutralPose());
 document.getElementById('view').value=view;d.view();d.snapCamera=true;d.fighters.forEach(f=>f.tracking=false);
 for(let i=0;i<10;i++)d.frame(performance.now()+i*17);
 await d.audio.start();d.audio.resetFight();d.audio.setEnabled(true);d.audio.setVolume(.5);d.audio.setVoiceVolume(.85);
 window.captionMeshSamples=[];
 // Independent rendered vertex sample, not the implementation's bone boxes.
 for(const a of d.actors)a.group.traverse(m=>{
  if(!m.isMesh||!m.visible)return;if(m.isSkinnedMesh)m.skeleton.update();
  for(let i=0;i<m.geometry.attributes.position.count;i+=13){
   if(a.clip.active.value>.5&&m.isSkinnedMesh){
    const head=[a.rig.bones.get('head')?.bone,a.rig.bones.get('neck')?.bone];let weight=0;
    for(let j=0;j<4;j++)if(head.includes(m.skeleton.bones[m.geometry.attributes.skinIndex.getComponent(i,j)]))weight+=m.geometry.attributes.skinWeight.getComponent(i,j);
    if(weight>.08)continue;
   }
   const p=m.getVertexPosition(i,new T.Vector3()).applyMatrix4(m.matrixWorld).project(d.camera);
   const x=(p.x+1)*innerWidth/2,y=(1-p.y)*innerHeight/2;
   if(p.z>=-1&&p.z<=1&&x>=0&&x<=innerWidth&&y>=0&&y<=innerHeight)captionMeshSamples.push({x,y});
  }
 });
 return {samples:captionMeshSamples.length};
}'''
SAMPLE=r'''()=>{
 const e=document.getElementById('voiceCaption'),d=cornerDebug;d.frame(performance.now());
 const animation=e.getAnimations()[0],rows=[];
 for(const ms of [80,200,450,1000]){
  if(animation){animation.pause();animation.currentTime=ms;}
  const r=e.getBoundingClientRect(),visible=!e.hidden&&+getComputedStyle(e).opacity>.01;
  const covers=visible?captionMeshSamples.filter(p=>p.x>=r.left&&p.x<=r.right&&p.y>=r.top&&p.y<=r.bottom).length:0;
  const overlaps=[];
  if(visible)for(const selector of ['header','#hud','#guide','footer','#banner','#combatMessage']){
   const el=document.querySelector(selector);if(el.hidden||+getComputedStyle(el).opacity===0||!el.textContent)continue;
   const b=el.getBoundingClientRect();if(b.width&&b.height&&r.left<b.right&&r.right>b.left&&r.top<b.bottom&&r.bottom>b.top)overlaps.push(selector);
  }
  rows.push({ms,visible,covers,overlaps,rect:{x:r.x,y:r.y,width:r.width,height:r.height}});
 }
 return {clip:e.dataset.clip,text:e.textContent,hidden:e.hidden,overflow:e.scrollWidth>e.clientWidth+1,rows};
}'''
results=[];errors=[]
with sync_playwright() as p:
 b=p.chromium.launch(args=['--use-angle=d3d11','--ignore-gpu-blocklist','--autoplay-policy=no-user-gesture-required'])
 for width,height,view in [(1440,900,'third'),(1440,900,'first'),(390,844,'third'),(390,844,'first'),(844,390,'third')]:
  page=b.new_page(viewport={'width':width,'height':height});page.on('pageerror',lambda e:errors.append(str(e)))
  page.goto('http://127.0.0.1:8780/static/boxing.html');page.wait_for_function('window.cornerDebug?.state().loaded',timeout=90000)
  setup=page.evaluate(SETUP,view);phrases=[]
  for line in manifest:
   page.evaluate("clip=>{cornerDebug.audio.say(clip,100)}",line['name']);page.wait_for_timeout(80)
   row=page.evaluate(SAMPLE);assert row['clip']==line['name'] and row['text']==line['text'],row
   assert not row['overflow'],row
   assert all(s['covers']==0 and not s['overlaps'] for s in row['rows']),row
   phrases.append(row)
   if line['name']=='pressure_guard_up':page.screenshot(path=str(OUT/f'voice-caption-{width}-{height}-{view}.png'))
  visible=sum(not q['hidden'] for q in phrases)
  assert visible>0,{'viewport':[width,height],'view':view,'phrases':phrases}
  # The actual audio arbitration decides which phrase appears.
  page.evaluate("()=>{const a=cornerDebug.audio;a.resetFight();a.say('combo_combo',20);a.say('hit_good',40);a.say('hit_clean',60)}")
  page.wait_for_timeout(80);priority=page.evaluate("()=>({clip:document.getElementById('voiceCaption').dataset.clip,rejected:cornerDebug.audio.say('combo_combo',20)})")
  assert priority=={'clip':'hit_clean','rejected':False},priority
  page.evaluate("cornerDebug.audio.say('ko_k_o',100)");page.wait_for_timeout(80)
  assert page.evaluate("document.getElementById('voiceCaption').dataset.clip")=='ko_k_o'
  page.evaluate("cornerDebug.audio.setVoiceVolume(0)");assert page.locator('#voiceCaption').is_hidden()
  page.evaluate("cornerDebug.audio.setVoiceVolume(.85)")
  page.evaluate("cornerDebug.audio.say('pressure_move',100)");page.wait_for_timeout(80)
  page.evaluate("cornerDebug.audio.setEnabled(false)");assert page.locator('#voiceCaption').is_hidden()
  page.evaluate("cornerDebug.audio.setEnabled(true);cornerDebug.audio.say('pressure_guard_up',100)");page.wait_for_timeout(80)
  page.evaluate("cornerDebug.audio.resetFight()");assert page.locator('#voiceCaption').is_hidden()
  impacts=[]
  for kind,force,blocked,word in [('clean',180,False,'THUD'),('clean',800,False,'CRACK'),('chin',1200,False,'BOOM'),('arm',800,True,'CLACK')]:
   page.evaluate("()=>document.getElementById('fxLayer').replaceChildren()")
   page.evaluate("e=>cornerDebug.reviewEffect(e)",{'kind':kind,'forceN':force,'victim':1,'dir':[0,0,1],'head':True,'blocked':blocked,'hand':0})
   actual=page.locator('.impact-sound').inner_text();assert actual==word,(kind,force,actual)
   impacts.append({'kind':kind,'forceN':force,'word':actual})
   if kind=='chin' and view=='third':
    page.evaluate("cornerDebug.frame(performance.now())");page.wait_for_timeout(140)
    page.screenshot(path=str(OUT/f'impact-word-{width}-{height}.png'))
  results.append({'viewport':[width,height],'view':view,'setup':setup,'visiblePhrases':visible,'total':len(phrases),'priority':priority,'impacts':impacts,'phrases':phrases});page.close()
 # Reduced motion retains readable text without movement.
 page=b.new_page(viewport={'width':1440,'height':900},reduced_motion='reduce');page.goto('http://127.0.0.1:8780/static/boxing.html');page.wait_for_function('window.cornerDebug?.state().loaded',timeout=90000);page.evaluate(SETUP,'third')
 page.evaluate("cornerDebug.audio.say('pressure_guard_up',100)");page.wait_for_timeout(100)
 reduced=page.evaluate("()=>{const e=document.getElementById('voiceCaption');return {hidden:e.hidden,opacity:getComputedStyle(e).opacity,animations:e.getAnimations().length}}")
 assert reduced=={'hidden':False,'opacity':'1','animations':0},reduced
 page.wait_for_timeout(1800);assert page.locator('#voiceCaption').is_hidden();b.close()
assert not errors,errors
result={'result':'PASS','cases':results,'reducedMotion':reduced,'errors':errors,'limitations':'Native vertex sampling and transformed DOM bounds in deterministic poses; no new live human webcam session.'}
(OUT/'voice-caption-test.json').write_text(json.dumps(result,indent=2),encoding='utf8')
print(json.dumps({'result':result['result'],'cases':[{k:v for k,v in row.items() if k!='phrases'} for row in results],'reducedMotion':reduced,'errors':errors},indent=2))
