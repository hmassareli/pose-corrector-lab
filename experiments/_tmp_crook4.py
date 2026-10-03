import json, numpy as np
from pathlib import Path
import sys
sys.path[:0]=['src','scripts']
from pose_lab.skeleton import smplx55_avatar_aux_json, smplx55_to_lab

def flip(p):
    # flipMpPointToViewer
    return np.array([p[0], -p[1], -p[2]], float)

def unit(v):
    n=np.linalg.norm(v); return v/n if n>1e-12 else v

meas=json.loads(Path('experiments/bone_crook/measure.json').read_text())
frames=json.loads(Path('experiments/bone_crook/frames.json').read_text())

for fm in frames:
    tag=fm['tag']; aux=fm['aux_smpl']
    # aux is still in opencv-ish (same as joints before bake flip). bake does auxFromSmpl(..., true)
    keys=['pelvis','spine1','spine2','spine3','neck']
    pts=np.array([flip(aux[k]) for k in keys])
    # normalize like posePoint roughly by shoulder width, origin shoulder mid
    lsh=flip(aux['left_shoulder']); rsh=flip(aux['right_shoulder'])
    sc=0.5*(lsh+rsh); sw=np.linalg.norm(lsh-rsh)
    ptsn=(pts-sc)/sw
    print('\n====', tag, 'frame', fm['frame'])
    print('SMPL waypoints (viewer, m-ish flipped):')
    for k,p,pn in zip(keys,pts,ptsn):
        print(f'  {k:8s} raw={np.round(p,3)}  norm={np.round(pn,3)}')
    segs=np.diff(ptsn,axis=0)
    segsn=np.array([unit(s) for s in segs])
    print('SMPL segment dirs:')
    for i,s in enumerate(segsn):
        print(f'  {keys[i]}->{keys[i+1]}: {np.round(s,3)}')
    for i in range(1,len(segsn)):
        ang=np.degrees(np.arccos(np.clip(segsn[i-1]@segsn[i],-1,1)))
        print(f'  turn at {keys[i]}: {ang:.1f}°')

    # solver chain parameterization with 3 bones, 4 segs
    waypoints=ptsn
    seg=len(waypoints)-1; count=3
    def chainPoint(u):
        s=min(seg-1,int(np.floor(u))); f=u-s
        return waypoints[s]*(1-f)+waypoints[s+1]*f
    names=['spine','spine1','spine2']
    print('Solver target dirs (full-chain mapping):')
    tdirs=[]
    for i,n in enumerate(names):
        a=chainPoint((i*seg)/count); b=chainPoint(((i+1)*seg)/count)
        d=unit(b-a); tdirs.append(d)
        print(f'  {n}: {np.round(d,3)}  a={np.round(a,3)} b={np.round(b,3)}')
    for i in range(1,len(tdirs)):
        ang=np.degrees(np.arccos(np.clip(tdirs[i-1]@tdirs[i],-1,1)))
        print(f'  target kink {names[i-1]}->{names[i]}: {ang:.1f}°')

    # hips torso target = -hipCenter in pose space
    lh=flip(aux['left_hip']); rh=flip(aux['right_hip'])
    hipc=0.5*(lh+rh); hipcn=(hipc-sc)/sw
    torso=unit(-hipcn)
    print('hips torso target ( -hipCenter ):', np.round(torso,3))
    # first spine target vs hips
    ang=np.degrees(np.arccos(np.clip(torso@tdirs[0],-1,1)))
    print(f'hips_target vs spine_target kink: {ang:.1f}°')

    # avatar measured dirs
    b=meas[tag]['bones']
    print('Avatar live dirs:')
    for n in ['hips']+names+['neck']:
        print(f'  {n:8s} {b[n]["liveDir"]}  bind={b[n]["bindDeg"]}')
    print('Avatar aimKinks', meas[tag]['aimKinks'])
