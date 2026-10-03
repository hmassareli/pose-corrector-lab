"""Galeria local de rótulos visuais e capturas reais do /live."""
from pathlib import Path
from html import escape
import json
from PIL import Image,ImageOps

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'experiments/review_20260930/palm_live'
def main():
 labels=json.loads((ROOT/'src/benchmark_images/palm_orientation/labels.json').read_text(encoding='utf-8'))
 folder=OUT/'fighter-web_settled'
 metrics=json.loads((folder/'palm_metrics.json').read_text(encoding='utf-8'))
 cells=[];cards=[]
 for sample in labels['samples']:
  stem=Path(sample['image']).stem
  rows=[r for r in metrics['results'] if r['image']==sample['image']]
  desc=' · '.join(('Direita' if r['source_hand']=='right' else 'Esquerda')+': esperado '+r['expected']+' | NLF '+r['raw_nlf']['majority']+' | avatar '+r['rendered_geometry']['majority'] for r in rows)
  cards.append(f'<article><h2>{escape(stem)}</h2><p>{escape(desc)}</p><a href="fighter-web_settled/{stem}_compare.png"><img src="fighter-web_settled/{stem}_compare.png" alt="Foto e avatar: {escape(stem)}"></a><p>Confiança do rótulo: {sample["label_confidence"]}. Anexos {sample["source_attachment_numbers"]}.</p></article>')
  cells.append(ImageOps.contain(Image.open(folder/(stem+'_compare.png')),(750,291)))
 contact=Image.new('RGB',(1500,873),'#171b23')
 for i,cell in enumerate(cells): contact.paste(cell,((i%2)*750,(i//2)*291))
 contact.save(OUT/'comparacoes.png')
 html='''<!doctype html><html lang="pt-BR"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Benchmark de palmas · NLF live</title><style>body{max-width:1500px;margin:32px auto;padding:0 20px;background:#141923;color:#edf2fa;font:16px/1.5 system-ui}h1{font-size:32px}h2{font-size:18px;overflow-wrap:anywhere}article{background:#202835;padding:16px;margin:22px 0;border-radius:10px}img{display:block;width:100%;height:auto}a{color:#85c7ff}p{color:#c8d5e5}</style><h1>Benchmark de orientação da palma</h1><p>18 anexos → 6 fotos únicas, rotuladas visualmente antes da inferência. Originais preservados em 4K. Fotos mantidas por 6 segundos na câmera simulada de 960×540, pelo caminho real /live → WebSocket → NLF-S (SMPL-X55) → Fighter Web. Capturas depois de 60 segundos de aquecimento na mesma conexão. Foto espelhada para coincidir com o modo selfie.</p><p>As classes usam o eixo dominante da normal da palma; não são uma medição de ângulo 3D ou de acurácia geral. A geometria do avatar é medida nas posições reais dos ossos dos dedos, sem usar os eixos-alvo do solver. Punhos fechados têm rótulos de confiança moderada. Cortes entre fotos não representam movimento humano.</p>'''+''.join(cards)+'</html>'
 (OUT/'galeria.html').write_text(html,encoding='utf-8')
 print(OUT/'galeria.html')

if __name__=='__main__':main()
