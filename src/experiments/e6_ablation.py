"""E6 ablation (real, 40 kHz): effect of compensation quality and SoD delta
on detection. Compare no-comp / OBS-only / OBS+BSS baseline compensation.
"""
import sys, os, json
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from src.data.ogw_loader import OGWSetZip
from src.methods.baseline_fast import stretch_batch
from scipy.signal import butter, filtfilt
from sklearn.metrics import roc_auc_score

_BA = butter(3, 20e3/5e6, btype='high')
def prep(x):
    y = filtfilt(_BA[0], _BA[1], x, axis=1).astype(np.float32)
    n = np.sqrt((y**2).sum(axis=1, keepdims=True)) + 1e-9
    return y/n

def di_obs(x, Bp):
    R = Bp - x[None, :]
    e = np.einsum('ij,ij->i', R, R)
    return float(e.min()) / max(float(np.dot(x, x)), 1e-9)

def di_bss(x, Bp, alphas):
    best = np.inf; xx = max(float(np.dot(x, x)), 1e-9)
    for a in alphas:
        S = stretch_batch(Bp, a)
        R = S - x[None, :]
        e = np.einsum('ij,ij->i', R, R)
        m = float(e.min())
        if m < best: best = m
    return best / xx

def di_none(x, Bp):
    r = x - Bp[0]
    return float(np.dot(r, r)) / max(float(np.dot(x, x)), 1e-9)

def run(freq=40, n_rec=20):
    ud = OGWSetZip('OGW_CFRP_Temperature_udam.zip'); dm = OGWSetZip('OGW_CFRP_Temperature_dam_D04.zip')
    Tud = ud.temperatures()
    pool = np.where(Tud <= 40)[0][::12][:8]
    Bpool = np.stack([prep(ud.signals(int(i), freq)) for i in pool])
    alphas = np.linspace(0.985, 1.015, 13)
    methods = {'none': di_none, 'OBS': di_obs, 'OBS+BSS': lambda x, b: di_bss(x, b, alphas)}
    out = {}
    for name, fn in methods.items():
        labels, di_l = [], []
        for cond, s in ((0, ud), (1, dm)):
            for m in range(n_rec):
                x = prep(s.signals(m, freq))
                d = np.array([fn(x[c], Bpool[:, c, :]) for c in range(66)])
                labels.append(cond); di_l.append(d.mean())
        out[name] = float(roc_auc_score(np.array(labels), np.array(di_l)))
        print(f'{name}: D04 AUC {out[name]:.3f}', flush=True)
    json.dump(out, open('results/e6_ablation.json', 'w'), indent=1)

if __name__ == '__main__':
    run()
