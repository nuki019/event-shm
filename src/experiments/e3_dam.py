"""E3-dam: event structure of DAMAGE records (D24) vs healthy (udam).
Same pipeline; compare coherence/localization distributions."""
import sys, os, json, time
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from src.data.ogw_loader import OGWSetZip
from src.methods.baseline_fast import stretch_batch
from src.methods.sod import sod_encode
from src.methods.discriminator import cross_path_coherence, path_localization_index
from sklearn.metrics import roc_auc_score


def structure_of(s, Bpool, alphas, delta, n_rec, freq):
    T = s.temperatures()
    M = min(n_rec, len(s)) if n_rec else len(s)
    K, C, N = Bpool.shape
    rows = []
    for m in range(M):
        x = s.signals(m, freq)
        ev = np.zeros(C)
        for c in range(C):
            best = np.inf; br = None
            for a in alphas:
                S = stretch_batch(Bpool[:, c, :], a)
                R = S - x[c][None, :]
                e = np.einsum('ij,ij->i', R, R)
                k = int(np.argmin(e))
                if e[k] < best: best = float(e[k]); br = R[k]
            t, sg, lv = sod_encode(br, delta)
            ev[c] = len(t)
        rows.append({'T': float(T[m]), 'n_events': int(ev.sum()),
                     'coherence': cross_path_coherence(ev, 3),
                     'localization': path_localization_index(ev)})
        del x
    return rows


def run(freq=100, delta=0.03, n_rec=None):
    ud = OGWSetZip('OGW_CFRP_Temperature_udam.zip')
    Tud = ud.temperatures()
    pool_idx = np.where(Tud <= 40.0)[0][::8][:12]
    Bpool = np.stack([ud.signals(int(i), freq) for i in pool_idx])
    alphas = np.linspace(0.995, 1.005, 9)
    t0 = time.time()
    h = structure_of(ud, Bpool, alphas, delta, n_rec, freq)
    print(f'healthy {len(h)} rec ({time.time()-t0:.0f}s)', flush=True)
    dm = OGWSetZip('OGW_CFRP_Temperature_dam_D24.zip')
    dd = structure_of(dm, Bpool, alphas, delta, n_rec, freq)
    print(f'D24 {len(dd)} rec ({time.time()-t0:.0f}s)', flush=True)
    json.dump({'healthy': h, 'D24': dd}, open(f'results/e3_structure_f{freq}.json', 'w'))
    # discriminate
    y = np.array([0]*len(h) + [1]*len(dd))
    coh = np.array([r['coherence'] for r in h+dd])
    loc = np.array([r['localization'] for r in h+dd])
    nev = np.array([r['n_events'] for r in h+dd])
    print(f'AUC by coherence: {roc_auc_score(y, -coh):.3f} (low coherence=damage)')
    print(f'AUC by localization: {roc_auc_score(y, loc):.3f}')
    print(f'AUC by n_events: {roc_auc_score(y, nev):.3f}')
    print(f'healthy coh {coh[:len(h)].mean():.2f} loc {loc[:len(h)].mean():.2f} | D24 coh {coh[len(h):].mean():.2f} loc {loc[len(h):].mean():.2f}')


if __name__ == '__main__':
    n = int(sys.argv[1]) if len(sys.argv) > 1 else None
    run(n_rec=n)
