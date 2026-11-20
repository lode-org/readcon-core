"""A forked child can read and write after the parent has built its caches.

The parent initializes the process caches, including the Rayon pool, and
then starts a child. The child must finish. A hook registered before
`pthread_atfork` succeeds, or a pool reused across `fork`, leaves the
child blocked.
"""

from __future__ import annotations

import multiprocessing as mp
import os
from pathlib import Path

import pytest

import readcon

SOURCE = Path(__file__).resolve().parents[2] / "resources" / "test" / "tiny_cuh2.con"


def _child(source: str, destination: str) -> None:
    frames = readcon.read_con(source, n_threads=2)
    frames[0].atoms[0].x = 1.5
    readcon.write_con(destination, frames, n_threads=2)


def _exercise(start_method: str, tmp_path: Path) -> None:
    parent_out = tmp_path / "parent.con"
    frames = readcon.read_con(str(SOURCE), n_threads=2)
    readcon.write_con(str(parent_out), frames, n_threads=2)
    assert parent_out.is_file()
    child_out = tmp_path / f"{start_method}.con"
    context = mp.get_context(start_method)
    proc = context.Process(target=_child, args=(str(SOURCE), str(child_out)))
    proc.start()
    proc.join(30)
    assert proc.exitcode == 0
    assert child_out.is_file()
    child = readcon.read_con(str(child_out))
    assert child[0].atoms[0].x == 1.5


def _tsan_loaded() -> bool:
    preload = os.environ.get("LD_PRELOAD", "")
    if "libtsan" in preload:
        return True
    try:
        maps = Path("/proc/self/maps").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return "libtsan" in maps


def test_fork_child_reads_and_writes(tmp_path: Path) -> None:
    if _tsan_loaded():
        pytest.skip("TSan does not support new threads after a multi-threaded fork")
    _exercise("fork", tmp_path)


def test_forkserver_child_reads_and_writes(tmp_path: Path) -> None:
    _exercise("forkserver", tmp_path)
