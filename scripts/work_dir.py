"""A directory under the repository build tree, removed with the block."""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def work_dir(name: str = "work") -> Iterator[Path]:
    base = os.environ.get("RUNNER_TEMP")
    root = Path(base) if base else ROOT / "build" / "scratch"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{name}.{os.getpid()}"
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
