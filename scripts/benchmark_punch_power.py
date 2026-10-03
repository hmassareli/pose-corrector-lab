"""Punch-power benchmark on a recorded webcam video.

1. Sends recorded frames to the real WebSocket NLF worker, without crop priming,
   and caches the camera-space joints next to the video.
2. Finds every fast hand movement (wrist speed peak).
3. Retains the legacy single-frame speed and offline magnitude reference tables.
4. Executes the actual current JavaScript detector with forward target projection,
   then writes a separate .runtime.json and matches the approved labels if present.

Usage: python scripts/benchmark_punch_power.py benchmarks/<video>.mp4 [body_kg]
"""
import json, sys, subprocess
from pathlib import Path
import cv2
import numpy as np

video = Path(sys.argv[1])
mass_args=[arg for arg in sys.argv[2:] if not arg.startswith('--')]
BODY_KG = float(mass_args[0]) if mass_args else 80.0
SERVER = 'ws://127.0.0.1:8781/nlf'
TARGET_HZ = 30
MASS = {'hand': .006, 'forearm': .016, 'upper': .027, 'trunk': .43, 'head': .07}
TRUNK_COUPLING, CONTACT_S, WINDOW_S, FULL_FORCE_N = .18, .015, .15, 1200
MIN_SPEED, FULL_SPEED = 1.1, 4.2  # COMBAT.minSpeed / fullPowerSpeed in boxing_core.mjs
FAST_MS = 1.2                    # wrist speed that counts as a "fast movement"

cache = video.with_suffix('.nlf.fresh.npz' if '--fresh' in sys.argv else '.nlf.npz')
if cache.exists() and '--fresh' not in sys.argv:
    z = np.load(cache); times, cam = z['times'], z['cam']
else:
    from websockets.sync.client import connect
    # The game's WebSocket path (fast TRT worker); the HTTP endpoint is ~60x slower.
    ws = connect(SERVER, max_size=None, open_timeout=120)
    ws.send('warmup'); warm=json.loads(ws.recv(timeout=120))
    if not warm.get('ok'): raise RuntimeError(warm)
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    step = max(1, round(fps / TARGET_HZ))
    times, cam, i = [], [], 0
    while True:
        ok, bgr = cap.read()
        if not ok: break
        if i % step == 0:
            h, w = bgr.shape[:2]; s = min(1, 960 / max(h, w))
            img = cv2.resize(bgr, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA)
            ok, jpg = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 82])
            ws.send(b'NLF1' + i.to_bytes(4, 'little') + jpg.tobytes())
            while True:
                d = json.loads(ws.recv(timeout=120))
                if d.get('frame_id') == i or not d.get('ok'): break
            if d.get('ok') and d.get('camera_joints'):
                times.append(i / fps)
                cam.append([[p[0], -p[1], -p[2]] for p in d['camera_joints']])  # toViewerSpace, no mirror (gameBridge)
            if len(times) % 300 == 0: print(f'  NLF {i / fps:.0f}s', flush=True)
        i += 1
    times, cam = np.array(times), np.array(cam)
    np.savez(cache, times=times, cam=cam)
print(f'{len(times)} poses, {times[-1]:.1f} s')

def slope(ts, vs):
    ts = ts - ts.mean()
    return (ts[:, None] * (vs - vs.mean(0))).sum(0) / max(1e-9, (ts ** 2).sum()) if vs.ndim > 1 else (ts * (vs - vs.mean())).sum() / max(1e-9, (ts ** 2).sum())

def win(t_end, length=WINDOW_S):
    return np.where((times > t_end - length - 1e-6) & (times <= t_end + 1e-6))[0]

# Legacy game method, retained solely as the before-change reference.
P = cam
scale = 1.72 / max(.7, P[0, 15, 1] - min(P[0, 5, 1], P[0, 6, 1]))
pose = (P - P[:, :1, :] * np.array([1, 0, 1])) * scale
old_events, armed, cooldown = [], [True, True], [0, 0]
for k in range(1, len(times)):
    dt = times[k] - times[k - 1]
    if not .008 < dt < .25: continue
    for h in (0, 1):
        reach = np.linalg.norm(pose[k, 12 + h] - pose[k, 8 + h])
        if reach < .39: armed[h] = True
        sp = np.linalg.norm(pose[k, 12 + h] - pose[k - 1, 12 + h]) / dt
        if armed[h] and reach > .47 and sp > MIN_SPEED and times[k] > cooldown[h]:
            old_events.append({'t': times[k], 'hand': h, 'power': min(1, max(0, (min(sp, 6) - MIN_SPEED) / (FULL_SPEED - MIN_SPEED)))})
            armed[h] = False; cooldown[h] = times[k] + .3

# Fast movements: wrist speed peaks (regression over ~130 ms), per hand.
moves = []
for h in (0, 1):
    W = 12 + h
    speed = np.array([np.linalg.norm(slope(times[ix], P[ix, W])) if len(ix := win(t, .13)) >= 3 else 0 for t in times])
    k = 1
    while k < len(times) - 1:
        if speed[k] >= FAST_MS and speed[k] >= speed[k - 1] and speed[k] >= speed[k + 1]:
            moves.append({'t': times[k], 'hand': h, 'peak': speed[k]}); k += int(.3 * TARGET_HZ)
        k += 1
moves.sort(key=lambda m: m['t'])

m = {k: v * BODY_KG for k, v in MASS.items()}
rows = []
for n, mv in enumerate(moves, 1):
    h = mv['hand']; S, E, W = 8 + h, 10 + h, 12 + h
    best = None
    for k in np.where((times >= mv['t'] - .25) & (times <= mv['t'] + .1))[0]:
        ix = win(times[k])
        if len(ix) < 3: continue
        ext = slope(times[ix], np.linalg.norm(P[ix, W] - P[ix, S], axis=1))
        if best is None or ext > best[0]: best = (ext, ix)
    ext, ix = best
    ts, Q = times[ix], P[ix]
    v_hand = slope(ts, Q[:, W]); v_fore = slope(ts, (Q[:, E] + Q[:, W]) / 2); v_upper = slope(ts, (Q[:, S] + Q[:, E]) / 2)
    v_trunk = slope(ts, (Q[:, 0] + (Q[:, 8] + Q[:, 9]) / 2) / 2); v_head = slope(ts, Q[:, 15])
    v_pelvis = slope(ts, Q[:, 0]); v_sh = slope(ts, Q[:, S] - Q[:, 0])
    d = v_hand / max(1e-6, np.linalg.norm(v_hand))
    along = lambda v: max(0.0, float(v @ d))
    momentum = (m['hand'] * along(v_hand) + m['forearm'] * along(v_fore) + m['upper'] * along(v_upper)
                + TRUNK_COUPLING * (m['trunk'] * along(v_trunk) + m['head'] * along(v_head)))
    pre = np.where((times >= ts[-1] - .4) & (times <= ts[-1]))[0]
    start = pre[np.argmin(np.linalg.norm(P[pre, W] - P[pre, S], axis=1))]
    reach_end = np.linalg.norm(P[ix[-1], W] - P[ix[-1], S])
    old = [e for e in old_events if e['hand'] == h and abs(e['t'] - mv['t']) <= .2]
    force = momentum / CONTACT_S
    rows.append({'n': n, 't': round(float(mv['t']), 2), 'hand': 'LR'[h], 'wristPeak_ms': round(float(mv['peak']), 2),
                 'armExt_ms': round(float(ext), 2), 'reach_cm': round(float(reach_end) * 100),
                 'travel_cm': round(float(np.linalg.norm(P[ix[-1], W] - P[start, W])) * 100),
                 'body_ms': round(along(v_sh) + along(v_pelvis), 2), 'forceN': round(force),
                 'newPct': round(min(100, 100 * force / FULL_FORCE_N)),
                 'oldPct': round(100 * max(e['power'] for e in old)) if old else None})

hdr = ['n', 't', 'hand', 'wristPeak_ms', 'armExt_ms', 'reach_cm', 'travel_cm', 'body_ms', 'forceN', 'oldPct', 'newPct']
print('| ' + ' | '.join(hdr) + ' |'); print('|' + '---|' * len(hdr))
for r in rows: print('| ' + ' | '.join('-' if r[c] is None else str(r[c]) for c in hdr) + ' |')
print(f'old detector fired {len(old_events)} times; fast movements {len(rows)}')
video.with_suffix('.fresh.power.json' if '--fresh' in sys.argv else '.power.json').write_text(json.dumps(rows, indent=1), encoding='utf-8')

# Use production JavaScript, rather than a Python imitation, for the new runtime.
reference=[]
labels=video.with_suffix('.punches.md')
if labels.exists():
    for line in labels.read_text(encoding='utf-8').splitlines():
        columns=[c.strip() for c in line.strip('|').split('|')]
        if len(columns)==8 and columns[0].isdigit():
            reference.append({'n':int(columns[0]),'t':float(columns[1].rstrip('s')),
                'hand':'L' if columns[2]=='esq' else 'R','forceN':float(columns[5].split()[0])})
runtime_input=video.with_suffix('.fresh.runtime-input.json' if '--fresh' in sys.argv else '.runtime-input.json')
runtime_output=video.with_suffix('.fresh.runtime.json' if '--fresh' in sys.argv else '.runtime.json')
runtime_input.write_text(json.dumps({'bodyKg':BODY_KG,'times':times.tolist(),'cam':cam.tolist(),'reference':reference}),encoding='utf-8')
print('\nActual HEAVY HANDS runtime (raw metres, target projection, LS150ms):',flush=True)
subprocess.run(['node',str(Path(__file__).with_name('benchmark_heavy_runtime.mjs')),str(runtime_input),str(runtime_output)],check=True)
print('Saved runtime:',runtime_output)
