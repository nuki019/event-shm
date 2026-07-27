"""Extract OGW zip and probe HDF5 structure (first file)."""
import os, sys, zipfile, json

RAW = os.path.join(os.path.dirname(__file__), '../../data/raw')

def extract(zip_name, out_dir=None):
    zp = os.path.join(RAW, zip_name)
    out_dir = out_dir or os.path.join(RAW, zip_name.replace('.zip', ''))
    os.makedirs(out_dir, exist_ok=True)
    with zipfile.ZipFile(zp) as z:
        names = z.namelist()
        print(f'{zip_name}: {len(names)} entries')
        for i, n in enumerate(names):
            z.extract(n, out_dir)
            if (i + 1) % 500 == 0:
                print(f'  {i+1}/{len(names)}', flush=True)
    print('extracted to', out_dir)
    return out_dir

def probe(root):
    """Print structure of the first pc_fXXkHz.h5 found."""
    import h5py
    for dirpath, _, files in os.walk(root):
        for f in files:
            if f.startswith('pc_f') and f.endswith('.h5'):
                p = os.path.join(dirpath, f)
                print('probing', p)
                with h5py.File(p, 'r') as h:
                    def visit(name, obj):
                        try:
                            if hasattr(obj, 'shape'):
                                print(f'  {name}: {obj.shape} {obj.dtype}')
                            else:
                                print(f'  {name}/ (group)')
                        except Exception as e:
                            print(f'  {name}: <err {e}>')
                    h.visititems(visit)
                return p

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'extract':
        extract(sys.argv[2])
    elif len(sys.argv) > 1 and sys.argv[1] == 'probe':
        probe(sys.argv[2])
