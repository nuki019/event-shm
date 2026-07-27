"""Loader for the OGW#2 CFRP temperature dataset (Moll et al., Sci. Data 2019).

Expected layout after extraction:
  root/
    OGW_CFRP_Temperature_udam/           (or ..._dam_D04 etc.)
      Data/
        <measurement_folder>/            (one per temperature point)
          pc_f40kHz.h5 ... pc_f260kHz.h5

Each h5 file contains:
  /pitchcatch/catch              (n_samples, n_channels) pitch-catch signals
  /Temperature/values            (2,) bottom/top temperature [degC]
  /command/pitchcatch/channels   (2, n_channels) transducer pair IDs
"""
import os, re, json
import numpy as np
import h5py

FREQS_KHZ = list(range(40, 261, 20))
FS = 10e6


class OGWSet:
    def __init__(self, root, condition='udam'):
        """root: extracted dataset dir containing Data/ ; condition label."""
        self.root = root
        self.condition = condition
        self.data_dir = os.path.join(root, 'Data') if os.path.isdir(os.path.join(root, 'Data')) else root
        self.folders = self._find_folders()
        self._temp_cache = None
        self._channels = None

    def _find_folders(self):
        out = []
        for name in sorted(os.listdir(self.data_dir)):
            d = os.path.join(self.data_dir, name)
            if not os.path.isdir(d):
                continue
            if any(f.startswith('pc_f') and f.endswith('.h5') for f in os.listdir(d)):
                out.append(d)
        return out

    def __len__(self):
        return len(self.folders)

    def h5_path(self, folder_idx, freq_khz):
        return os.path.join(self.folders[folder_idx], f'pc_f{freq_khz}kHz.h5')

    def temperature(self, folder_idx, freq_khz=100):
        with h5py.File(self.h5_path(folder_idx, freq_khz), 'r') as f:
            v = np.array(f['Temperature']['values']).ravel()
        return float(v.mean())

    def temperatures(self):
        if self._temp_cache is None:
            self._temp_cache = np.array([self.temperature(i) for i in range(len(self))])
        return self._temp_cache

    def channels(self, folder_idx=0, freq_khz=100):
        if self._channels is None:
            with h5py.File(self.h5_path(folder_idx, freq_khz), 'r') as f:
                self._channels = np.array(f['command']['pitchcatch']['channels'])
        return self._channels

    def signals(self, folder_idx, freq_khz):
        """Return (n_samples, n_channels) float array."""
        with h5py.File(self.h5_path(folder_idx, freq_khz), 'r') as f:
            return np.array(f['pitchcatch']['catch'])

    def summary(self):
        info = {'root': self.root, 'condition': self.condition,
                'n_measurements': len(self)}
        if len(self):
            with h5py.File(self.h5_path(0, 100), 'r') as f:
                info['h5_keys'] = list(f.keys())
                info['catch_shape'] = list(f['pitchcatch']['catch'].shape)
        return info


def discover_sets(raw_root):
    """Find extracted OGW sets under data/raw/."""
    sets = {}
    for name in sorted(os.listdir(raw_root)):
        m = re.match(r'OGW_CFRP_Temperature_(udam|dam_\w+)', name)
        if m:
            sets[m.group(1)] = os.path.join(raw_root, name)
    return sets
