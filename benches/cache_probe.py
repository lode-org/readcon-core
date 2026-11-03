#!/usr/bin/env python3
"""Time 1 GiB reads after a guest page-cache drop.

The virtio cache type is recorded, then each read follows ``drop_caches`` 3.
A buffered write, an ``O_DIRECT`` write, and an ``O_DIRECT|O_DSYNC`` write
each use a distinct byte pattern.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import mmap
import os
import struct
import subprocess
import time
from pathlib import Path

libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
libc.pwrite.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int64]
libc.pwrite.restype = ctypes.c_ssize_t
libc.pread.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int64]
libc.pread.restype = ctypes.c_ssize_t

# 1 GiB, 2^30 bytes, is a multiple of probe_chunk. time.perf_counter
# resolves 1 ns (time.get_clock_info). A read that lasts at least 0.18 s
# then resolves to better than 1 part in 10^8. The size is a measured
# length, above any timing floor.
SIZE = 1024 * 1024 * 1024
# 1 MiB. O_DIRECT requires a multiple of the queue logical block size.
# Row probe_chunk.
CHUNK = 1024 * 1024
# 8 MiB buffered read. A multiple of the page. Row probe_read_block.
READ_BLOCK = 8 * 1024 * 1024
# Distinct patterns. The three files then carry different bytes.
# Rows probe_seed_buffered, probe_seed_direct, probe_seed_dsync.
SEED_BUFFERED = 0xA11CE
SEED_DIRECT = 0xD1CEC7
SEED_DSYNC = 0xBEEF
# Fractional part of the golden ratio, times 2^64. A Weyl increment:
# successive 8-byte words differ. Row probe_weyl.
WEYL = 0x9E3779B97F4A7C15
ROOT = (
    Path(os.environ["WORKDIR"])
    if os.environ.get("WORKDIR")
    else Path(__file__).resolve().parent / "work"
)


def drop() -> None:
    subprocess.check_call(["sync"])
    subprocess.check_call(["sudo", "-n", "sh", "-c", "echo 3 > /proc/sys/vm/drop_caches"])
    print("after drop", flush=True)


def fill(buf: mmap.mmap | bytearray, seed: int) -> None:
    view = memoryview(buf)
    value = seed & 0xFFFFFFFFFFFFFFFF
    index = 0
    limit = len(buf)
    while index + 8 <= limit:
        struct.pack_into("<Q", view, index, value)
        value = (value + WEYL) & 0xFFFFFFFFFFFFFFFF
        index += 8


def address(buf: mmap.mmap) -> int:
    return ctypes.addressof(ctypes.c_char.from_buffer(buf))


def write_buffered(path: Path, seed: int) -> None:
    fd = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o644)
    buf = bytearray(CHUNK)
    fill(buf, seed)
    left = SIZE
    while left:
        take = min(CHUNK, left)
        os.write(fd, buf[:take])
        left -= take
    os.fsync(fd)
    os.close(fd)


def write_direct(path: Path, seed: int, extra: int = 0) -> None:
    fd = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY | os.O_DIRECT | extra, 0o644)
    buf = mmap.mmap(-1, CHUNK)
    fill(buf, seed)
    ptr = address(buf)
    off = 0
    left = SIZE
    while left:
        n = libc.pwrite(fd, ptr, min(CHUNK, left), off)
        if n <= 0:
            err = ctypes.get_errno()
            raise SystemExit(f"short pwrite {n} errno {err}")
        off += n
        left -= n
    os.fsync(fd)
    os.close(fd)
    buf.close()


def read_timed(path: Path, direct: bool) -> None:
    flags = os.O_RDONLY | (os.O_DIRECT if direct else 0)
    fd = os.open(path, flags)
    if direct:
        buf = mmap.mmap(-1, CHUNK)
        ptr = address(buf)
        t0 = time.perf_counter()
        total = 0
        while total < SIZE:
            n = libc.pread(fd, ptr, CHUNK, total)
            if n <= 0:
                err = ctypes.get_errno()
                raise SystemExit(f"short pread {n} errno {err} at {total}")
            total += n
        dt = time.perf_counter() - t0
        buf.close()
    else:
        t0 = time.perf_counter()
        total = 0
        while total < SIZE:
            block = os.read(fd, READ_BLOCK)
            if not block:
                raise SystemExit(f"short read at {total}")
            total += len(block)
        dt = time.perf_counter() - t0
    os.close(fd)
    kind = "O_DIRECT" if direct else "buffered"
    print(f"  read {kind:9} {dt:.3f}s {total / 1e6 / dt:.1f} MB/s", flush=True)


def probe(label: str, path: Path, writer, seed: int, extra: int = 0) -> None:
    print(f"\n== {label} ==", flush=True)
    t0 = time.perf_counter()
    if extra:
        writer(path, seed, extra)
    else:
        writer(path, seed)
    print(f"  write {time.perf_counter() - t0:.3f}s", flush=True)
    for name, direct in (
        ("first buffered read", False),
        ("second buffered read", False),
        ("first O_DIRECT read", True),
        ("second O_DIRECT read", True),
    ):
        drop()
        print(f"  {name}", flush=True)
        read_timed(path, direct)
    path.unlink()


def disk_node(path: Path) -> Path:
    """Parent disk for ``path``, the sysfs node for ``queue/``."""
    dev = path.stat().st_dev
    node = Path(f"/sys/dev/block/{os.major(dev)}:{os.minor(dev)}")
    if (node / "partition").is_file():
        node = (node / "..").resolve()
    return node


def sysfs_text(path: Path) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return "absent"


def main() -> None:
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    print(f"boot_id {boot}", flush=True)
    print(f"unix_time {time.time():.0f}", flush=True)
    anchor = ROOT if ROOT.exists() else ROOT.parent
    disk = disk_node(anchor)
    logical = sysfs_text(disk / "queue" / "logical_block_size")
    if logical != "absent" and CHUNK % int(logical) != 0:
        raise SystemExit(f"CHUNK {CHUNK} is not a multiple of logical_block_size {logical}")
    print("disk", disk, flush=True)
    print("write_cache", sysfs_text(disk / "queue" / "write_cache"), flush=True)
    print("cache_type", sysfs_text(disk / "cache_type"), flush=True)
    print("logical_block_size", logical, flush=True)
    existing = ROOT / "columns.conbin"
    if existing.exists():
        print("\n== existing columns.conbin first 1GiB ==", flush=True)
        drop()
        fd = os.open(existing, os.O_RDONLY)
        t0 = time.perf_counter()
        total = 0
        while total < SIZE:
            block = os.read(fd, READ_BLOCK)
            if not block:
                raise SystemExit(f"short read at {total}")
            total += len(block)
        dt = time.perf_counter() - t0
        os.close(fd)
        print(f"  read buffered {dt:.3f}s {total / 1e6 / dt:.1f} MB/s", flush=True)
    ROOT.mkdir(parents=True, exist_ok=True)
    probe("buffered unique write", ROOT / "probe-buffered.bin", write_buffered, SEED_BUFFERED)
    probe("O_DIRECT write", ROOT / "probe-direct.bin", write_direct, SEED_DIRECT)
    probe(
        "O_DIRECT|O_DSYNC write",
        ROOT / "probe-dsync.bin",
        write_direct,
        SEED_DSYNC,
        os.O_DSYNC,
    )
    print("\nDONE", flush=True)


if __name__ == "__main__":
    main()
