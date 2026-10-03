import re
from pathlib import Path
root = Path('.')
# keys present in fit_smplx.npz
keys = ['verts','pose','betas','trans','fit_joints','x55','ok','smplx55_names']
# scan py/js/html files in repo (exclude huge outputs)
files = [p for p in root.rglob('*') if p.suffix.lower() in {'.py','.js','.html','.md'} and 'node_modules' not in p.parts and '.git' not in p.parts]
usage = {k: [] for k in keys}
patterns = {k: [re.compile(rf"\b{k}\b"), re.compile(rf"\[\s*['\"]{k}['\"]\s*\]")] for k in keys}
for p in files:
    try:
        t = p.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        continue
    rel = p.as_posix()
    if rel.startswith('./'): rel = rel[2:]
    for k, pats in patterns.items():
        if any(pt.search(t) for pt in pats):
            usage[k].append(rel)

print('FIT key usage by file count:')
for k in keys:
    print(f"{k:12} {len(usage[k])}")

print('\nTop relevant files (viewer + scripts) per key:')
for k in keys:
    rel = [f for f in usage[k] if f.startswith('viewer/') or f.startswith('scripts/')]
    print(f"\n[{k}] {len(rel)} relevant")
    for f in rel[:12]:
        print(' ', f)

# quick live path evidence: where /api/nlf_pose payload fields are assembled
sp = Path('scripts/serve_lab.py').read_text(encoding='utf-8', errors='ignore')
for token in ['aux_smpl','smplx55','surface1024','fit_joints','pose','betas','trans','ok']:
    idx = sp.find(token)
    print(f"token {token:10} first_at", idx)
