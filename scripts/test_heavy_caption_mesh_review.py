"""Independent sampled native skinned mesh bounds vs caption rig envelope."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
PROBE=r'''async view=>{
 const T=await import('three'),{neutralPose}=await import('/static/boxing_core.mjs'),{characterScreenBounds}=await import('/static/boxing_caption_bounds.js'),d=cornerDebug;
 d.paused=true;await new Promise(r=>requestAnimationFrame(r));d.enter();d.reviewPose(neutralPose());
 document.getElementById('view').value=view;d.view();
 d.fighters.forEach(f=>{f.tracking=false;});
 for(let i=0;i<10;i++)d.frame(performance.now()+i*17);
 const rows=[];
 for(const a of d.actors){
  a.group.updateMatrixWorld(true);
  const bones=[...new Set([...a.rig.bones.values()].flatMap(r=>[r.bone,r.child]).filter(Boolean))];
  const project=p=>{p.project(d.camera);return p.z>=-1&&p.z<=1?[(p.x+1)*innerWidth/2,(1-p.y)*innerHeight/2]:null;};
  const points=bones.map(b=>project(b.getWorldPosition(new T.Vector3()))).filter(Boolean);
  const bounds=pts=>({left:Math.min(...pts.map(p=>p[0])),right:Math.max(...pts.map(p=>p[0])),top:Math.min(...pts.map(p=>p[1])),bottom:Math.max(...pts.map(p=>p[1]))});
  const rig=bounds(points),meshPoints=[];let samples=0;
  a.root.traverse(m=>{if(!m.isMesh||!m.visible)return;if(m.isSkinnedMesh)m.skeleton.update();
   const count=m.geometry.attributes.position.count;
   for(let i=0;i<count;i+=7){const p=m.getVertexPosition(i,new T.Vector3()).applyMatrix4(m.matrixWorld);const q=project(p);
    if(q&&q[0]>=0&&q[0]<=innerWidth&&q[1]>=0&&q[1]<=innerHeight)meshPoints.push(q);samples++;}
  });
  const mesh=bounds(meshPoints),envelope=characterScreenBounds(a,d.camera,innerWidth,innerHeight);
  const containsSampledMesh=!!envelope&&envelope.x<=mesh.left&&envelope.x+envelope.width>=mesh.right&&envelope.y<=mesh.top&&envelope.y+envelope.height>=mesh.bottom;
  rows.push({avatar:a.id||a.avatarId,rig,mesh,envelope,containsSampledMesh,samples,visibleSamples:meshPoints.length,
    beyondPadding:{left:rig.left-36-mesh.left,right:mesh.right-rig.right-36,top:rig.top-36-mesh.top,bottom:mesh.bottom-rig.bottom-36}});
 }
 return rows;
}'''
rows=[]
with sync_playwright() as p:
 b=p.chromium.launch(args=['--use-angle=d3d11','--ignore-gpu-blocklist'])
 for viewport in [(1280,800),(390,844)]:
  page=b.new_page(viewport={'width':viewport[0],'height':viewport[1]})
  page.goto('http://127.0.0.1:8780/static/boxing.html')
  page.wait_for_function('window.cornerDebug?.state().loaded',timeout=90000)
  for view in ['third','first']:
   rows.append({'viewport':viewport,'view':view,'actors':page.evaluate(PROBE,view)})
  page.close()
 b.close()
(ROOT/'experiments/heavy_hands_gauntlet/independent-caption-mesh-review.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
print(json.dumps(rows,indent=2))
