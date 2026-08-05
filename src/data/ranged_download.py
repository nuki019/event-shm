"""Resume-safe parallel HTTP range downloader for frozen public archives."""

from __future__ import annotations

import argparse
import json
import os
import queue
import re
import sys
import threading
import time
from pathlib import Path

import requests


class RangeDownloadError(RuntimeError):
    pass


def _remote_size(url: str) -> int:
    response = requests.get(url, headers={"Range": "bytes=0-0"}, timeout=(20, 60), stream=True)
    try:
        if response.status_code != 206:
            raise RangeDownloadError(f"range probe returned HTTP {response.status_code}")
        value = response.headers.get("Content-Range", "")
        match = re.fullmatch(r"bytes 0-0/(\d+)", value)
        if not match:
            raise RangeDownloadError(f"range probe lacks a usable Content-Range: {value!r}")
        return int(match.group(1))
    finally:
        response.close()


def download(url: str, output: Path, connections: int, chunk_mib: int) -> None:
    if connections <= 0 or chunk_mib <= 0:
        raise RangeDownloadError("connections and chunk_mib must be positive")
    size = _remote_size(url)
    output.parent.mkdir(parents=True, exist_ok=True)
    part = output.with_name(output.name + ".range.part")
    state_path = output.with_name(output.name + ".range.state.json")
    chunk_bytes = chunk_mib * 1024 * 1024
    chunk_count = (size + chunk_bytes - 1) // chunk_bytes
    done = set()
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            if state.get("url") == url and state.get("size") == size and state.get("chunk_bytes") == chunk_bytes:
                done = {int(index) for index in state.get("done", []) if 0 <= int(index) < chunk_count}
        except (OSError, json.JSONDecodeError, ValueError):
            done = set()
    if not part.exists():
        with part.open("wb") as handle:
            handle.truncate(size)
    elif part.stat().st_size != size:
        raise RangeDownloadError(f"partial file has unexpected size: {part}")
    work: queue.Queue[int] = queue.Queue()
    for index in range(chunk_count):
        if index not in done:
            work.put(index)
    lock = threading.Lock()
    started = time.monotonic()
    transferred = 0
    failures: list[str] = []

    def save_state() -> None:
        state_path.write_text(
            json.dumps({"url": url, "size": size, "chunk_bytes": chunk_bytes, "done": sorted(done)}, separators=(",", ":")),
            encoding="utf-8",
        )

    def worker() -> None:
        nonlocal transferred
        with part.open("r+b") as handle:
            while True:
                try:
                    index = work.get_nowait()
                except queue.Empty:
                    return
                lower = index * chunk_bytes
                upper = min((index + 1) * chunk_bytes, size) - 1
                expected = upper - lower + 1
                success = False
                for attempt in range(6):
                    try:
                        response = requests.get(
                            url,
                            headers={"Range": f"bytes={lower}-{upper}"},
                            timeout=(20, 180),
                            stream=True,
                        )
                        try:
                            if response.status_code != 206:
                                raise RangeDownloadError(f"HTTP {response.status_code}")
                            data = b"".join(response.iter_content(1024 * 1024))
                        finally:
                            response.close()
                        if len(data) != expected:
                            raise RangeDownloadError(f"short range {len(data)} != {expected}")
                        handle.seek(lower)
                        handle.write(data)
                        with lock:
                            done.add(index)
                            transferred += len(data)
                            if len(done) % 8 == 0 or len(done) == chunk_count:
                                save_state()
                                elapsed = max(time.monotonic() - started, 1e-9)
                                rate = transferred / elapsed / 1e6
                                remaining = (size - len(done) * chunk_bytes) / max(rate * 1e6, 1.0) / 60.0
                                print(f"{output.name}: {len(done)}/{chunk_count} chunks, {rate:.1f} MB/s, ETA {max(remaining, 0):.0f} min", flush=True)
                        success = True
                        break
                    except (requests.RequestException, RangeDownloadError) as error:
                        if attempt == 5:
                            with lock:
                                failures.append(f"chunk {index}: {error}")
                        else:
                            time.sleep(min(2**attempt, 20))
                if not success:
                    work.task_done()
                    return
                work.task_done()

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(connections)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    if failures or len(done) != chunk_count:
        save_state()
        raise RangeDownloadError(f"incomplete range download: {len(done)}/{chunk_count}; {failures[:3]}")
    os.replace(part, output)
    state_path.unlink(missing_ok=True)
    print(f"{output.name}: complete {size} bytes", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--connections", type=int, default=8)
    parser.add_argument("--chunk-mib", type=int, default=1)
    args = parser.parse_args()
    try:
        download(args.url, args.output, args.connections, args.chunk_mib)
    except RangeDownloadError as error:
        print(f"RANGE DOWNLOAD FAILED: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
