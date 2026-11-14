"""Bench-disk helpers for scripts under this repository.

A script adds the repository root to ``sys.path`` and imports this module.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_DISK = Path(__file__).resolve().parent / "bench" / "h2h" / "bench_disk.py"
_spec = importlib.util.spec_from_file_location("readcon_bench_disk", _DISK)
if _spec is None or _spec.loader is None:
    raise ImportError(f"cannot load {_DISK}")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

bench_disk = _mod.bench_disk
bench_scratch = _mod.bench_scratch
bench_dir = _mod.bench_dir
bench_file = _mod.bench_file
release = _mod.release
