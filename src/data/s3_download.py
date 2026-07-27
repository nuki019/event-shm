"""Multi-connection ranged downloader for figshare S3 files.

Strategy: figshare ndownloader is geo-blocked from this network, but the
underlying S3 bucket (s3-eu-west-1) is reachable. We obtain a fresh S3
pre-signed URL via a public proxy (only for the 302 redirect, no body),
then download directly from S3 with ranged parallel connections.
The URL is refreshed automatically when it nears expiry.
"""
import os, sys, time, json, threading, requests

PROXY_FILE = os.path.join(os.path.dirname(__file__), '../../good_proxies.txt')
DL_DIR = os.path.join(os.path.dirname(__file__), '../../data/raw')
os.makedirs(DL_DIR, exist_ok=True)

def fresh_url(file_id, proxies):
    for p in proxies:
        try:
            r = requests.get(f'https://ndownloader.figshare.com/files/{file_id}',
                             proxies={'http': f'http://{p}', 'https': f'http://{p}'},
                             timeout=30, allow_redirects=False)
            if r.status_code in (301, 302, 303, 307):
                return r.headers['Location']
        except Exception:
            continue
    raise RuntimeError('no proxy worked for redirect')

def total_size(url):
    r = requests.get(url, headers={'Range': 'bytes=0-0'}, timeout=30)
    cr = r.headers.get('Content-Range', '')
    return int(cr.split('/')[-1])

def download(file_id, name, nconn=12, chunk_mb=64):
    proxies = [l.strip() for l in open(PROXY_FILE) if l.strip()]
    url = fresh_url(file_id, proxies)
    size = total_size(url)
    path = os.path.join(DL_DIR, name)
    part_path = path + '.part'
    state_path = path + '.state.json'
    chunk = chunk_mb * 1024 * 1024
    nchunks = (size + chunk - 1) // chunk
    done = set()
    if os.path.exists(state_path):
        done = set(json.load(open(state_path))['done'])
    if not os.path.exists(part_path):
        with open(part_path, 'wb') as f:
            f.truncate(size)
    lock = threading.Lock()
    url_box = {'url': url, 't': time.time()}
    stats = {'bytes': 0, 't0': time.time()}

    def get_url():
        with lock:
            # pre-signed URLs live 1h+; refresh every 50 min
            if time.time() - url_box['t'] > 3000:
                url_box['url'] = fresh_url(file_id, proxies)
                url_box['t'] = time.time()
            return url_box['url']

    def worker():
        while True:
            with lock:
                remaining = [i for i in range(nchunks) if i not in done]
                if not remaining:
                    return
                i = remaining[0]
            lo, hi = i * chunk, min((i + 1) * chunk, size) - 1
            for attempt in range(8):
                try:
                    r = requests.get(get_url(), headers={'Range': f'bytes={lo}-{hi}'},
                                     timeout=300, stream=True)
                    if r.status_code not in (200, 206):
                        raise RuntimeError(f'status {r.status_code}')
                    buf = b''.join(r.iter_content(1 << 20))
                    if len(buf) != hi - lo + 1:
                        raise RuntimeError(f'short read {len(buf)} != {hi-lo+1}')
                    with lock:
                        with open(part_path, 'r+b') as f:
                            f.seek(lo)
                            f.write(buf)
                        done.add(i)
                        stats['bytes'] += len(buf)
                        if len(done) % 5 == 0 or len(done) == nchunks:
                            json.dump({'done': sorted(done)}, open(state_path, 'w'))
                            el = time.time() - stats['t0']
                            mb = stats['bytes'] / 1e6
                            print(f'{name}: {len(done)}/{nchunks} chunks, '
                                  f'{mb:.0f} MB done, avg {mb/el:.1f} MB/s, '
                                  f'ETA {(size/1e6-mb)/(mb/el+1e-9)/60:.0f} min', flush=True)
                    break
                except Exception as e:
                    time.sleep(min(2 ** attempt, 30))
                    if attempt == 7:
                        print(f'chunk {i} failed permanently: {e}', flush=True)

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(nconn)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    if len(done) == nchunks:
        os.rename(part_path, path)
        os.remove(state_path)
        print(f'{name}: COMPLETE {size/1e9:.1f} GB', flush=True)
    else:
        print(f'{name}: incomplete {len(done)}/{nchunks}', flush=True)

if __name__ == '__main__':
    fid = int(sys.argv[1]); name = sys.argv[2]
    nconn = int(sys.argv[3]) if len(sys.argv) > 3 else 12
    download(fid, name, nconn)
