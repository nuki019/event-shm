"""Vectorized fast BSS/OBS using scipy.ndimage.map_coordinates."""
import numpy as np
from scipy.ndimage import map_coordinates


def stretch_batch(Y, alpha):
    """Time-stretch each row of Y (K, N) by alpha, keep length N (linear interp)."""
    K, N = Y.shape
    t = np.arange(N, dtype=float) / alpha
    # clamp to valid range
    np.clip(t, 0, N - 1, out=t)
    coords = np.broadcast_to(t, (K, N))
    rows = np.arange(K)[:, None]
    return map_coordinates(Y, [rows + t * 0, coords], order=1, mode='nearest')


def bss_search(x, baselines, alphas):
    """For one signal x (N,) and candidate baselines (K, N):
    for each baseline, find alpha in alphas minimizing residual energy.
    Vectorized over K for each alpha. Returns (best_k, best_alpha, residual)."""
    N = x.shape[0]
    K = baselines.shape[0]
    best_e = np.full(K, np.inf)
    best_a = np.ones(K)
    for a in alphas:
        B = stretch_batch(baselines, a)
        R = B - x[None, :]
        e = np.einsum('ij,ij->i', R, R)
        upd = e < best_e
        best_e[upd] = e[upd]
        best_a[upd] = a
    k = int(np.argmin(best_e))
    B = stretch_batch(baselines[k:k+1], best_a[k])[0]
    return k, float(best_a[k]), B, x - B


def bss_search_batch(X, baselines, alphas):
    """X: (P, N) signals; baselines: (P, K, N). Returns per-path (k, alpha, residual)."""
    P, N = X.shape
    K = baselines.shape[1]
    res = np.empty_like(X)
    ks = np.empty(P, dtype=int)
    al = np.empty(P)
    for p in range(P):
        k, a, B, r = bss_search(X[p], baselines[p], alphas)
        res[p] = r; ks[p] = k; al[p] = a
    return ks, al, res
