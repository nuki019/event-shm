"""Vectorized fast BSS/OBS using numpy interpolation (memory-light)."""
import numpy as np


def stretch_batch(Y, alpha):
    """Time-stretch each row of Y (K, N) by alpha, keep length N (linear interp).
    Uses np.interp per row (C speed, no big temporaries)."""
    K, N = Y.shape
    t = (np.arange(N, dtype=np.float64) / alpha)
    xp = np.arange(N, dtype=np.float64)
    out = np.empty(Y.shape, dtype=np.float32)
    for k in range(K):
        out[k] = np.interp(t, xp, Y[k])
    return out


def bss_search(x, baselines, alphas):
    """For signal x (N,) and candidate baselines (K, N): pick (k, alpha)
    minimizing residual energy. Returns (best_k, best_alpha, baseline, residual)."""
    K, N = baselines.shape
    best_e = np.inf
    best = (0, alphas[0])
    for a in alphas:
        R = stretch_batch(baselines, a)
        R -= x[None, :]
        e = np.einsum('ij,ij->i', R, R)
        k = int(np.argmin(e))
        if e[k] < best_e:
            best_e = float(e[k])
            best = (k, a)
    k, a = best
    B = stretch_batch(baselines[k:k+1], a)[0]
    return k, float(a), B, x - B


def residual_grid(X, B, alphas):
    """X: (P, N); B: (P, K, N). Returns residuals (P, N) with best (k,alpha)
    per path, plus arrays ks, al."""
    P, N = X.shape
    res = np.empty_like(X)
    ks = np.empty(P, dtype=int)
    al = np.empty(P)
    for p in range(P):
        k, a, _, r = bss_search(X[p], B[p], alphas)
        res[p] = r; ks[p] = k; al[p] = a
    return ks, al, res
