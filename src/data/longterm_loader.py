"""Loader for the UF/Utah long-term aluminum-plate dataset.

Files: monthly pickles 'measurements YYYY_MM.pickle'. Based on the
SmartDATA-Lab code and Scientific Data descriptor: each pickle holds a
list/dict of records with waveforms + environmental metadata. We keep
access lazy and tolerant of exact schema (probe first, then index).
"""
import os, pickle, json
import numpy as np

RAW = os.path.join(os.path.dirname(__file__), '../../data/raw')


def probe_month(path):
    with open(path, 'rb') as f:
        obj = pickle.load(f)
    info = {'type': str(type(obj))}
    if isinstance(obj, dict):
        info['keys'] = list(obj.keys())[:30]
        for k in list(obj.keys())[:3]:
            v = obj[k]
            info[f'{k}'] = {'type': str(type(v)),
                            'len': len(v) if hasattr(v, '__len__') else None}
    elif isinstance(obj, (list, tuple)):
        info['len'] = len(obj)
        if len(obj):
            v = obj[0]
            info['first'] = {'type': str(type(v))}
            if isinstance(v, dict):
                info['first_keys'] = list(v.keys())
            elif hasattr(v, '__dict__'):
                info['first_attrs'] = list(v.__dict__.keys())
    return info


if __name__ == '__main__':
    import sys, glob
    files = sorted(glob.glob(os.path.join(RAW, 'measurements*.pickle')))
    print('found', len(files), 'monthly files')
    if files:
        info = probe_month(files[0])
        print(json.dumps(info, indent=1, default=str)[:2000])
