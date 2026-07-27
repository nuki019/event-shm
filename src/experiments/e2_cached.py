"""E2 (real, from cached residuals): detection AUC vs event rate.
Reads data/processed/R_*.npy (no zip decompression, low memory)."""
import sys, os, json
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from src.methods.sod import sod_encode, sod_decode
from sklearn.metrics import roc_auc_score

PROC = 'data/processed'

def run(freq=100, dam='D04', deltas=None):
    if deltas is None:
        deltas = np.geomspace(0.0005, 0.05, 12)
    RH = np.load(f'{PROC}/R_udam_f{freq}.npy')
    RD = np.load(f'{PROC}/R_{dam}_f{freq}.npy')
    NNH = np.load(f'{PROC}/NN_udam_f{freq}.npy')
    NND = np.load(f'{PROC}/NN_{dam}_f{freq}.npy')
    rows = []
    for delta in deltas:
        labels, di_e, di_u, rates = [], [], [], []
        for cond, RR, NN in ((0, RH, NNH), (1, RD, NND)):
            for m in range(RR.shape[0]):
                for c in range(0, RR.shape[1], 3):   # 22 paths
                    r = RR[m, c]; nn = NN[m, c]
                    t, s, lv = sod_encode(r, delta)
                    rates.append(len(t) / len(r))
                    rec = sod_decode(t, lv, len(r))
                    labels.append(cond)
                    di_e.append(float(np.dot(rec, rec)) / nn)
                    rate = len(t) / len(r)
                    step = max(1, int(round(1.0 / rate))) if rate > 1e-6 else len(r)
                    uni = np.zeros(len(r), dtype=np.float32)
                    uni[::step] = r[::step]
                    di_u.append(float(np.dot(uni, uni)) / nn)
        labels = np.array(labels)
        ae = roc_auc_score(labels, di_e); au = roc_auc_score(labels, di_u)
        rows.append({'delta': float(delta), 'event_rate': float(np.mean(rates)),
                     'auc_event': float(ae), 'auc_uniform': float(au)})
        print(f'delta={delta:.4f} rate={rows[-1]["event_rate"]:.5f} AUC_ev={ae:.3f} AUC_uni={au:.3f}', flush=True)
    json.dump({'freq': freq, 'dam': dam, 'rows': rows},
              open(f'results/e2_real_f{freq}_{dam}.json', 'w'), indent=1)
    print('saved')

if __name__ == '__main__':
    run(dam=sys.argv[1] if len(sys.argv) > 1 else 'D04')
