"""Prepare recorded MediaPipe body + head/palm input for the avatar viewer."""
import json
from pathlib import Path
import numpy as np

root = Path(__file__).resolve().parents[1]
clip = root / 'data/mediapipe/burn_500_shots__shot_000__person_009'
joints = np.load(clip / 'joints3d.npy')
landmarks = np.load(clip / 'landmarks33_world.npy')
frames = [{'joints': j.tolist(), 'aux_pose33': a[:, :3].tolist()}
          for j, a in zip(joints[:180], landmarks[:180])]
out = root / 'experiments/bake_top/prism_mp_replay.json'
out.write_text(json.dumps(frames), encoding='utf-8')
print(out, len(frames))
