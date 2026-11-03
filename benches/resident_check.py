#!/usr/bin/env python3
"""Resident pages and read rate after a guest page-cache drop.

``drop_caches`` 3 clears the guest page cache. ``posix_fadvise``
``DONTNEED`` asks the guest to drop the file's pages. ``mincore`` then
counts resident pages. The host cache is not controlled.

The work directory is ``$WORKDIR``, or ``benches/work`` when that
variable is unset.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import mmap
import os
import subprocess
import time
from pathlib import Path

libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
libc.mmap.argtypes = [
    ctypes.c_void_p,
    ctypes.c_size_t,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int64,
]
libc.mmap.restype = ctypes.c_void_p
libc.munmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
libc.munmap.restype = ctypes.c_int
libc.mincore.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p]
libc.mincore.restype = ctypes.c_int
libc.posix_fadvise.argtypes = [ctypes.c_int, ctypes.c_int64, ctypes.c_int64, ctypes.c_int]
libc.posix_fadvise.restype = ctypes.c_int
libc.pread.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int64]
libc.pread.restype = ctypes.c_ssize_t

# mmap(2): PROT_READ, MAP_SHARED. posix_fadvise(2): POSIX_FADV_DONTNEED is 4.
PROT_READ = 1
MAP_SHARED = 1
POSIX_FADV_DONTNEED = 4
# Host page. Row header_page uses sysconf(SC_PAGESIZE), which is this value.
PAGE = mmap.PAGESIZE
# 1 GiB. Same length as cache_probe.py SIZE, row probe_size.
GIB = 1024**3
# 8 MiB. Same length as cache_probe.py READ_BLOCK, row probe_read_block.
BLOCK = 8 * 1024 * 1024


def work_dir() -> Path:
    env = os.environ.get("WORKDIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent / "work"


def drop() -> None:
    subprocess.check_call(["sync"])
    subprocess.check_call(["sudo", "-n", "sh", "-c", "echo 3 > /proc/sys/vm/drop_caches"])


def resident(path: Path) -> tuple[int, int]:
    size = path.stat().st_size
    fd = os.open(path, os.O_RDONLY)
    addr = libc.mmap(None, size, PROT_READ, MAP_SHARED, fd, 0)
    if addr in (None, ctypes.c_void_p(-1).value):
        err = ctypes.get_errno()
        os.close(fd)
        raise OSError(err, os.strerror(err))
    pages = (size + PAGE - 1) // PAGE
    vec = ctypes.create_string_buffer(pages)
    rc = libc.mincore(
        ctypes.c_void_p(addr),
        ctypes.c_size_t(size),
        ctypes.cast(vec, ctypes.c_void_p),
    )
    if rc != 0:
        err = ctypes.get_errno()
        libc.munmap(ctypes.c_void_p(addr), size)
        os.close(fd)
        raise OSError(err, os.strerror(err))
    count = sum(1 for byte in vec.raw if byte & 1)
    libc.munmap(ctypes.c_void_p(addr), size)
    os.close(fd)
    return pages, count


def fadvise(path: Path) -> int:
    fd = os.open(path, os.O_RDONLY)
    rc = libc.posix_fadvise(fd, 0, 0, POSIX_FADV_DONTNEED)
    os.close(fd)
    return rc


def read_n(path: Path, nbytes: int, direct: bool) -> tuple[int, float]:
    flags = os.O_RDONLY | (os.O_DIRECT if direct else 0)
    fd = os.open(path, flags)
    buf = mmap.mmap(-1, BLOCK, prot=mmap.PROT_READ | mmap.PROT_WRITE)
    addr = ctypes.addressof(ctypes.c_char.from_buffer(buf))
    t0 = time.perf_counter()
    off = 0
    got = 0
    while got < nbytes:
        n = libc.pread(fd, ctypes.c_void_p(addr), min(BLOCK, nbytes - got), off)
        if n < 0:
            err = ctypes.get_errno()
            raise OSError(err, os.strerror(err))
        if n == 0:
            break
        got += n
        off += n
    dt = time.perf_counter() - t0
    buf.close()
    os.close(fd)
    return got, dt


def report(label: str, got: int, dt: float, resident_before: int) -> None:
    print(
        f"{label} resident_before={resident_before} bytes={got} "
        f"seconds={dt:.3f} MB/s={got / 1e6 / dt:.1f}",
        flush=True,
    )


def queue_text(path: Path, name: str) -> str:
    dev = path.stat().st_dev
    node = Path(f"/sys/dev/block/{os.major(dev)}:{os.minor(dev)}")
    if (node / "partition").is_file():
        node = (node / "..").resolve()
    q = node / "queue" / name
    try:
        return q.read_text().strip()
    except OSError:
        return "absent"


def main() -> None:
    root = work_dir()
    conbin = root / "columns.conbin"
    hdf5 = root / "columns.h5"
    print("cmd: sync; echo 3 > /proc/sys/vm/drop_caches", flush=True)
    print("cmd: mincore via mmap MAP_SHARED of the whole file", flush=True)
    print("cmd: posix_fadvise(POSIX_FADV_DONTNEED) then the same drop", flush=True)
    print(f"file {conbin} bytes {conbin.stat().st_size}", flush=True)
    drop()
    for label, path in (("conbin", conbin), ("h5", hdf5)):
        pages, count = resident(path)
        print(f"after drop {label} pages={pages} resident={count}", flush=True)
    rc = fadvise(conbin)
    print(f"posix_fadvise DONTNEED rc={rc}", flush=True)
    drop()
    pages, count = resident(conbin)
    print(f"after fadvise+drop conbin pages={pages} resident={count}", flush=True)
    got, dt = read_n(conbin, GIB, False)
    report("buffered 1GiB", got, dt, count)
    pages, count = resident(conbin)
    print(f"after that read resident={count}", flush=True)
    got, dt = read_n(conbin, GIB, False)
    print(
        f"buffered 1GiB again no drop bytes={got} seconds={dt:.3f} MB/s={got / 1e6 / dt:.1f}",
        flush=True,
    )
    drop()
    pages, count = resident(conbin)
    got, dt = read_n(conbin, GIB, True)
    report("O_DIRECT 1GiB", got, dt, count)
    size = conbin.stat().st_size
    drop()
    pages, count = resident(conbin)
    got, dt = read_n(conbin, size, False)
    report("buffered whole file", got, dt, count)
    drop()
    pages, count = resident(conbin)
    got, dt = read_n(conbin, size, False)
    report("buffered whole file second drop", got, dt, count)
    print("write_cache", queue_text(conbin, "write_cache"), flush=True)
    print("boot", Path("/proc/sys/kernel/random/boot_id").read_text().strip(), flush=True)
    print("unix", f"{time.time():.0f}", flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
