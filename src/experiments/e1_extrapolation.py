"""E1b (real OGW): temperature-extrapolation behaviour of OBS+BSS on HEALTHY
records. Baseline pool <=40C. For healthy records at >40C, the compensated
DI should stay low if compensation extrapolates; its rise quantifies the
false-alarm pressure that event-structure discrimination must avoid.
Streams records (low memory)."""
import sys, os, json, time
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from src.data.ogw_loader import OGWSetZip
from src.methods.baseline_fast import stretch_batch

def di_record(x, Bp, alphas):
    best = np.inf
    xx = max(float(np.dot(x, x)), 1e-9)
    for a in alphas:
        S = stretch_batch(Bp, a)
        R = S - x[None, :]
        e = np.einsum('ij,ij->i', R, R)
        m = float(e.min())
        if m < best: best = m
    return best / xx

freq = 100
ud = OGWSetZip('OGW_CFRP_Temperature_udam.zip')
T = ud.temperatures()
alphas = np.linspace(0.995, 1.005, 9)
pool_idx = np.where(T <= 40.0)[0][::8][:12]
Bpool = np.stack([ud.signals(int(i), freq) for i in pool_idx])
K, C, N = Bpool.shape
print(f'pool {K} records T {T[pool_idx].min():.1f}..{T[pool_idx].max():.1f}', flush=True)
rows = []
t0 = time.time()
for m in range(len(ud)):
    x = ud.signals(m, freq)
    di = np.array([di_record(x[c], Bpool[:, c, :], alphas) for c in range(C)])
    rows.append({'T': float(T[m]), 'di_mean': float(di.mean()), 'di_max': float(di.max())})
    if (m + 1) % 60 == 0:
        print(f'  {m+1}/{len(ud)} ({time.time()-t0:.0f}s)', flush=True)
    del x
json.dump(rows, open('results/e1_extrapolation_f100.json', 'w'), indent=0)
lo = np.array([r['di_mean'] for r in rows if r['T'] <= 40])
hi = np.array([r['di_mean'] for r in rows if r['T'] > 40])
print(f'healthy DI_mean: <=40C {lo.mean():.4f}+-{lo.std():.4f} | >40C {hi.mean():.4f}+-{hi.std():.4f}')
print(f'extrapolation inflation factor: {hi.mean()/lo.mean():.2f}x')
