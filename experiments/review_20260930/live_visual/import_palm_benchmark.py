"""Importa anexos originais e registra rótulos visuais independentes do NLF."""
from pathlib import Path
import hashlib, json, shutil
from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
DEST = ROOT / 'src/benchmark_images/palm_orientation'
IDS = '''b915fea5-df81-48d5-bc05-c9a54b673fd3
e631767c-85a1-4ed7-bd8a-328c8c89996a
e5258ba4-4040-4efe-8cc0-dd7542676363
77e1545c-50e2-4b36-9448-9d4af996c12c
57a49d34-5dd1-4488-a5eb-afa1c7a5682e
32264f68-5b00-407e-b059-e74d5581d858
7b671ef3-aae8-4327-8ba0-9cb84871238f
9a427779-5d16-46f4-8e83-89e5577bcc19
e743aeae-681b-4f26-b987-fe6a4ad74723
82b0ac7c-8f3a-4991-a202-d3d794ab1fb0
dd7a47f7-2ed2-4102-8bc3-3628125d51b5
ce53703a-313d-415b-ad09-5be9afff68a5
a4721e72-6806-4549-b890-ffba396bc244
2c7baed8-5235-455f-805e-333bae644adb
b1278301-ef1d-4e09-b2df-801bf16368ee
20262d4f-7fca-476c-9420-3c1997093e39
ebf2cfb6-9736-4455-8c88-cf7bd69684c6
afb44223-b186-4b8c-9e3a-9fedf051a043'''.splitlines()
CASES = [
 ('01_maos_abertas_ambas_palmas_cima.jpg', 'cima', 'aberta', ['right','left']),
 ('02_maos_abertas_ambas_palmas_lado_interno.jpg', 'lado_interno', 'aberta', ['right','left']),
 ('03_punho_direito_fechado_palma_cima_polegar_estendido.jpg', 'cima', 'fechada_polegar_estendido', ['right']),
 ('04_maos_abertas_ambas_palmas_baixo.jpg', 'baixo', 'aberta', ['right','left']),
 ('05_punho_direito_fechado_palma_lado_interno.jpg', 'lado_interno', 'fechada', ['right']),
 ('06_punho_direito_fechado_palma_baixo.jpg', 'baixo', 'fechada', ['right']),
]

def main():
 DEST.mkdir(parents=True, exist_ok=True)
 samples=[]; by_pixels={}; attachments=[]
 for n,ident in enumerate(IDS,1):
  source=Path('C:/Users/Henrique/AppData/Local/Temp')/f'codex-clipboard-{ident}.jpg'
  raw=source.read_bytes(); sha=hashlib.sha256(raw).hexdigest()
  with Image.open(source) as im:
   rgb=im.convert('RGB'); pixels=hashlib.sha256(rgb.tobytes()).hexdigest(); size=list(im.size)
  if pixels not in by_pixels:
   case=(n-1)%6; filename,direction,state,hands=CASES[case]
   if (DEST/filename).exists() and (DEST/filename).read_bytes()!=raw:
    raise RuntimeError(f'Destino existente diferente: {filename}')
   shutil.copy2(source, DEST/filename)
   sample={'id':Path(filename).stem,'image':filename,'sha256':sha,'decoded_rgb_sha256':pixels,'size':size,
    'label_source':'inspecao_visual_dos_anexos_antes_da_inferencia',
    'label_confidence':'alta' if state=='aberta' else 'moderada',
    'arms':'ambos_para_frente' if len(hands)==2 else 'direito_para_frente_esquerdo_relaxado',
    'hands':{hand:{'palm_direction':direction,'hand_state':state,'evaluate':True} for hand in hands},
    'source_attachment_numbers':[],
    'notes':'Normal da palma aproximada; não é medição de ângulo 3D. Palma de punho fechado inferida pelo polegar e pelos dedos.'}
   if len(hands)==1: sample['hands']['left']={'evaluate':False,'reason':'braco_relaxado_fora_do_alvo_do_teste'}
   by_pixels[pixels]=sample; samples.append(sample)
  sample=by_pixels[pixels]; sample['source_attachment_numbers'].append(n)
  attachments.append({'number':n,'original_name':source.name,'sha256':sha,'canonical_image':sample['image'],
   'deduplication':'primeiro_exemplar' if sample['source_attachment_numbers']==[n] else 'pixels_RGB_identicos'})
 manifest={'schema_version':1,'created':'2026-09-30','uploaded_count':len(IDS),'unique_count':len(samples),
  'conventions':{'hand_side':'lado anatomico da pessoa; direita aparece à esquerda na foto original',
   'image_mirrored':False,'palm_direction':'direcao da normal da palma, não a direção dos dedos',
   'cima':'em direcao ao teto','baixo':'em direcao ao chao','lado_interno':'em direcao ao plano mediano do corpo; palmas uma para a outra quando ambas estendidas',
   'labels_consumed_by_model':False,'angular_ground_truth':False,
   'duplicates':'mesmos pixels RGB contam uma vez; não são novas amostras ou sequencia temporal'},
  'samples':samples,'attachments':attachments}
 (DEST/'labels.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({'uploaded':len(IDS),'unique':len(samples),'groups':{s['image']:s['source_attachment_numbers'] for s in samples}},indent=2))

if __name__=='__main__': main()
