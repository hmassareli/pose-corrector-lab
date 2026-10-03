import json
import struct
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation

for name in ['boxer_prism31_rig.glb', 'boxeador_mixamo_trellis.glb']:
    b = (Path(__file__).resolve().parents[1] / 'assets' / name).read_bytes()
    j = json.loads(b[20:20 + struct.unpack_from('<I', b, 12)[0]])
    parents = {c: i for i, n in enumerate(j['nodes']) for c in n.get('children', [])}
    cache = {}
    def world(i):
        if i not in cache:
            n = j['nodes'][i]
            m = np.eye(4)
            m[:3, :3] = Rotation.from_quat(n.get('rotation', [0, 0, 0, 1])).as_matrix() @ np.diag(n.get('scale', [1, 1, 1]))
            m[:3, 3] = n.get('translation', [0, 0, 0])
            cache[i] = world(parents[i]) @ m if i in parents else m
        return cache[i]
    print(name)
    for i, n in enumerate(j['nodes']):
        if n.get('name', '').split(':')[-1].removeprefix('mixamorig') in ['Hips', 'LeftUpLeg', 'RightUpLeg', 'LeftArm', 'RightArm', 'Head']:
            print(n['name'], world(i)[:3, 3].round(3).tolist())
