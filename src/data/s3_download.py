"""Multi-connection ranged downloader for figshare S3 files (v2).

figshare ndownloader 302-redirects to S3 pre-signed URLs that live only
~10 s. The S3 endpoint itself is reachable directly; only the redirect
needs a proxy. Therefore every chunk request fetches a fresh URL via a
proxy pool (cheap, no body), then downloads directly from S3.
"""
import os, sys, time, json, threading, queue, requests

HERE = os.path.dirname(__file__)
PROXY_FILE = os.path.join(HERE, '../../good_proxies.txt')
DL_DIR = os.path.join(HERE, '../../data/raw')
os.makedirs(DL_DIR, exist_ok=True)


class UrlPool:
    def __init__(self, file_id, proxies):
        self.file_id = file_id
        self.proxies = proxies
        self.lock = threading.Lock()
        self.idx = 0

    def fresh(self, tries=10):
        for _ in range(tries):
            with self.lock:
                p = self.proxies[self.idx % len(self.proxies)]
                self.idx += 1
            try:
                r = requests.get(f'https://ndownloader.figshare.com/files/{self.file_id}',
                                 proxies={'http': f'http://{p}', 'https': f'http://{p}'},
                                 timeout=20, allow_redirects=False)
                if r.status_code in (301, 302, 303, 307):
                    return r.headers['Location']
            except Exception:
                continue
        raise RuntimeError('no proxy gave a redirect')


def total_size(pool):
    url = pool.fresh()
    r = requests.get(url, headers={'Range': 'bytes=0-0'}, timeout=30)
    return int(r.headers['Content-Range'].split('/')[-1])


def download(file_id, name, nconn=16, chunk_mb=32):
    proxies = [l.strip() for l in open(PROXY_FILE) if l.strip()]
    pool = UrlPool(file_id, proxies)
    size = total_size(pool)
    path = os.path.join(DL_DIR, name)
    part_path = path + '.part'
    state_path = path + '.state.json'
    chunk = chunk_mb * 1024 * 1024
    nchunks = (size + chunk - 1) // chunk
    done = set(json.load(open(state_path))['done']) if os.path.exists(state_path) else set()
    if not os.path.exists(part_path):
        with open(part_path, 'wb') as f:
            f.truncate(size)
    q = queue.Queue()
    for i in range(nchunks):
        if i not in done:
            q.put(i)
    lock = threading.Lock()
    stats = {'bytes': 0, 't0': time.time(), 'fail': 0}

    def worker():
        fh = open(part_path, 'r+b')
        while True:
            try:
                i = q.get_nowait()
            except queue.Empty:
                fh.close(); return
            lo, hi = i * chunk, min((i + 1) * chunk, size) - 1
            ok = False
            for attempt in range(10):
                try:
                    url = pool.fresh()
                    r = requests.get(url, headers={'Range': f'bytes={lo}-{hi}'},
                                     timeout=(20, 180), stream=True)
                    if r.status_code not in (200, 206):
                        raise RuntimeError(f'status {r.status_code}')
                    buf = bytearray()
                    for part in r.iter_content(1 << 20):
                        buf.extend(part)
                    if len(buf) != hi - lo + 1:
                        raise RuntimeError(f'short read {len(buf)}')
                    fh.seek(lo); fh.write(bytes(buf))
                    with lock:
                        done.add(i)
                        stats['bytes'] += len(buf)
                        if len(done) % 10 == 0 or len(done) == nchunks:
                            json.dump({'done': sorted(done)}, open(state_path, 'w'))
                            el = time.time() - stats['t0']
                            mb = stats['bytes'] / 1e6
                            print(f'{name}: {len(done)}/{nchunks} chunks, {mb:.0f} MB, '
                                  f'avg {mb/el:.1f} MB/s, ETA {(size/1e6-mb)/(mb/el+1e-9)/60:.0f} min',
                                  flush=True)
                    ok = True
                    break
                except Exception as e:
                    with lock:
                        stats['fail'] += 1
                    time.sleep(min(2 ** attempt, 20))
            if not ok:
                print(f'chunk {i} FAILED permanently', flush=True)
            q.task_done()

    ths = [threading.Thread(target=worker, daemon=True) for _ in range(nconn)]
    [t.start() for t in ths]
    [t.join() for t in ths]
    if len(done) == nchunks:
        os.rename(part_path, path)
        os.remove(state_path)
        print(f'{name}: COMPLETE {size/1e9:.1f} GB, fails={stats["fail"]}', flush=True)
        return True
    print(f'{name}: incomplete {len(done)}/{nchunks}', flush=True)
    return False


if __name__ == '__main__':
    fid, name = int(sys.argv[1]), sys.argv[2]
    nconn = int(sys.argv[3]) if len(sys.argv) > 3 else 16
    ok = download(fid, name, nconn)
    sys.exit(0 if ok else 1)
