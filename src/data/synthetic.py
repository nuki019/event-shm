"""Synthetic guided-wave dataset mimicking OGW#2 specs.

Purpose: end-to-end pipeline validation before/until the real OGW data
is available. Physics model (deliberately simple but with the right
spatio-temporal structure):

- Plate 500x500 mm, 12 transducers (OGW-like layout).
- A0-mode toneburst (5-cycle Hann), mild dispersion.
- Temperature: time-stretch of the whole trace (velocity change),
  plus smooth amplitude drift; alpha(T) = 1 + k_T*(T-T0).
- Damage (surface-mounted disc at D): paths whose actuator-sensor line
  passes within R of D acquire an extra scattered wavepacket; exact-line
  paths additionally lose direct amplitude (shadowing).
- Noise: white Gaussian, SNR ~ 40 dB.
"""
import numpy as np

# OGW-like transducer layout on 500x500 mm plate (approximate, mm)
# (for synthetic testing only; real layout read from dataset metadata)
RNG_POS = np.array([
    [150, 150], [250, 110], [350, 150], [390, 250],
    [350, 350], [250, 390], [150, 350], [110, 250],
    [250, 250], [180, 320], [320, 320], [250, 180],
], dtype=float)

FS = 10e6                    # 10 MHz as in OGW
N_SAMPLES = 12000            # 1.2 ms
C_G = 1350.0                 # group velocity m/s (A0-ish)
K_T = 6e-5                   # relative velocity change per degC (=> ToF stretch)
AMP_DRIFT = 0.002            # per degC amplitude drift (relative)
DAMAGE_POS = np.array([300.0, 220.0])   # mm (like a D-point between centre and edge)
DAMAGE_R = 12.0              # mm effective disc radius
SCATTER_AMP = 0.22           # relative amplitude of scattered packet
SHADOW = 0.12                # direct-path amplitude loss on exact-line paths


def hann_toneburst(fc, n_cycles=5, fs=FS):
    dur = n_cycles / fc
    n = int(dur * fs)
    t = np.arange(n) / fs
    w = np.hanning(n)
    return np.sin(2 * np.pi * fc * t) * w


def _line_point_dist(a, b, p):
    """Distance from point p to segment a-b, and projection parameter u in [0,1]."""
    ab = b - a
    L2 = ab @ ab
    if L2 == 0:
        return np.linalg.norm(p - a), 0.0
    u = np.clip(((p - a) @ ab) / L2, 0.0, 1.0)
    proj = a + u * ab
    return np.linalg.norm(p - proj), u


def path_signal(pos_a, pos_s, fc, temp, temp0=20.0, damaged=False,
                rng=None, snr_db=40.0):
    """Generate one path signal at given temperature."""
    rng = rng or np.random.default_rng(0)
    sig = np.zeros(N_SAMPLES)
    burst = hann_toneburst(fc)
    alpha = 1.0 + K_T * (temp - temp0)          # wave slower when hotter -> arrive later
    amp_T = 1.0 + AMP_DRIFT * (temp - temp0)

    def add_packet(delay_s, amp):
        i0 = int(delay_s * FS / alpha)           # stretch shifts arrival
        i1 = min(i0 + len(burst), N_SAMPLES)
        if i0 < N_SAMPLES:
            sig[i0:i1] += amp * burst[:i1 - i0]

    d = np.linalg.norm(pos_s - pos_a) / 1000.0   # m
    t_direct = d / C_G
    add_packet(t_direct, amp_T)

    # a weak boundary reflection for realism (fixed path, e.g. nearest edge)
    edge = min(pos_a[0], pos_a[1], 500 - pos_a[0], 500 - pos_a[1],
               pos_s[0], pos_s[1], 500 - pos_s[0], 500 - pos_s[1]) / 1000.0
    add_packet(t_direct + 2 * edge / C_G, 0.18 * amp_T)

    if damaged:
        dist, u = _line_point_dist(pos_a, pos_s, DAMAGE_POS)
        if dist < DAMAGE_R * 2.5:
            # scatterer: path a->D->s
            d_sc = (np.linalg.norm(DAMAGE_POS - pos_a) +
                    np.linalg.norm(pos_s - DAMAGE_POS)) / 1000.0
            t_sc = d_sc / C_G
            strength = SCATTER_AMP * np.exp(-dist / DAMAGE_R)
            add_packet(t_sc, strength * amp_T)
            if dist < DAMAGE_R * 0.7:
                sig *= (1.0 - SHADOW * (1 - dist / (DAMAGE_R * 0.7)))

    noise = rng.standard_normal(N_SAMPLES)
    sig += noise * (np.max(np.abs(sig)) / (10 ** (snr_db / 20)))
    return sig


def make_cycle(n_temps=41, t_lo=20.0, t_hi=60.0, freqs=None, damaged=False,
               seed=0, positions=RNG_POS):
    """Generate one temperature cycle.

    Returns dict with keys:
      temps : (n_temps,) float
      freqs : list of kHz
      signals : dict[(freq_khz, ti)] -> (n_paths, n_samples) array
      paths : list of (ia, is) transducer index pairs
    """
    freqs = freqs or [40, 60, 80, 100, 120, 140, 160, 180, 200, 220, 240, 260]
    temps = np.linspace(t_lo, t_hi, n_temps)
    n_tr = len(positions)
    paths = [(i, j) for i in range(n_tr) for j in range(n_tr) if i != j]
    rng = np.random.default_rng(seed)
    signals = {}
    for f in freqs:
        for ti, T in enumerate(temps):
            arr = np.stack([
                path_signal(positions[i], positions[j], f * 1e3, T,
                            damaged=damaged, rng=rng)
                for (i, j) in paths])
            signals[(f, ti)] = arr
    return {'temps': temps, 'freqs': freqs, 'signals': signals,
            'paths': paths, 'positions': positions}
