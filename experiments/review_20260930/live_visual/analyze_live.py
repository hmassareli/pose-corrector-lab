from pathlib import Path
import json, numpy as np
from PIL import Image, ImageDraw, ImageOps

HERE=Path(__file__).resolve().parent
def angle(a,b):
    a=np.asarray(a); b=np.asarray(b)
    return float(np.degrees(np.arccos(np.clip(np.dot(a,b)/(np.linalg.norm(a)*np.linalg.norm(b)),-1,1))))
def qangle(a,b):
    a=np.asarray(a);b=np.asarray(b)
    return float(np.degrees(2*np.arccos(np.clip(abs(np.dot(a,b))/(np.linalg.norm(a)*np.linalg.norm(b)),0,1))))
def stats(v):
    return {k:round(float(val),3) for k,val in zip(['p50','p95','max'],np.percentile(v,[50,95,100]))} if len(v) else {}

for folder in [p for p in HERE.iterdir() if p.is_dir() and (p/'summary.json').exists()]:
    s=json.loads((folder/'summary.json').read_text())
    frames=json.loads((folder/'frames.json').read_text())
    metrics=[]
    for i,c in enumerate(s['captures']):
        # Settled holds: discard the first 2s after each abrupt photo transition.
        fs=[f for f in frames if i*6+2 <= f['videoTime'] <= i*6+5.8]
        out={'image':c['image'],'samples':len(fs),'jumps':{},'direction_error_degrees':{}}
        for key in ['leftArm','rightArm','leftForeArm','rightForeArm','leftHand','rightHand']:
            out['jumps'][key]=stats([qangle(a['bones'][key]['q'],b['bones'][key]['q']) for a,b in zip(fs,fs[1:])])
        for side,sh,el,wr in [('left',8,10,12),('right',9,11,13)]:
            for name,begin,end,a,b in [('upper',side+'Arm',side+'ForeArm',sh,el),('fore',side+'ForeArm',side+'Hand',el,wr)]:
                vals=[]
                for f in fs:
                    source=np.array(f['view'][b])-np.array(f['view'][a])
                    actual=np.array(f['bones'][end]['p'])-np.array(f['bones'][begin]['p'])
                    vals.append(angle(source,actual))
                out['direction_error_degrees'][side+'_'+name]=stats(vals)
        metrics.append(out)
    settled=[f for f in frames if 2 <= f['videoTime']%6 <=5.8]
    result={'frames':len(frames),'elapsed_ms':round(frames[-1]['t']-frames[0]['t'],1),
            'delivered_fps':round((len(frames)-1)*1000/(frames[-1]['t']-frames[0]['t']),2),
            'transport_types':sorted(set(str(f['data'].get('type')) for f in frames)),
            'server_ms':stats([f['data']['ms'] for f in settled]),
            'round_trip_ms':stats([f['roundTrip'] for f in settled]),'holds':metrics}
    (folder/'metrics.json').write_text(json.dumps(result,indent=2))
    print(folder.name,result['delivered_fps'],result['server_ms'],result['round_trip_ms'])
    for m in metrics:
        print(m['image'][13:21],m['direction_error_degrees'], 'hand jumps',m['jumps']['leftHand'],m['jumps']['rightHand'])
    cells=[]
    for i,c in enumerate(s['captures']):
        pic=ImageOps.contain(Image.open(folder/(Path(c['image']).stem+'_compare.png')),(750,291))
        cells.append(pic)
    contact=Image.new('RGB',(1500,291*7),(23,27,35))
    for i,pic in enumerate(cells):contact.paste(pic,((i%2)*750,(i//2)*291))
    contact.save(folder/'all_benchmarks.png')
