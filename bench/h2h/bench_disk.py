"""Disk root for benchmark outputs.

``READCON_BENCH_DISK`` selects the directory. Otherwise outputs go under
``<repo>/build/bench``. The system temporary directory is not a default:
on many hosts it is tmpfs, and a write there is not an ext4 measurement.
"""

from __future__ import annotations

import os
import secrets
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def bench_disk() -> Path:
    raw = os.environ.get("READCON_BENCH_DISK")
    root = Path(raw) if raw else REPO / "build" / "bench"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _unique(name: str) -> Path:
    root = bench_disk() / "scratch" / name
    root.mkdir(parents=True, exist_ok=True)
    path = root / secrets.token_hex(8)
    path.mkdir()
    return path


@contextmanager
def bench_scratch(name: str = "scratch") -> Iterator[str]:
    """A directory under the bench disk, removed when the block ends."""
    path = _unique(name)
    try:
        yield str(path)
    finally:
        shutil.rmtree(path, ignore_errors=True)


def release(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def bench_dir(name: str = "scratch") -> Path:
    """A new directory under the bench disk. The caller removes it."""
    return _unique(name)


def bench_file(name: str, suffix: str = "") -> Path:
    """A new file under the bench disk. The caller deletes the file.

    The name is unique inside ``scratch/<name>``. There is no per-file
    directory left behind after that delete.
    """
    root = bench_disk() / "scratch" / name
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{secrets.token_hex(8)}{suffix}"
    path.touch()
    return path
