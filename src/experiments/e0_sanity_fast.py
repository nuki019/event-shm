"""E0 sanity (fast): synthetic -> vectorized OBS+BSS -> SoD -> ROC."""
import sys, os, time
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from src.data.synthetic import make_cycle, DAMAGE_POS
from src.methods.baseline_fast import bss_search
from src.methods.damage_index import di_residual_energy
from src.methods.sod import sod_encode
from sklearn.metrics import roc_auc_score

t0 = time.time()
ud = make_cycle(n_temps=21, t_lo=20, t_hi=60, freqs=[100], damaged=False, seed=1)
dm = make_cycle(n_temps=21, t_lo=20, t_hi=60, freqs=[100], damaged=True, seed=2)
freq = 100
n_t = len(ud['temps'])
n_paths = len(ud['paths'])
n_samp = ud['signals'][(freq, 0)].shape[1]
print(f'cycles built {time.time()-t0:.1f}s, paths={n_paths}, n_samp={n_samp}')

pos = ud['positions']
def near_damage(p):
    a, s = pos[p[0]], pos[p[1]]
    ab = s - a
    u = np.clip(((DAMAGE_POS - a) @ ab) / (ab @ ab), 0, 1)
    return np.linalg.norm(DAMAGE_POS - (a + u * ab)) < 25
near = [i for i, p in enumerate(ud['paths']) if near_damage(p)]
print(f'near-damage paths: {len(near)}/{n_paths}')

baselines = np.stack([ud['signals'][(freq, ti)] for ti in range(n_t)])  # (K=21, P, N)
alphas = np.linspace(0.995, 1.005, 21)

# build per-path baseline arrays: (P, K, N)
B = np.transpose(baselines, (1, 0, 2))

labels, di_plain, di_comp, ev_all = [], [], [], []
t1 = time.time()
for ti in range(n_t):
    for cond, X in ((0, ud['signals'][(freq, ti)]), (1, dm['signals'][(freq, ti)])):
        for pi in range(n_paths):
            x = X[pi]
            k, a, bs, r = bss_search(x, B[pi], alphas)
            labels.append(cond)
            di_comp.append(di_residual_energy(x, r))
            di_plain.append(di_residual_energy(x, B[pi, 0]))
            if cond == 1:
                ev = sod_encode(r, delta=0.05)
                ev_all.append((pi, len(ev[0]) / n_samp))
print(f'compensation done in {time.time()-t1:.1f}s')
labels = np.array(labels)
print(f'AUC no-comp : {roc_auc_score(labels, di_plain):.3f}')
print(f'AUC OBS+BSS : {roc_auc_score(labels, di_comp):.3f}')
ev = np.array([e for _, e in ev_all])
evn = [e for p, e in ev_all if p in near]
evf = [e for p, e in ev_all if p not in near]
print(f'event rate (delta=0.05): near-damage {np.mean(evn):.4f} vs far {np.mean(evf):.4f} ev/sample')
print(f'total {time.time()-t0:.1f}s')
