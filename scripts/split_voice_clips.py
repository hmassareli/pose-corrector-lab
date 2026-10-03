"""Split a long voice recording into one clip per phrase (cut at pauses).

Usage: python scripts/split_voice_clips.py <audio> <out_dir> [--thr -40] [--gap 0.2] [--probe]
--probe only prints how many clips each threshold/gap would give.
"""
import argparse, json, subprocess
from pathlib import Path
import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument('audio'); ap.add_argument('out')
ap.add_argument('--thr', type=float, default=-40, help='dB below which the voice counts as silent')
ap.add_argument('--gap', type=float, default=0.2, help='min silence (s) that separates two phrases')
ap.add_argument('--pad', type=float, default=0.06, help='seconds kept before/after each phrase')
ap.add_argument('--min', type=float, default=0.15, help='drop clips shorter than this (clicks)')
ap.add_argument('--probe', action='store_true')
a = ap.parse_args()

SR, HOP = 16000, 160  # 10 ms frames
raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', a.audio, '-ac', '1', '-ar', str(SR), '-f', 'f32le', '-'], capture_output=True).stdout
x = np.frombuffer(raw, dtype=np.float32)
n = len(x) // HOP
db = 20 * np.log10(np.sqrt((x[:n * HOP].reshape(n, HOP) ** 2).mean(1)) + 1e-9)

def segments(thr, gap):
    out, start, last = [], None, None
    for k, loud in enumerate(db > thr):
        if loud:
            if start is None: start = k
            last = k
        elif start is not None and k - last >= gap * 100:
            out.append((start, last + 1)); start = None
    if start is not None: out.append((start, last + 1))
    return [(s / 100, e / 100) for s, e in out if (e - s) / 100 >= a.min]

if a.probe:
    print(f'duration {n / 100:.1f}s  dB p10/p50/p90/max: {[round(float(np.percentile(db, p)), 1) for p in (10, 50, 90, 100)]}')
    for thr in (-50, -45, -40, -35, -30):
        print(f'thr {thr}:', {g: len(segments(thr, g)) for g in (.15, .2, .25, .3, .4)})
    raise SystemExit

segs = segments(a.thr, a.gap)
out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
for old in out.glob('clip_*.wav'): old.unlink()
manifest = []
for i, (s, e) in enumerate(segs, 1):
    # Cut in the middle of the neighbouring pause so a long tail is not clipped.
    lo = max(0, s - a.pad) if i == 1 else max(s - a.pad, (segs[i - 2][1] + s) / 2)
    hi = min(n / 100, e + a.pad) if i == len(segs) else min(e + a.pad, (e + segs[i][0]) / 2)
    name = f'clip_{i:02d}.wav'
    # -ss before -i resets timestamps to 0, so the fade-out time is relative to the clip.
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{lo:.3f}', '-t', f'{hi - lo:.3f}', '-i', a.audio, '-af', 'afade=t=in:d=0.005,afade=t=out:st=%.3f:d=0.02' % (hi - lo - 0.02), str(out / name)], check=True)
    manifest.append({'file': name, 'start': round(lo, 3), 'end': round(hi, 3), 'dur': round(hi - lo, 2), 'name': None})
(out / 'manifest.json').write_text(json.dumps({'source': Path(a.audio).name, 'thr_db': a.thr, 'gap_s': a.gap, 'clips': manifest}, indent=1, ensure_ascii=False), encoding='utf-8')
print(f'{len(manifest)} clips -> {out}')
for m in manifest: print(f"{m['file']}  {m['start']:6.2f}-{m['end']:6.2f}  {m['dur']}s")
