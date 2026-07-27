"""E3 (real OGW): event-structure statistics of temperature drift.

Without damage, the only event source is temperature. Compute per-record
SoD events of the compensated residual across all 66 paths; report
cross-path coherence and localization. Healthy records should show the
global/coherent pattern; this calibrates the discriminator's 'temperature'
end before damage data (D24) arrives.
"""
import sys, os, json, time
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from src.data.ogw_loader import OGWSetZip
from src.methods.baseline_fast import stretch_batch
from src.methods.sod import sod_encode
from src.methods.discriminator import cross_path_coherence, path_localization_index


def run(freq=100, delta=0.03, n_rec=None):
    ud = OGWSetZip('OGW_CFRP_Temperature_udam.zip')
    T = ud.temperatures()
    pool_idx = np.where(T <= 40.0)[0][::8][:12]
    Bpool = np.stack([ud.signals(int(i), freq) for i in pool_idx])
    K, C, N = Bpool.shape
    alphas = np.linspace(0.995, 1.005, 9)
    M = len(ud) if n_rec is None else min(n_rec, len(ud))
    rows = []
    t0 = time.time()
    for m in range(M):
        x = ud.signals(m, freq)
        ev_counts = np.zeros(C)
        for c in range(C):
            # OBS+BSS residual
            best = np.inf; br = None
            for a in alphas:
                S = stretch_batch(Bpool[:, c, :], a)
                R = S - x[c][None, :]
                e = np.einsum('ij,ij->i', R, R)
                k = int(np.argmin(e))
                if e[k] < best: best = float(e[k]); br = R[k]
            t, s, lv = sod_encode(br, delta)
            ev_counts[c] = len(t)
        rows.append({'T': float(T[m]), 'n_events': int(ev_counts.sum()),
                     'coherence': cross_path_coherence(ev_counts, thresh=3),
                     'localization': path_localization_index(ev_counts)})
        if (m + 1) % 60 == 0:
            print(f'  {m+1}/{M} ({time.time()-t0:.0f}s)', flush=True)
        del x
    json.dump(rows, open(f'results/e3_udam_f{freq}.json', 'w'), indent=0)
    coh = np.array([r['coherence'] for r in rows])
    loc = np.array([r['localization'] for r in rows])
    Tr = np.array([r['T'] for r in rows])
    print(f'healthy: coherence {coh.mean():.3f}+-{coh.std():.3f}, localization {loc.mean():.3f}+-{loc.std():.3f}')
    print(f'coherence vs temperature: corr {np.corrcoef(coh, Tr)[0,1]:.3f}')


if __name__ == '__main__':
    import sys
    n = int(sys.argv[1]) if len(sys.argv)>1 else None
    run(n_rec=n)
