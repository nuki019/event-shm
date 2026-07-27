"""Precompute OBS+BSS residuals for OGW sets and cache to disk (npz).
This is the expensive step (zip decompress + compensation); cache once,
then all experiments load npy directly (fast, low memory).
"""
import sys, os, time
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from src.data.ogw_loader import OGWSetZip
from src.methods.baseline_fast import stretch_batch
from scipy.signal import butter, filtfilt

_BA = butter(3, 20e3 / 5e6, btype='high')   # 20 kHz high-pass, fs=10 MHz

def prep(x):
    """High-pass + per-path unit-energy normalize (C, N) -> float32."""
    y = filtfilt(_BA[0], _BA[1], x, axis=1).astype(np.float32)
    n = np.sqrt((y ** 2).sum(axis=1, keepdims=True)) + 1e-9
    return y / n

OUT = 'data/processed'
os.makedirs(OUT, exist_ok=True)


def residuals(x, Bpool, alphas):
    K, C, N = Bpool.shape
    R = np.empty((C, N), dtype=np.float32)
    NN = np.empty(C, dtype=np.float32)
    for c in range(C):
        best = np.inf; br = None
        for a in alphas:
            S = stretch_batch(Bpool[:, c, :], a)
            Rr = S - x[c][None, :]
            e = np.einsum('ij,ij->i', Rr, Rr)
            k = int(np.argmin(e))
            if e[k] < best: best = float(e[k]); br = Rr[k]
        R[c] = br; NN[c] = max(float(np.dot(x[c], x[c])), 1e-9)
    return R, NN


def cache(freq=100, n_rec=40):
    ud = OGWSetZip('OGW_CFRP_Temperature_udam.zip')
    Tud = ud.temperatures()
    pool_idx = np.where(Tud <= 40.0)[0][::12][:8]
    Bpool = np.stack([prep(ud.signals(int(i), freq)) for i in pool_idx])
    alphas = np.linspace(0.985, 1.015, 13)
    np.save(f'{OUT}/Bpool_f{freq}.npy', Bpool)
    np.save(f'{OUT}/Tud_f{freq}.npy', Tud)
    for name, s in [('udam', ud),
                    ('D04', OGWSetZip('OGW_CFRP_Temperature_dam_D04.zip')),
                    ('D24', OGWSetZip('OGW_CFRP_Temperature_dam_D24.zip'))]:
        M = min(n_rec, len(s))
        T = s.temperatures()[:M]
        t0 = time.time()
        Rs, NNs = [], []
        for m in range(M):
            R, NN = residuals(prep(s.signals(m, freq)), Bpool, alphas)
            Rs.append(R); NNs.append(NN)
            if (m + 1) % 10 == 0:
                print(f'  {name} {m+1}/{M} ({time.time()-t0:.0f}s)', flush=True)
        np.save(f'{OUT}/R_{name}_f{freq}.npy', np.stack(Rs))
        np.save(f'{OUT}/NN_{name}_f{freq}.npy', np.stack(NNs))
        np.save(f'{OUT}/T_{name}_f{freq}.npy', T)
        print(f'cached {name} ({np.stack(Rs).shape})', flush=True)


if __name__ == '__main__':
    cache(n_rec=int(sys.argv[1]) if len(sys.argv) > 1 else 40)
