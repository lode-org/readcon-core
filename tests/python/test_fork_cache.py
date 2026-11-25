"""A forked child can read and write after the parent has built its caches.

The parent initializes the process caches, including the Rayon pool, and
then starts a child. The child must finish. A hook registered before
`pthread_atfork` succeeds, or a pool reused across `fork`, leaves the
child blocked.

A pid alone does not tell a child from the process that built a cache.
The first process of a new PID namespace is pid 1, so a cache built by
pid 1 of one namespace and inherited by pid 1 of a nested namespace
carries the child's own pid. Only the fork epoch tells them apart.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import signal
import time
from pathlib import Path

import pytest

import readcon

SOURCE = Path(__file__).resolve().parents[2] / "resources" / "test" / "tiny_cuh2.con"

# Exit codes of the forked processes in the reused-pid test.
_NO_NAMESPACES = 77
_CHILD_HUNG = 70
_BUILDER_HUNG = 71
_WRONG_PID = 72
# A child that reuses the builder's pool has no workers and never returns.
_CHILD_TIMEOUT = 20.0


def _child(source: str, destination: str) -> int:
    frames = readcon.read_con(source, n_threads=2)
    frames[0].atoms[0].x = 1.5
    readcon.write_con(destination, frames, n_threads=2)
    return 0


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


def _write_frames(path: Path, n_frames: int = 64, n_atoms: int = 64) -> None:
    with path.open("w", encoding="ascii") as out:
        for _ in range(n_frames):
            out.write(
                "fork\n"
                '{"con_spec_version":2,"con_spec_minor":1}\n'
                f"20 20 20\n90 90 90\n0 0\n0 0\n1\n{n_atoms}\n63.546\nCu\n"
                "Coordinates of Component 1\n"
            )
            for atom in range(n_atoms):
                out.write(f"{atom * 0.01:.6f} 1.0 2.0 0 {atom}\n")


def _wait(pid: int, timeout: float) -> int | None:
    """Exit code of `pid`, or None after killing it at `timeout`."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        done, status = os.waitpid(pid, os.WNOHANG)
        if done:
            return os.waitstatus_to_exitcode(status)
        time.sleep(0.01)
    os.kill(pid, signal.SIGKILL)
    os.waitpid(pid, 0)
    return None


def _forked(main) -> int:
    """Fork, run `main` in the child, and return the child's pid."""
    pid = os.fork()
    if pid == 0:
        code = 1
        try:
            code = main()
        finally:
            os._exit(code)
    return pid


def _pid_one_child(source: str, destination: str) -> int:
    if os.getpid() != 1:
        return _WRONG_PID
    frames = readcon.read_con(source, n_threads=2)
    frames[0].atoms[0].x = 1.5
    readcon.write_con(destination, frames, n_threads=2)
    return 0


def _pid_one_builder(source: str, destination: str) -> int:
    if os.getpid() != 1:
        return _WRONG_PID
    readcon.read_con(source, n_threads=2)
    try:
        os.unshare(os.CLONE_NEWPID)
    except OSError:
        return _NO_NAMESPACES
    child = _forked(lambda: _pid_one_child(source, destination))
    code = _wait(child, _CHILD_TIMEOUT)
    return _CHILD_HUNG if code is None else code


def _namespace_root(source: str, destination: str) -> int:
    try:
        os.unshare(os.CLONE_NEWUSER | os.CLONE_NEWPID)
    except OSError:
        return _NO_NAMESPACES
    builder = _forked(lambda: _pid_one_builder(source, destination))
    code = _wait(builder, 2 * _CHILD_TIMEOUT)
    return _BUILDER_HUNG if code is None else code


def test_plain_fork_child_rebuilds_the_pool(tmp_path: Path) -> None:
    """Exercise the fork fallback without user or PID namespaces."""
    if _tsan_loaded():
        pytest.skip("TSan does not support new threads after a multi-threaded fork")
    if not hasattr(os, "fork"):
        pytest.skip("needs os.fork")
    source = tmp_path / "frames.con"
    _write_frames(source)
    parent_out = tmp_path / "parent.con"
    frames = readcon.read_con(str(source), n_threads=2)
    readcon.write_con(str(parent_out), frames, n_threads=2)
    destination = tmp_path / "plain-fork.con"
    child = _forked(lambda: _child(str(source), str(destination)))
    code = _wait(child, _CHILD_TIMEOUT)
    assert code is not None, "the plain-fork child reused the parent's pool"
    assert code == 0
    written = readcon.read_con(str(destination))
    assert written[0].atoms[0].x == 1.5


def test_fork_child_with_the_builders_pid_rebuilds_the_pool(tmp_path: Path) -> None:
    if _tsan_loaded():
        pytest.skip("TSan does not support new threads after a multi-threaded fork")
    if not hasattr(os, "unshare") or not hasattr(os, "CLONE_NEWPID"):
        pytest.skip("needs os.unshare with PID namespaces")
    source = tmp_path / "frames.con"
    _write_frames(source)
    destination = tmp_path / "pid-one.con"
    root = _forked(lambda: _namespace_root(str(source), str(destination)))
    code = _wait(root, 3 * _CHILD_TIMEOUT)
    if code == _NO_NAMESPACES:
        pytest.skip("unprivileged user and PID namespaces are unavailable")
    assert code != _CHILD_HUNG, "the pid-1 child reused the builder's Rayon pool"
    assert code == 0
    child = readcon.read_con(str(destination))
    assert child[0].atoms[0].x == 1.5


def test_forkserver_child_reads_and_writes(tmp_path: Path) -> None:
    _exercise("forkserver", tmp_path)
