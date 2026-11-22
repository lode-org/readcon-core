"""Threads sharing one ConFrame through `frame.atoms` and atom views.

On a free-threaded build every call below can overlap a structural
rebuild on another thread. Each one has to wait for it, never fail.
"""

from __future__ import annotations

import sysconfig
import threading

import pytest

pytestmark = pytest.mark.skipif(
    sysconfig.get_config_var("Py_GIL_DISABLED") != 1,
    reason="requires a free-threaded interpreter",
)

N_ATOMS = 6
N_WORKERS = 8
N_ROUNDS = 600
SYMBOLS = ("Cu", "H")


class Shared:
    """One frame, plus wrappers that every worker uses at once."""

    def __init__(self) -> None:
        import readcon

        atoms = [
            readcon.Atom(symbol="Cu", x=float(i), y=0.5, z=0.25, atom_id=i, mass=63.546)
            for i in range(N_ATOMS)
        ]
        self.frame = readcon.ConFrame(
            cell=[10.0, 10.0, 10.0], angles=[90.0, 90.0, 90.0], atoms=atoms
        )
        self.atoms = self.frame.atoms
        self.view = self.frame[0]
        self.held = self.frame.atoms[1]
        self.iterator = iter(self.frame)


def _read(shared: Shared, worker: int, step: int) -> None:
    import readcon

    frame = shared.frame
    i = (worker + step) % N_ATOMS
    op = step % 12
    if op == 0:
        assert len(frame.atoms) == N_ATOMS
    elif op == 1:
        assert isinstance(frame.atoms[i].x, float)
    elif op == 2:
        assert isinstance(frame[i].x, float)
    elif op == 3:
        assert sum(1 for _ in frame.atoms) == N_ATOMS
    elif op == 4:
        assert frame.coords_array().shape == (N_ATOMS, 3)
    elif op == 5:
        assert isinstance(frame[i] in frame.atoms, bool)
    elif op == 6:
        assert len([view.symbol for view in frame]) == N_ATOMS
    elif op == 7:
        assert len(shared.atoms) == N_ATOMS
        assert isinstance(shared.atoms[i].z, float)
    elif op == 8:
        assert shared.view.symbol in SYMBOLS
        assert isinstance(shared.held.x, float)
    elif op == 9:
        next(shared.iterator, None)
    elif op == 10:
        assert frame == shared.frame
        assert frame.cell == [10.0, 10.0, 10.0]
        assert "natoms=" in repr(frame)
    else:
        try:
            perm = readcon.atom_id_permutation(frame, frame, strict=False)
        except readcon.ValidationError:
            # Assignments copy atom ids, so ids can repeat.
            return
        assert sorted(perm) == list(range(N_ATOMS))


def _write(shared: Shared, worker: int, step: int) -> None:
    import readcon

    frame = shared.frame
    i = (worker + step) % N_ATOMS
    j = (worker * 3 + step) % N_ATOMS
    value = float(worker * 1000 + step)
    op = step % 12
    if op == 0:
        frame[i].x = value
    elif op == 1:
        frame.atoms[i].y = value
    elif op == 2:
        frame.atoms[i] = frame.atoms[j]
    elif op == 3:
        frame.atoms[i] = frame[j]
    elif op == 4:
        frame[i] = readcon.Atom(
            symbol="Cu", x=value, y=0.5, z=0.25, atom_id=i, mass=63.546
        )
    elif op == 5:
        frame.atoms[0:2] = [frame.atoms[1], frame.atoms[0]]
    elif op == 6:
        frame[i].symbol = SYMBOLS[step % 2]
    elif op == 7:
        frame[i].vx = value
    elif op == 8:
        shared.atoms[i] = shared.atoms[j]
    elif op == 9:
        shared.view.z = value
        shared.held.x = value
    elif op == 10:
        frame.set_energy(value)
    else:
        frame.atoms[i] = shared.held


def test_shared_frame_atoms_never_fail_under_threads() -> None:
    shared = Shared()
    barrier = threading.Barrier(N_WORKERS)
    failures: list[BaseException] = []
    lock = threading.Lock()

    def run(worker: int) -> None:
        barrier.wait()
        op = _write if worker % 2 else _read
        try:
            for step in range(N_ROUNDS):
                op(shared, worker, step)
        # A borrow panic surfaces as pyo3's PanicException, a BaseException.
        except BaseException as err:  # noqa: BLE001
            with lock:
                failures.append(err)

    threads = [threading.Thread(target=run, args=(w,)) for w in range(N_WORKERS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120.0)
    assert not any(thread.is_alive() for thread in threads), "a worker hung"
    assert not failures, [f"{type(err).__name__}: {err}" for err in failures[:5]]
    frame = shared.frame
    assert len(frame.atoms) == N_ATOMS
    assert frame.coords_array().shape == (N_ATOMS, 3)
    for i in range(N_ATOMS):
        assert frame.atoms[i] is frame.atoms[i]
        assert frame[i].x == frame.atoms[i].x
