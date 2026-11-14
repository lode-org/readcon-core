"""Disk root for benchmark outputs.

``READCON_BENCH_DISK`` selects the directory. Otherwise outputs go under
``<repo>/build/bench``. The system temporary directory is not a default:
on many hosts it is tmpfs, and a write there is not an ext4 measurement.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def bench_disk() -> Path:
    raw = os.environ.get("READCON_BENCH_DISK")
    root = Path(raw) if raw else REPO / "build" / "bench"
    root.mkdir(parents=True, exist_ok=True)
    return root
