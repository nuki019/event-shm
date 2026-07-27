"""E0 sanity: synthetic data -> BSS/OBS -> residual -> SoD events -> DI ROC."""
import sys, os, time
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from src.data.synthetic import make_cycle, FS
from src.methods.baseline import bss_compensate, obs_bss, highpass
from src.methods.damage_index import di_residual_energy
from src.methods.sod import sod_encode
from sklearn.metrics import roc_auc_score

t0 = time.time()
# undamaged cycle (baselines) + damaged cycle
ud = make_cycle(n_temps=21, t_lo=20, t_hi=60, freqs=[100], damaged=False, seed=1)
dm = make_cycle(n_temps=21, t_lo=20, t_hi=60, freqs=[100], damaged=True, seed=2)
print(f'synthetic cycles built in {time.time()-t0:.1f}s; paths={len(ud["paths"])}')

freq = 100
n_t = len(ud['temps'])
n_paths = len(ud['paths'])
n_samp = ud['signals'][(freq, 0)].shape[1]

# pick a subset of paths passing near damage for display
from src.data.synthetic import DAMAGE_POS
pos = ud['positions']
def near_damage(p):
    a, s = pos[p[0]], pos[p[1]]
    ab = s - a
    u = np.clip(((DAMAGE_POS - a) @ ab) / (ab @ ab), 0, 1)
    return np.linalg.norm(DAMAGE_POS - (a + u * ab)) < 25
near = [i for i, p in enumerate(ud['paths']) if near_damage(p)]
print(f'paths passing near damage: {len(near)}/{n_paths}')

# --- baseline compensation pipeline ---
baselines = np.stack([ud['signals'][(freq, ti)] for ti in range(n_t)])  # (n_t, n_paths, n_samp)
labels, di_plain, di_bssobs, ev_rate = [], [], [], []
for ti in range(n_t):
    X_u = ud['signals'][(freq, ti)]  # (n_paths, n_samp)
    X_d = dm['signals'][(freq, ti)]
    for cond, X in ((0, X_u), (1, X_d)):
        for pi in range(n_paths):
            x = X[pi]
            # OBS+BSS with baselines from same temp range (leave-self-in ok for sanity)
            k, a, bs, r = obs_bss(x, baselines[:, pi, :])
            labels.append(cond)
            di_bssobs.append(di_residual_energy(x, r))
            # no compensation: subtract mean baseline at nearest temp
            r0 = x - baselines[0, pi]
            di_plain.append(di_residual_energy(x, r0))
            if cond == 1 and pi in near[:3]:
                ev = sod_encode(r, delta=0.05)
                ev_rate.append(len(ev[0]) / n_samp)

labels = np.array(labels)
print(f'AUC (no compensation): {roc_auc_score(labels, di_plain):.3f}')
print(f'AUC (OBS+BSS)        : {roc_auc_score(labels, di_bssobs):.3f}')
print(f'mean event rate on damaged near-paths (delta=0.05): {np.mean(ev_rate):.4f} events/sample')
print(f'total time {time.time()-t0:.1f}s')
