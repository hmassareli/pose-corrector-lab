"""Bake a shadowboxing video into a seamless lobby loop (viewer/lobby_shadowbox.json).

Usage: python scripts/build_lobby_loop.py --video clip.mp4
"""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import torch

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB / 'scripts'))
sys.path.insert(0, str(LAB / 'src'))
from nlf_bbox_track import YoloNanoPerson
from nlf_fast_path import get_joint_weights, load_nlf, estimate_joints24
from pose_lab.skeleton import smplx55_avatar_aux_json, smplx55_to_lab


def capture(video, max_side=960):
    model = load_nlf(LAB / 'data/models/nlf/nlf_s_multi_0.2.2.torchscript')
    weights, _ = get_joint_weights(model, 'smplx55')
    yolo = YoloNanoPerson(device='cuda', imgsz=640)
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS)
    poses, box = [], None
    while True:
        ok, bgr = cap.read()
        if not ok:
            break
        s = max_side / max(bgr.shape[:2])
        rgb = cv2.cvtColor(cv2.resize(bgr, None, fx=s, fy=s, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
        det = yolo.detect_xywh(rgb)
        if det is not None:
            x, y, w, h = det
            cx, cy, side = x + w / 2, y + h / 2, max(w, h) * 1.2
            new = np.array([cx - side / 2, cy - side / 2, side, side])
            box = new if box is None else .6 * box + .4 * new
        if box is None:
            continue
        pred = estimate_joints24(model, rgb, weights, box=torch.tensor([box], dtype=torch.float32, device='cuda'), num_aug=1)
        if pred is not None and np.isfinite(pred).all():
            poses.append(pred / 1000)
    cap.release()
    return fps, np.array(poses)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--video', type=Path, required=True)
    ap.add_argument('--blend', type=int, default=12, help='frames crossfaded at the loop seam')
    ap.add_argument('--teacher', type=Path, help='gvhmr.npz from wsl_teacher_one_video.sh (gravity alignment)')
    args = ap.parse_args()
    cache = LAB / 'experiments' / f'lobby_nlf_{args.video.stem[:40]}.npz'
    if cache.exists():
        raw = np.load(cache)['x55']
    else:
        _, raw = capture(args.video)
        np.savez_compressed(cache, x55=raw)
    fps = cv2.VideoCapture(str(args.video)).get(cv2.CAP_PROP_FPS)
    if args.teacher:
        from scipy.spatial.transform import Rotation
        t = np.load(args.teacher)
        # Static camera: one camera->gravity rotation, averaged over the clip.
        r = Rotation.from_rotvec(t['global_orient']) * Rotation.from_rotvec(t['incam_orient']).inv()
        up = r.mean().as_matrix()
        x = (raw - raw[:, :1]) @ up.T
    else:
        x = (raw - raw[:, :1]) * np.array([1, -1, -1])
    across = np.median(x[:, 1] - x[:, 2], axis=0)
    angle = np.arctan2(-across[2], across[0])
    c, s = np.cos(-angle), np.sin(-angle)
    x = x @ np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]]).T
    # Level the stance: a residual roll leaves one foot hovering on the canvas.
    d = np.median(x[:, 7] - x[:, 8], axis=0)
    roll = -np.arctan2(d[1], d[0])
    cr, sr = np.cos(roll), np.sin(roll)
    x = x @ np.array([[cr, -sr, 0], [sr, cr, 0], [0, 0, 1]]).T
    x *= .5 / np.median(x[:, 12, 1])
    x[1:-1] = .2 * x[:-2] + .6 * x[1:-1] + .2 * x[2:]
    x[:, :, 1] += .94
    # Crossfade the tail into the head so the loop has no visible jump.
    n = args.blend
    w = np.linspace(0, 1, n)[:, None, None]
    x[:n] = w * x[:n] + (1 - w) * x[-n:]
    x = x[:-n]
    frames = [{'pose': np.round(smplx55_to_lab(j), 5).tolist(), 'aux': smplx55_avatar_aux_json(np.round(j, 5))} for j in x]
    target = LAB / 'viewer/lobby_shadowbox.json'
    target.write_text(json.dumps({'version': 1, 'source': args.video.name, 'fps': fps, 'frames': frames}, separators=(',', ':')), encoding='utf-8')
    print(f'{len(frames)} frames @ {fps:.1f} fps -> {target}', flush=True)


if __name__ == '__main__':
    main()
