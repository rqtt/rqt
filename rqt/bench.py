"""
Quick synthetic benchmarks. Not trying to compete with Cinebench - the point is
to have repeatable numbers on *your* machine so you can see whether a driver
update, an undervolt or a dusty cooler changed anything.

hashlib and zlib both release the GIL on big buffers, so plain threads give
real multi-core scaling without the multiprocessing headaches.
"""
import hashlib
import os
import random
import sys
import tempfile
import threading
import time
import zlib

TESTS = [
    # key,          label,                     unit
    ("hash_1t",    "SHA-256, single thread",   "MB/s"),
    ("hash_nt",    "SHA-256, all threads",     "MB/s"),
    ("zlib_1t",    "zlib compress, single",    "MB/s"),
    ("zlib_nt",    "zlib compress, all",       "MB/s"),
    ("mem_copy",   "Memory copy",              "GB/s"),
    ("disk_write", "Disk sequential write",    "MB/s"),
    ("disk_read",  "Disk sequential read",     "MB/s"),
]

CHUNK = 1 << 20


class Cancelled(Exception):
    pass


def _compressible(size):
    # random words, so zlib has something realistic to chew on
    rnd = random.Random(1234)
    words = [bytes(rnd.choices(range(97, 123), k=rnd.randint(2, 9))) for _ in range(4000)]
    out = bytearray()
    while len(out) < size:
        out += rnd.choice(words) + b" "
    return bytes(out[:size])


def _throughput(work, buf, threads, seconds, stop):
    done = [0] * threads
    deadline = time.perf_counter() + seconds

    def worker(i):
        n = 0
        while time.perf_counter() < deadline and not stop.is_set():
            work(buf)
            n += len(buf)
        done[i] = n

    t0 = time.perf_counter()
    pool = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(threads)]
    for t in pool:
        t.start()
    for t in pool:
        t.join()
    if stop.is_set():
        raise Cancelled
    return sum(done) / (time.perf_counter() - t0) / 1e6


def _sha(buf):
    hashlib.sha256(buf).digest()


def _zlib(buf):
    zlib.compress(buf, 6)


def mem_copy(seconds, stop, size=128 << 20):
    src = bytearray(os.urandom(1 << 20)) * (size >> 20)
    dst = bytearray(size)
    s, d = memoryview(src), memoryview(dst)
    copied = 0
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < seconds:
        if stop.is_set():
            raise Cancelled
        d[:] = s
        copied += size
    return copied / (time.perf_counter() - t0) / 1e9


def disk_rw(directory, size_mb, stop):
    block = os.urandom(4 * CHUNK)
    path = os.path.join(directory, f".rqt-bench-{os.getpid()}.tmp")
    try:
        t0 = time.perf_counter()
        with open(path, "wb", buffering=0) as f:
            for _ in range(size_mb // 4):
                if stop.is_set():
                    raise Cancelled
                f.write(block)
            os.fsync(f.fileno())
        write = size_mb / (time.perf_counter() - t0)

        cached = True
        if hasattr(os, "posix_fadvise"):
            # drop it from the page cache so the read actually hits the disk
            fd = os.open(path, os.O_RDONLY)
            os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
            os.close(fd)
            cached = False

        t0 = time.perf_counter()
        with open(path, "rb", buffering=0) as f:
            while f.read(4 * CHUNK):
                if stop.is_set():
                    raise Cancelled
        read = size_mb / (time.perf_counter() - t0)
        return write, read, cached
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def run_all(progress, stop, disk_dir=None, disk_mb=512, seconds=4):
    """progress(fraction, message) is called between tests."""
    threads = os.cpu_count() or 1
    hash_buf = os.urandom(CHUNK)
    zlib_buf = _compressible(CHUNK)
    results, notes = {}, []

    steps = [
        ("hash_1t", lambda: _throughput(_sha, hash_buf, 1, seconds, stop)),
        ("hash_nt", lambda: _throughput(_sha, hash_buf, threads, seconds, stop)),
        ("zlib_1t", lambda: _throughput(_zlib, zlib_buf, 1, seconds, stop)),
        ("zlib_nt", lambda: _throughput(_zlib, zlib_buf, threads, seconds, stop)),
        ("mem_copy", lambda: mem_copy(seconds / 2, stop)),
    ]
    labels = {k: label for k, label, _ in TESTS}
    total = len(steps) + 1

    for i, (key, fn) in enumerate(steps):
        progress(i / total, f"Running {labels[key]}…")
        results[key] = fn()

    progress(len(steps) / total, f"Writing {disk_mb} MB test file…")
    w, r, cached = disk_rw(disk_dir or tempfile.gettempdir(), disk_mb, stop)
    results["disk_write"], results["disk_read"] = w, r
    if cached:
        notes.append(f"Disk read on {sys.platform} may be served from RAM cache.")

    progress(1.0, "Done")
    return results, notes


def stress(seconds, stop, progress):
    """Pin every core for `seconds` so you can watch clocks and temps."""
    threads = os.cpu_count() or 1
    buf = os.urandom(CHUNK)
    end = time.monotonic() + seconds

    def burn():
        while time.monotonic() < end and not stop.is_set():
            hashlib.sha256(buf).digest()

    pool = [threading.Thread(target=burn, daemon=True) for _ in range(threads)]
    for t in pool:
        t.start()
    while any(t.is_alive() for t in pool):
        left = max(0, end - time.monotonic())
        progress(1 - left / seconds, f"Stressing {threads} threads, {left:.0f}s left")
        time.sleep(0.5)
    if stop.is_set():
        raise Cancelled
