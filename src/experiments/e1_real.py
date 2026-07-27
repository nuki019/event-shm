"""E1 (real OGW): OBS+BSS DI pipeline on zip-loaded data."""
import sys, os, json, time, argparse
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from src.data.ogw_loader import OGWSetZip, load_matrix
from src.methods.baseline_fast import bss_search
from src.methods.damage_index import di_residual_energy
from sklearn.metrics import roc_auc_score


def run(freq=100, dam_zip=None, t_base=40.0, n_chan=None, out=None):
    t0 = time.time()
    ud = OGWSetZip('OGW_CFRP_Temperature_udam.zip')
    Xu, Tu = load_matrix(ud, freq)
    # use all 66 channels
    print(f'udam {Xu.shape}, T {Tu.min():.1f}..{Tu.max():.1f} ({time.time()-t0:.0f}s)')
    sets = [(0, Xu, Tu)]
    if dam_zip:
        dm = OGWSetZip(dam_zip)
        Xd, Td = load_matrix(dm, freq)
        print(f'{dam_zip} {Xd.shape}, T {Td.min():.1f}..{Td.max():.1f}')
        sets.append((1, Xd, Td))

    pool = np.where(Tu <= t_base)[0]
    B = np.transpose(Xu[pool], (1, 0, 2))     # (C, K, N)
    alphas = np.linspace(0.995, 1.005, 21)
    labels, di_comp, di_plain = [], [], []
    t1 = time.time()
    for cond, X, T in sets:
        for m in range(X.shape[0]):
            for ci in range(X.shape[1]):
                x = X[m, ci]
                k, a, bs, r = bss_search(x, B[ci], alphas)
                di_comp.append(di_residual_energy(x, r))
                di_plain.append(di_residual_energy(x, B[ci, 0]))
                labels.append(cond)
        print(f'  cond {cond} done ({time.time()-t1:.0f}s)', flush=True)
    labels = np.array(labels)
    auc_c = roc_auc_score(labels, di_comp)
    auc_p = roc_auc_score(labels, di_plain)
    print(f'freq={freq} dam={dam_zip}: AUC no-comp {auc_p:.3f} | OBS+BSS {auc_c:.3f}')
    out = out or f'results/e1_real_f{freq}.json'
    json.dump({'freq': freq, 'dam': dam_zip, 'auc_comp': auc_c, 'auc_plain': auc_p},
              open(out, 'w'), indent=1)
    print('saved', out)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--freq', type=int, default=100)
    ap.add_argument('--dam', default=None)
    ap.add_argument('--n-chan', type=int, default=None)
    args = ap.parse_args()
    run(freq=args.freq, dam_zip=args.dam, n_chan=args.n_chan)
