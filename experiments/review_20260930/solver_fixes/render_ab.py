"""A/B visual: mesmos pontos gravados do NLF, solver anterior e corrigido."""
from pathlib import Path
import hashlib,json,sys
from playwright.sync_api import sync_playwright
from PIL import Image,ImageDraw,ImageOps

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.stdout.reconfigure(encoding='utf-8')

def main():
 frames=json.loads((HERE/'benchmark_replay.json').read_text())
 html=(ROOT/'viewer/avatar_bake_seq.html').read_text(encoding='utf-8')
 # Poupe GPU entre medições: renderize somente quando a captura for pedida.
 # Toda a aplicação da pose e os filtros continuam executados em cada frame.
 html=html.replace('renderer.render(scene, camera);','if (globalThis.__reviewRenderEnabled) renderer.render(scene, camera);')
 base='http://127.0.0.1:8780'
 avatars=sys.argv[1:] or ['boxeador','fighter-web']
 records=[]
 if (HERE/'render_ab_measurements.json').exists():
  records=[r for r in json.loads((HERE/'render_ab_measurements.json').read_text()) if r['avatar'] not in avatars]
 with sync_playwright() as p:
  browser=p.chromium.launch(headless=True,args=['--enable-unsafe-swiftshader'])
  for avatar in avatars:
   captures={}
   for version in ['before','after']:
    source=(HERE/'solver_before.js' if version=='before' else ROOT/'viewer/mikapo_mixamo_solver.js').read_text(encoding='utf-8')
    context=browser.new_context(viewport={'width':720,'height':960})
    page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.route(base+'/bake_seq*',lambda route:route.fulfill(body=html,content_type='text/html'))
    page.route(base+'/static/mikapo_mixamo_solver.js',lambda route,request,body=source:route.fulfill(body=body,content_type='text/javascript'))
    page.goto(base+'/bake_seq?pose=/experiments/review_20260930/solver_fixes/benchmark_replay.json&avatar='+avatar+'&fps=30&ui=0',wait_until='domcontentloaded')
    page.wait_for_function('() => __BAKE_READY__ || __BAKE_ERROR__',timeout=60000)
    assert page.evaluate('() => __BAKE_ERROR__') is None
    # FBX conclui o rig antes das texturas; aguarde-as para evitar a primeira mão preta.
    page.wait_for_load_state('networkidle',timeout=60000)
    for i in range(6):
     page.evaluate('() => {globalThis.__reviewRenderEnabled=false;for(let j=0;j<40;j++)__bakeSeqStep();}')
     photo=frames[i*40]['image'];stem=Path(photo).stem
     measurement=page.evaluate('''() => {
       const T=__BAKE_THREE__, rig=__BAKE_RIG__, bones={};
       for(const [key,r]of rig.bones) bones[key]=r.bone.getWorldQuaternion(new T.Quaternion()).toArray();
       const wrist=rig.bones.get('rightHand').bone.getWorldPosition(new T.Vector3());
       globalThis.__reviewRenderEnabled=true;
       __bakeLookAt([wrist.x+.22,wrist.y+.15,wrist.z+.30],wrist.toArray());
       return {bones,wrist:wrist.toArray()};
     }''')
     image=HERE/f'{avatar}_{stem}_{version}_hand.png'
     page.locator('#canvas').screenshot(path=str(image))
     captures[(i,version)]=image
     records.append({'avatar':avatar,'version':version,'image':photo,'measurement':measurement,
       'solver_sha256':hashlib.sha256(source.encode()).hexdigest()})
    assert not errors,errors
    context.close()
    print('RENDER',avatar,version,flush=True)
   for i in range(6):
    photo=frames[i*40]['image'];stem=Path(photo).stem
    canvas=Image.new('RGB',(1380,680),'#171b23');draw=ImageDraw.Draw(canvas)
    source=ImageOps.contain(Image.open(ROOT/'src/benchmark_images/palm_orientation'/photo),(460,600))
    canvas.paste(source,(0,60));draw.text((12,20),'Foto original / NLF gravado',fill='white')
    for x,version,title in [(460,'before','Adaptador anterior'),(920,'after','Adaptador corrigido')]:
     im=ImageOps.contain(Image.open(captures[(i,version)]),(460,600));canvas.paste(im,(x,60));draw.text((x+12,20),title+' - '+avatar,fill='white')
    canvas.save(HERE/f'{avatar}_{stem}_compare.png')
  browser.close()
 (HERE/'render_ab_measurements.json').write_text(json.dumps(records,indent=2),encoding='utf-8')

if __name__=='__main__':main()
