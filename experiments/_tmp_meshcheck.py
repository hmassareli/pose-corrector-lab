import numpy as np

d=np.load('experiments/nlf_fit_webcam1/fit_smplx.npz')
names=[str(s) for s in d['smplx55_names']]
idx={n:i for i,n in enumerate(names)}
SPINE=['pelvis','spine1','spine2','spine3','neck']

for t in [37, 65, 1052]:
    verts=d['verts'][t].astype(np.float64)  # (10475,3) mm opencv
    joints=d['fit_joints'][t].astype(np.float64)
    jp=joints[[idx[k] for k in SPINE]]

    print('='*70)
    print('FRAME', t)

    # 1) consistency: distance from each spine joint to nearest mesh vertex
    for k,p in zip(SPINE,jp):
        dist=np.linalg.norm(verts-p,axis=1).min()
        print(f'  joint {k:8s} -> mesh mais proximo: {dist:6.1f} mm', '(dentro do corpo)' if dist<60 else '*** FORA/LONGE ***')

    # 2) mesh centerline: slice the torso horizontally at each joint height
    #    torso = verts with |x - joint.x| < 150mm laterally, and y within +-40mm of joint height
    print('  mesh centerline vs joints (x,z em mm, opencv):')
    for k,p in zip(SPINE,jp):
        y0=p[1]
        slab=verts[np.abs(verts[:,1]-y0)<40]
        # keep only torso: near the joint in x and z (exclude arms sticking out)
        cx, cz = p[0], p[2]
        near=slab[(np.abs(slab[:,0]-cx)<120) & (np.abs(slab[:,2]-cz)<120)]
        if len(near)<20:
            print(f'    {k:8s} slab vazio'); continue
        cen=near.mean(axis=0)
        dx, dz = cen[0]-p[0], cen[2]-p[2]
        print(f'    {k:8s} mesh_centroid=({cen[0]:7.1f},{cen[2]:7.1f})  joint=({p[0]:7.1f},{p[2]:7.1f})  delta=({dx:+5.1f},{dz:+5.1f}) mm')

    # 3) mesh spine polyline curvature (centroids) vs joint polyline
    cents=[]
    for k,p in zip(SPINE,jp):
        y0=p[1]
        slab=verts[np.abs(verts[:,1]-y0)<40]
        near=slab[(np.abs(slab[:,0]-p[0])<120) & (np.abs(slab[:,2]-p[2])<120)]
        cents.append(near.mean(axis=0) if len(near)>=20 else p)
    cents=np.array(cents)
    def turns(pts):
        segs=np.diff(pts,axis=0)
        segsn=segs/np.linalg.norm(segs,axis=1,keepdims=True)
        return [float(np.degrees(np.arccos(np.clip(segsn[i-1]@segsn[i],-1,1)))) for i in range(1,len(segsn))]
    print('  turns JUNTAS:', [round(a,1) for a in turns(jp)])
    print('  turns MESH  :', [round(a,1) for a in turns(cents)])
