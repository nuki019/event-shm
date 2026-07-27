"""E1 (real OGW, memory-efficient): stream records, temperature-matched OBS
baseline (subset pool), DI per path -> AUC. Avoids holding the full
(66,154,13108) baseline tensor by using a per-record matched subset.
"""
import sys, os, json, time, argparse
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from src.data.ogw_loader import OGWSetZip, load_matrix
from src.methods.baseline_fast import stretch_batch
from src.methods.damage_index import di_residual_energy
from sklearn.metrics import roc_auc_score


def run(freq=100, dam_zip=None, t_base=40.0, n_pool=40, alphas=None):
    t0 = time.time()
    ud = OGWSetZip('OGW_CFRP_Temperature_udam.zip')
    Xu, Tu = load_matrix(ud, freq)
    print(f'udam {Xu.shape}, T {Tu.min():.1f}..{Tu.max():.1f} ({time.time()-t0:.0f}s)', flush=True)
    if alphas is None:
        alphas = np.linspace(0.995, 1.005, 11)
    pool_idx = np.where(Tu <= t_base)[0]
    pool_T = Tu[pool_idx]
    sets = [(0, Xu, Tu)]
    if dam_zip:
        dm = OGWSetZip(dam_zip)
        Xd, Td = load_matrix(dm, freq)
        print(f'{dam_zip} {Xd.shape}, T {Td.min():.1f}..{Td.max():.1f}', flush=True)
        sets.append((1, Xd, Td))

    labels, di_comp, di_plain = [], [], []
    t1 = time.time()
    for cond, X, T in sets:
        for m in range(X.shape[0]):
            # temperature-matched baseline subset (nearest n_pool in T)
            near = pool_idx[np.argsort(np.abs(pool_T - T[m]))[:n_pool]]
            Bp = np.transpose(X[near], (1, 0, 2))   # (C, K, N)
            for c in range(X.shape[1]):
                x = X[m, c]
                # OBS+BSS over subset
                best_e = np.inf; br = None
                for a in alphas:
                    S = stretch_batch(Bp[c], a)
                    R = S - x[None, :]
                    e = np.einsum('ij,ij->i', R, R)
                    k = int(np.argmin(e))
                    if e[k] < best_e:
                        best_e = float(e[k]); br = R[k]
                di_comp.append(best_e / max(float(np.dot(x, x)), 1e-9))
                di_plain.append(di_residual_energy(x, Bp[c, 0]))
                labels.append(cond)
            if (m + 1) % 50 == 0:
                print(f'  cond{cond} {m+1}/{X.shape[0]} ({time.time()-t1:.0f}s)', flush=True)
    labels = np.array(labels)
    auc_c = roc_auc_score(labels, di_comp)
    auc_p = roc_auc_score(labels, di_plain)
    print(f'freq={freq} dam={dam_zip}: AUC no-comp {auc_p:.3f} | OBS+BSS {auc_c:.3f}')
    out = f'results/e1_real_f{freq}' + (f'_{os.path.basename(dam_zip)[:3]}' if dam_zip else '') + '.json'
    json.dump({'freq': freq, 'dam': dam_zip, 'auc_comp': auc_c, 'auc_plain': auc_p},
              open(out, 'w'), indent=1)
    print('saved', out)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--freq', type=int, default=100)
    ap.add_argument('--dam', default=None)
    ap.add_argument('--n-pool', type=int, default=40)
    args = ap.parse_args()
    run(args.freq, args.dam, n_pool=args.n_pool)
