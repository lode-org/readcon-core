"""ThreadSanitizer stress for shared NumPy storage and writer snapshots."""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

import numpy as np
import readcon


assert sys._is_gil_enabled() is False

root = Path(os.environ.get("READCON_TSAN_WORK", "/tmp/readcon-tsan-writer-v3"))
root.mkdir(parents=True, exist_ok=True)
source = root / "source.con"
with source.open("w", encoding="ascii") as out:
    for frame in range(24):
        out.write(
            "tsan\n"
            '{"con_spec_version":2,"con_spec_minor":1}\n'
            "100 100 100\n90 90 90\n0 0\n0 0\n1\n1024\n63.546\nCu\n"
            "Coordinates of Component 1\n"
        )
        for atom in range(1024):
            out.write(f"{atom * 0.001:.6f} 1.0 2.0 0 {atom}\n")

frames = readcon.read_con(os.fspath(source), n_threads=2)
columns = frames.columns()
moved = frames[0]
live_coords = frames[1]
positions = columns["positions"]
cell = columns["cell"].copy()
velocities = np.zeros_like(positions)
fixed = np.zeros_like(positions)

# Exercise concurrent first initialization of the deferred Python atom list.
barrier = threading.Barrier(8)


def initialize_atoms() -> None:
    barrier.wait()
    assert len(moved.atoms) == 1024


initializers = [threading.Thread(target=initialize_atoms) for _ in range(8)]
for thread in initializers:
    thread.start()
for thread in initializers:
    thread.join()

stop = threading.Event()
started = threading.Event()


def mutate() -> None:
    version = 0
    started.set()
    while not stop.is_set():
        positions[...] = 1.0 + (version % 64) * 0.25
        cell[:, 0] = np.nan
        cell[:, 0] = 100.0
        version += 1


def read_again() -> None:
    while not stop.is_set():
        other = readcon.read_con(os.fspath(source), n_threads=2)
        assert len(other) == 24


mutator = threading.Thread(target=mutate)
reader = threading.Thread(target=read_again)
mutator.start()
reader.start()
started.wait()
try:
    for iteration in range(24):
        con = root / f"shared-{iteration}.con"
        cols = root / f"columns-{iteration}.con"
        conbin = root / f"columns-{iteration}.conbin"
        readcon.write_con(os.fspath(con), frames, n_threads=2)
        readcon.write_columns(os.fspath(cols), columns, n_threads=2)
        try:
            readcon.write_conbin_columns(
                os.fspath(conbin),
                positions,
                velocities,
                columns["masses"],
                cell,
                fixed,
            )
        except readcon.NonFiniteValue:
            pass
        else:
            mapped = readcon.read_conbin_columns(os.fspath(conbin))
            assert np.isfinite(np.asarray(mapped["cell"])).all()
        assert np.isfinite(np.asarray(live_coords.coords_array())).all()
        assert np.isfinite(readcon.read_positions(os.fspath(con), n_threads=1)).all()
        assert np.isfinite(readcon.read_positions(os.fspath(cols), n_threads=1)).all()
        digest, elapsed = frames.touch_checksum()
        assert digest >= 0 and elapsed >= 0.0
finally:
    stop.set()
    mutator.join()
    reader.join()
