"""Loader for OGW#2 CFRP temperature dataset (Moll et al., Sci. Data 2019).

Reads h5 files either from an extracted tree or directly from the big zip
(avoids a full 53/27 GB extraction). Real schema per h5:
  pitchcatch/catch   (66, 13108) float64   received signals (fs=10 MHz)
  pitchcatch/pitch   (66, 13108) float64   excitation echoes
  Temperature/values (2,)                  bottom/top sensor [degC]
  command/pitchcatch/channels (66,2) uint8 actuator/sensor indices (i<j)
  command/pitchcatch/sampling_frequency (1,)
  timestamp (1,)
"""
import os, io, zipfile
import numpy as np
import h5py

FREQS_KHZ = list(range(40, 261, 20))
RAW = os.path.join(os.path.dirname(__file__), '../../data/raw')


class OGWSetZip:
    """Random access to an OGW zip without full extraction."""

    def __init__(self, zip_name):
        self.zip_path = os.path.join(RAW, zip_name)
        self.zf = zipfile.ZipFile(self.zip_path)
        self.prefix = zip_name.replace('.zip', '') + '/'
        names = [n for n in self.zf.namelist() if n.endswith('.h5')]
        # folder -> {freq: arcname}
        self.folders = {}
        for n in names:
            parts = n.split('/')
            folder = parts[1]
            freq = int(parts[2].split('pc_f')[1].split('kHz')[0])
            self.folders.setdefault(folder, {})[freq] = n
        self.folder_list = sorted(self.folders)
        self._temp = None

    def __len__(self):
        return len(self.folder_list)

    def _read_h5(self, arcname):
        return h5py.File(io.BytesIO(self.zf.read(arcname)), 'r')

    def signals(self, folder_idx, freq):
        """Return (66, 13108) float32 for a folder/frequency."""
        h = self._read_h5(self.folders[self.folder_list[folder_idx]][freq])
        x = np.array(h['pitchcatch']['catch'], dtype=np.float32)
        h.close()
        return x

    def temperature(self, folder_idx, freq=100):
        h = self._read_h5(self.folders[self.folder_list[folder_idx]][freq])
        t = float(np.array(h['Temperature']['values']).mean())
        h.close()
        return t

    def temperatures(self):
        if self._temp is None:
            self._temp = np.array([self.temperature(i) for i in range(len(self))])
        return self._temp

    def channels(self, folder_idx=0, freq=100):
        h = self._read_h5(self.folders[self.folder_list[folder_idx]][freq])
        c = np.array(h['command']['pitchcatch']['channels'])
        h.close()
        return c


def load_matrix(s: OGWSetZip, freq, idx=None):
    """Stack records: X (M, 66, N), temps (M,). Records lacking the
    requested frequency or a readable temperature are skipped."""
    idx = idx if idx is not None else range(len(s))
    Xs, Ts = [], []
    for i in idx:
        try:
            x = s.signals(i, freq)
            t = float(s.temperature(i, 100))
            if not np.isfinite(t):
                continue
            Xs.append(x); Ts.append(t)
        except Exception:
            continue
    return np.stack(Xs), np.array(Ts, dtype=float)
