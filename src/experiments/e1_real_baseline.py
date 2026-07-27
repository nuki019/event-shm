"""E1 (real): OGW#2 baseline reproduction.

For a given frequency: load udam (baseline pool + healthy test records) and
one damage set; compute DI with OBS+BSS; AUC vs temperature; compare with
no-compensation. Mirrors the Schnur et al. 2022 setup loosely (they used
feature ML; we anchor on the classic DI pipeline first).
"""
import sys, os, json, time, argparse
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from src.data.ogw_loader import OGWSet
from src.methods.baseline_fast import bss_search
from src.methods.damage_index import di_residual_energy
from sklearn.metrics import roc_auc_score

RAW = os.path.join(os.path.dirname(__file__), '../../data/raw')


def load_set_matrix(s: OGWSet, freq, channels=None, hp=False):
    """Load all records of one set at one frequency.
    Returns X (M, C, N), temps (M,)."""
    Xs, Ts = [], []
    for i in range(len(s)):
        x = s.signals(i, freq)                      # (N, C)
        if channels is not None:
            x = x[:, channels]
        Xs.append(x.T)                            # (C, N)
        Ts.append(s.temperature(i, freq))
    return np.stack(Xs), np.array(Ts)


def run(freq=100, dam='D04', max_chan=None, alpha_grid=(0.99, 1.01, 41), out=None):
    t0 = time.time()
    ud = OGWSet(os.path.join(RAW, 'OGW_CFRP_Temperature_udam'))
    dm = OGWSet(os.path.join(RAW, f'OGW_CFRP_Temperature_dam_{dam}'))
    print('udam:', len(ud), 'records;', dam, ':', len(dm), 'records')
    ch = list(range(max_chan)) if max_chan else None
    Xu, Tu = load_set_matrix(ud, freq, ch)
    Xd, Td = load_set_matrix(dm, freq, ch)
    print(f'loaded udam {Xu.shape}, dam {Xd.shape} in {time.time()-t0:.0f}s; '
          f'T range {Tu.min():.1f}..{Tu.max():.1f} / {Td.min():.1f}..{Td.max():.1f}')

    n_chan = Xu.shape[1]
    # baseline pool: healthy records at <= 40 C (extrapolation protocol)
    pool_idx = np.where(Tu <= 40.0)[0]
    B = np.transpose(Xu[pool_idx], (1, 0, 2))     # (C, K, N)
    alphas = np.linspace(*alpha_grid)

    labels, di_comp, di_plain = [], [], []
    t1 = time.time()
    for cond, X in ((0, Xu), (1, Xd)):
        for m in range(X.shape[0]):
            for c in range(n_chan):
                x = X[m, c].astype(np.float32)
                k, a, bs, r = bss_search(x, B[c], alphas)
                di_comp.append(di_residual_energy(x, r))
                di_plain.append(di_residual_energy(x, B[c, 0]))
                labels.append(cond)
        print(f'  cond {cond} done ({time.time()-t1:.0f}s)', flush=True)
    labels = np.array(labels)
    auc_comp = roc_auc_score(labels, di_comp)
    auc_plain = roc_auc_score(labels, di_plain)
    print(f'freq={freq} dam={dam}: AUC no-comp {auc_plain:.3f} | OBS+BSS {auc_comp:.3f}')
    out = out or f'results/e1_real_f{freq}_{dam}.json'
    json.dump({'freq': freq, 'dam': dam, 'auc_comp': auc_comp, 'auc_plain': auc_plain,
               'n_records_u': int(len(Xu)), 'n_records_d': int(len(Xd))},
              open(out, 'w'), indent=1)
    print('saved', out)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--freq', type=int, default=100)
    ap.add_argument('--dam', default='D04')
    ap.add_argument('--max-chan', type=int, default=None)
    args = ap.parse_args()
    run(args.freq, args.dam, args.max_chan)
