"""Bake the supplied training video into reusable, pelvis-relative boxing poses.

Uses the existing NLF TorchScript model offline with a fixed person crop, avoiding
the live session's sticky detector state. Raw inference is cached for recutting.
"""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import torch

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB / 'src'))
from nlf_fast_path import load_nlf, get_joint_weights, estimate_joints24
from pose_lab.skeleton import smplx55_to_lab, smplx55_avatar_aux_json


STRIKES = [
    ('hook_right', 'Cruzado direito', 1, 8.02, 8.95, 8.46),
    ('jab_left', 'Jab esquerdo', 0, 12.55, 13.18, 12.92),
    ('straight_right', 'Direto direito', 1, 14.48, 15.12, 14.78),
    ('hook_left', 'Cruzado esquerdo', 0, 21.50, 22.23, 21.91),
]


def capture(video, cache, refine=False):
    model = load_nlf(LAB / 'data/models/nlf/nlf_s_multi_0.2.2.torchscript')
    weights, _ = get_joint_weights(model, 'smplx55')
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS)
    box = torch.tensor([[260., 0., 440., 540.]], device='cuda')
    if refine:
        previous = np.load(cache)
        times, poses = previous['times'].tolist(), list(previous['x55'])
    else:
        times, poses = [], []
    existing = {round(t * fps) for t in times}
    frame = 0
    while True:
        ok, bgr = cap.read()
        if not ok:
            break
        t = frame / fps
        frame += 1
        if t < 3 or t > 35:
            continue
        if refine and ((frame - 1) % 2 == 0 or not any(a <= t <= b for _, _, _, a, b, _ in STRIKES)):
            continue
        if frame - 1 in existing:
            continue
        if not refine and (frame - 1) % 2:
            continue
        rgb = cv2.cvtColor(cv2.resize(bgr, (960, 540)), cv2.COLOR_BGR2RGB)
        pred = estimate_joints24(model, rgb, weights, box=box, num_aug=1)
        if pred is None or not np.isfinite(pred).all():
            raise RuntimeError(f'Invalid capture at {t:.3f}s')
        times.append(t)
        poses.append(pred / 1000)
        if len(times) % 90 == 0:
            print(f'Captured {t:.1f}s ({len(times)} frames)', flush=True)
    cap.release()
    order = np.argsort(times)
    np.savez_compressed(cache, times=np.array(times)[order], x55=np.array(poses)[order])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--video', type=Path, required=True)
    ap.add_argument('--capture-only', action='store_true')
    ap.add_argument('--refine', action='store_true')
    args = ap.parse_args()
    out = LAB / 'experiments/sparring_capture_20261002'
    out.mkdir(parents=True, exist_ok=True)
    cache = out / 'raw.npz'
    if not cache.exists():
        capture(args.video, cache)
    if args.refine:
        capture(args.video, cache, refine=True)
    if args.capture_only:
        return
    data = np.load(cache)
    times, raw = data['times'], data['x55']
    x = (raw - raw[:, :1]) * np.array([1, -1, -1])
    # A fixed heading preserves the real torso rotation throughout each strike.
    across = np.median(x[times < 5, 1] - x[times < 5, 2], axis=0)
    angle = np.arctan2(-across[2], across[0])
    c, s = np.cos(-angle), np.sin(-angle)
    rot = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    x = x @ rot.T
    scale = .5 / np.median(x[:, 12, 1])
    x *= scale
    # Symmetric three-tap smoothing keeps peaks; never filter the attack to a sine.
    x[1:-1] = .2*x[:-2] + .6*x[1:-1] + .2*x[2:]
    x[:, :, 1] += .94
    frames = []
    for j in x:
        frames.append({'pose': np.round(smplx55_to_lab(j), 5).tolist(),
                       'aux': smplx55_avatar_aux_json(np.round(j, 5))})
    (out / 'frames.json').write_text(json.dumps({'times': times.tolist(), 'frames': frames}), encoding='utf-8')
    guard = frames[int(np.argmin(abs(times - 5.2)))]
    clips = []
    for id, label, hand, start, end, peak in STRIKES:
        indices = np.where((times >= start) & (times <= end))[0]
        tt = times[indices]
        fps = 1 / np.median(np.diff(tt))
        joints = np.array([frames[i]['pose'] for i in indices])
        speed = np.linalg.norm(np.diff(joints[:, 12+hand], axis=0), axis=1)*fps
        launch = max(.12, peak - tt[0] - .16)
        clips.append(dict(id=id, label=label, hand=hand, fps=float(fps),
                          duration=float(tt[-1]-tt[0]), launch=float(launch),
                          speed=float(np.clip(np.percentile(speed, 90), 1.1, 6)),
                          sourceRange=[float(tt[0]), float(tt[-1])],
                          frames=[frames[i] for i in indices]))
        import subprocess
        subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-ss', str(tt[0]), '-i', str(args.video),
                        '-t', str(tt[-1]-tt[0]), '-an', '-c:v', 'libx264', '-crf', '20',
                        str(out / (id+'.mp4'))], check=True)
    target = LAB / 'viewer/sparring_mocap.json'
    target.write_text(json.dumps(dict(version=1, source=args.video.name, guard=guard, clips=clips), separators=(',', ':')), encoding='utf-8')
    (out / 'manifest.json').write_text(json.dumps([ {k:v for k,v in c.items() if k!='frames'} for c in clips], indent=2), encoding='utf-8')
    print(f'Baked {len(frames)} frames; scale={scale:.3f}', flush=True)


if __name__ == '__main__':
    main()
