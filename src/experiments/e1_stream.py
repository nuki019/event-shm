"""E1 (streaming, minimal memory): per-record from zip, small baseline pool.
DI via OBS+BSS. udam self-test (healthy-vs-healthy should be ~0.5 AUC on
matched temp, rising when temperature extrapolates) then damage AUC.
"""
import sys, os, json, time, argparse
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from src.data.ogw_loader import OGWSetZip
from src.methods.baseline_fast import stretch_batch
from sklearn.metrics import roc_auc_score


def di_record(x, Bp, alphas):
    """x (N,), Bp (K, N) small pool. Return best OBS+BSS normalized residual."""
    best = np.inf
    xx = max(float(np.dot(x, x)), 1e-9)
    for a in alphas:
        S = stretch_batch(Bp, a)
        R = S - x[None, :]
        e = np.einsum('ij,ij->i', R, R)
        m = float(e.min())
        if m < best:
            best = m
    return best / xx


def run(freq=100, dam_zip=None, n_pool=12, max_rec=None, alphas=None):
    if alphas is None:
        alphas = np.linspace(0.995, 1.005, 9)
    t0 = time.time()
    ud = OGWSetZip('OGW_CFRP_Temperature_udam.zip')
    T_all = ud.temperatures()
    # small baseline pool: records at <=40C, evenly spaced
    pool_idx = np.where(T_all <= 40.0)[0][::max(1, int(np.sum(T_all <= 40) / n_pool))][:n_pool]
    print(f'baseline pool {len(pool_idx)} records, T {T_all[pool_idx].min():.1f}..{T_all[pool_idx].max():.1f}', flush=True)
    # load pool once (small): (K, 66, N)
    Bpool = np.stack([ud.signals(int(i), freq) for i in pool_idx])
    K, C, N = Bpool.shape
    print(f'pool loaded {Bpool.shape} ({time.time()-t0:.0f}s)', flush=True)

    sets = [(0, ud, T_all)]
    if dam_zip:
        dm = OGWSetZip(dam_zip)
        sets.append((1, dm, dm.temperatures()))
    labels, di_c, di_p = [], [], []
    t1 = time.time()
    for cond, s, T in sets:
        M = len(s) if max_rec is None else min(max_rec, len(s))
        for m in range(M):
            x = s.signals(m, freq)             # (66, N)
            for c in range(C):
                xc = x[c]
                di_c.append(di_record(xc, Bpool[:, c, :], alphas))
                di_p.append(float(np.sum((xc - Bpool[0, c]) ** 2)) / max(float(np.dot(xc, xc)), 1e-9))
                labels.append(cond)
            if (m + 1) % 100 == 0:
                print(f'  cond{cond} {m+1}/{M} ({time.time()-t1:.0f}s)', flush=True)
            del x
    labels = np.array(labels)
    auc_c = roc_auc_score(labels, di_c)
    auc_p = roc_auc_score(labels, di_p)
    print(f'freq={freq} dam={dam_zip}: AUC no-comp {auc_p:.3f} | OBS+BSS {auc_c:.3f}')
    out = f'results/e1_stream_f{freq}' + ('_dam' if dam_zip else '') + '.json'
    json.dump({'freq': freq, 'dam': dam_zip, 'auc_comp': auc_c, 'auc_plain': auc_p},
              open(out, 'w'), indent=1)
    print('saved', out)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--freq', type=int, default=100)
    ap.add_argument('--dam', default=None)
    ap.add_argument('--n-pool', type=int, default=12)
    ap.add_argument('--max-rec', type=int, default=None)
    args = ap.parse_args()
    run(args.freq, args.dam, args.n_pool, args.max_rec)
