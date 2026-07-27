"""Extract OGW zip (streaming) and build a compact index of measurements.

The zips are large (53/27 GB) with one folder per temperature point
containing 12 h5 files (one per frequency). We extract, then index
(folder -> temperature) to avoid re-reading every h5 for metadata.
"""
import os, sys, zipfile, json, re
import numpy as np

RAW = os.path.join(os.path.dirname(__file__), '../../data/raw')


def extract(zip_name):
    zp = os.path.join(RAW, zip_name)
    out_dir = os.path.join(RAW, zip_name.replace('.zip', ''))
    os.makedirs(out_dir, exist_ok=True)
    with zipfile.ZipFile(zp) as z:
        names = z.namelist()
        n = len(names)
        print(f'{zip_name}: {n} entries -> {out_dir}', flush=True)
        for i, name in enumerate(names):
            z.extract(name, out_dir)
            if (i + 1) % 2000 == 0:
                print(f'  {i+1}/{n}', flush=True)
    print('done', flush=True)
    return out_dir


def index_temperatures(root):
    """Map each measurement folder to its mean temperature (from f100 file)."""
    import h5py
    data_dir = os.path.join(root, 'Data')
    if not os.path.isdir(data_dir):
        data_dir = root
    idx = {}
    folders = sorted(os.listdir(data_dir))
    for i, name in enumerate(folders):
        d = os.path.join(data_dir, name)
        if not os.path.isdir(d):
            continue
        # find any h5 to read temperature
        for f in os.listdir(d):
            if f.startswith('pc_f') and f.endswith('.h5'):
                try:
                    with h5py.File(os.path.join(d, f), 'r') as h:
                        idx[name] = float(np.array(h['Temperature']['values']).mean())
                except Exception:
                    pass
                break
        if (i + 1) % 50 == 0:
            print(f'  indexed {i+1}/{len(folders)}', flush=True)
    json.dump(idx, open(os.path.join(root, 'temp_index.json'), 'w'), indent=0)
    print(f'indexed {len(idx)} folders')
    return idx


if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'extract':
        extract(sys.argv[2])
    elif cmd == 'index':
        index_temperatures(sys.argv[2])
