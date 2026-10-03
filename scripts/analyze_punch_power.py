"""Offline punch-power audit on a CORNER debug recording (timeline.ndjson).

For every hit the player landed on the sparring partner, compares the game's
current power (single-frame wrist speed) with a physics estimate built from the
same NLF camera-space joints: segment momentum along the punch direction with
body-segment masses (de Leva 1996), the trunk/head coupled at a fixed fraction
(effective mass), and force = momentum / contact time.

Usage: python scripts/analyze_punch_power.py <recording_dir> [body_kg]
"""
import json, sys, math, bisect, statistics as st
from pathlib import Path

rec = Path(sys.argv[1])
BODY_KG = float(sys.argv[2]) if len(sys.argv) > 2 else 80.0
MASS = {'hand': .006, 'forearm': .016, 'upper': .027, 'trunk': .43, 'head': .07}
TRUNK_COUPLING = .18   # fraction of trunk/head mass behind a punch (effective mass)
CONTACT_S = .015       # glove contact time used to turn momentum into force
WINDOW_S = .15         # slope window for velocities

poses, hits = [], []
last_start = None
with open(rec / 'timeline.ndjson', encoding='utf-8') as f:
    for line in f:
        if '"type":"pose"' not in line[:40] and '"type":"frame"' not in line[:40]:
            continue
        d = json.loads(line)
        if d['type'] == 'pose':
            cam = d['input'].get('cameraPose')
            if cam and len(cam) == 16:
                poses.append((d['tMs'] / 1000, cam))
        else:
            r = d['fighters'][1].get('reaction')
            if r and r.get('start') != last_start:
                last_start = r.get('start')
                hits.append({'t': d['tMs'] / 1000, 'kind': r.get('kind'), 'old': r.get('power')})

times = [t for t, _ in poses]
sub = lambda a, b: [a[i] - b[i] for i in range(3)]
add = lambda a, b: [a[i] + b[i] for i in range(3)]
mid = lambda a, b: [(a[i] + b[i]) / 2 for i in range(3)]
dot = lambda a, b: sum(a[i] * b[i] for i in range(3))
norm = lambda a: math.sqrt(dot(a, a))

def slope(ts, vs):
    """Least-squares slope: velocity that one noisy frame cannot spike."""
    if len(ts) < 3: return None
    mt = st.mean(ts)
    den = sum((t - mt) ** 2 for t in ts)
    if den <= 0: return None
    if isinstance(vs[0], list):
        return [sum((t - mt) * v[i] for t, v in zip(ts, vs)) / den for i in range(3)]
    mv = st.mean(vs)
    return sum((t - mt) * (v - mv) for t, v in zip(ts, vs)) / den

def window(t0, t1):
    i, j = bisect.bisect_left(times, t0), bisect.bisect_right(times, t1)
    return poses[i:j]

rows = []
for h in hits:
    # NLF runs behind the game frame that registered the hit; search the 450 ms before it.
    span = window(h['t'] - .45, h['t'] + .05)
    if len(span) < 6: continue
    best = None
    for side in (0, 1):
        S, E, W = 8 + side, 10 + side, 12 + side
        # Peak arm-extension slope over sliding windows.
        for k in range(len(span)):
            win = [p for p in span if span[k][0] - WINDOW_S <= p[0] <= span[k][0]]
            if len(win) < 3: continue
            ts = [p[0] for p in win]
            ext = slope(ts, [norm(sub(p[1][W], p[1][S])) for p in win])
            if ext is None: continue
            if not best or ext > best['ext']:
                best = {'side': side, 'ext': ext, 'win': win, 'k': k}
    if not best: continue
    side, win = best['side'], best['win']
    S, E, W = 8 + side, 10 + side, 12 + side
    ts = [p[0] for p in win]
    vel = lambda f: slope(ts, [f(p[1]) for p in win])
    v_hand = vel(lambda P: P[W]); v_fore = vel(lambda P: mid(P[E], P[W])); v_upper = vel(lambda P: mid(P[S], P[E]))
    v_trunk = vel(lambda P: mid(P[0], mid(P[8], P[9]))); v_head = vel(lambda P: P[15])
    v_pelvis = vel(lambda P: P[0]); v_shoulder_rel = vel(lambda P: sub(P[S], P[0]))
    direction = v_hand if norm(v_hand) > 1e-6 else [0, 0, 1]
    dn = norm(direction); direction = [c / dn for c in direction]
    along = lambda v: max(0.0, dot(v, direction))
    # Travel: wrist path from its closest-to-shoulder point in the last 400 ms to the peak.
    pre = window(win[-1][0] - .4, win[-1][0])
    start = min(pre, key=lambda p: norm(sub(p[1][W], p[1][S])))
    travel = norm(sub(win[-1][1][W], start[1][W]))
    m = {k: v * BODY_KG for k, v in MASS.items()}
    momentum = (m['hand'] * along(v_hand) + m['forearm'] * along(v_fore) + m['upper'] * along(v_upper)
                + TRUNK_COUPLING * (m['trunk'] * along(v_trunk) + m['head'] * along(v_head)))
    eff_mass = m['hand'] + m['forearm'] + m['upper'] + TRUNK_COUPLING * (m['trunk'] + m['head'])
    rows.append({'t': round(h['t'], 1), 'kind': h['kind'], 'oldPower': h['old'], 'hand': 'LR'[side],
                 'armExt_ms': round(best['ext'], 2), 'shoulderDrive_ms': round(along(v_shoulder_rel), 2),
                 'stepIn_ms': round(along(v_pelvis), 2), 'gloveSpeed_ms': round(norm(v_hand), 2),
                 'travel_cm': round(travel * 100), 'momentum': round(momentum, 1),
                 'forceN': round(momentum / CONTACT_S), 'effMassKg': round(eff_mass, 1)})

print(f'{len(poses)} poses ({len(poses)/(times[-1]-times[0]):.1f} Hz), {len(hits)} hits on sparring, {len(rows)} analysed')
hdr = ['t', 'kind', 'oldPower', 'hand', 'armExt_ms', 'shoulderDrive_ms', 'stepIn_ms', 'gloveSpeed_ms', 'travel_cm', 'forceN']
print(' '.join(f'{h:>15}' for h in hdr))
for r in rows: print(' '.join(f'{str(r[h]):>15}' for h in hdr))
old = [r['oldPower'] for r in rows if r['oldPower'] is not None]
print('oldPower: share >= 0.95 ->', round(sum(o >= .95 for o in old) / max(1, len(old)), 2))
for k in ('armExt_ms', 'travel_cm', 'forceN'):
    v = [r[k] for r in rows]
    print(k, 'p10/p50/p90 =', [round(st.quantiles(v, n=10)[i], 2) for i in (0, 4, 8)] if len(v) >= 10 else v)
susp = [r for r in rows if (r['oldPower'] or 0) >= .8 and r['armExt_ms'] < .6 and r['travel_cm'] < 12]
print('old power >= 0.8 but arm barely extends (<0.6 m/s) and travels < 12 cm:', len(susp), 'of', len(rows))
(rec / 'punch_power_audit.json').write_text(json.dumps(rows, indent=1), encoding='utf-8')
