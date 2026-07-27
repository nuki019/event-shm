"""Loader for the UF/Utah long-term aluminum-plate dataset (2018-2022).

Each monthly pickle is a dict with keys:
  datatime (M,) datetime; temperature/pressure/brightness/humidity (M,);
  damage tag (M,) 0=healthy,1..13 damage stages; weather tag (M,) 0=fair,1..5;
  excitation signal (1000,); guided wave (M, 8, 2000) float64.
Path mapping (from data inf): waves 1..8 -> paths 5-1,5-2,5-3,5-4,6-1,6-2,6-3,6-4.
Chirp excitation 5-350 kHz, 1 ms; fs ~ 2 MHz (2000 samples / 1 ms window).
"""
import os, pickle, glob
import numpy as np

RAW = os.path.join(os.path.dirname(__file__), '../../data/raw')
PATHS = ['5-1', '5-2', '5-3', '5-4', '6-1', '6-2', '6-3', '6-4']
FS = 2e6   # 2000 samples per 1 ms


def month_file(year_month):
    return os.path.join(RAW, f'measurements_{year_month}.pickle')


def load_month(year_month, float32=True):
    with open(month_file(year_month), 'rb') as f:
        d = pickle.load(f)
    gw = d['guided wave']
    if float32 and gw.dtype != np.float32:
        gw = gw.astype(np.float32)
    # drop unused big fields early to limit peak memory
    for k in ('excitation signal',):
        d.pop(k, None)
    return {
        'gw': gw,                                   # (M, 8, 2000)
        't': d['datatime'],
        'temp': np.asarray(d['temperature'], float),
        'weather': np.asarray(d['weather tag'], int),
        'damage': np.asarray(d['damage tag'], int),
        'paths': PATHS, 'fs': FS,
    }


def available_months():
    return [os.path.basename(p).replace('measurements_', '').replace('.pickle', '')
            for p in sorted(glob.glob(month_file('*')))]
