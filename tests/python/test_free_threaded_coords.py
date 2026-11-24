"""Concurrent coordinate loads must not tear a double.

Run with a free-threaded CPython and ``PYTHON_GIL=0``. Other interpreters
skip this test.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest


def _gil_disabled() -> bool:
    enabled = getattr(sys, "_is_gil_enabled", None)
    return enabled is not None and not enabled()


def test_concurrent_coordinate_loads_do_not_tear(tmp_path: Path) -> None:
    if not _gil_disabled():
        pytest.skip("requires PYTHON_GIL=0 on a free-threaded build")
    import numpy as np
    import readcon

    path = tmp_path / "race.con"
    path.write_text(
        "\n"
        '{"con_spec_version":3,"con_spec_minor":1,'
        '"units":{"length":"angstrom","energy":"eV"}}\n'
        "10.000000 10.000000 10.000000\n90.000000 90.000000 90.000000\n\n\n1\n"
        "4\n63.546000\nCu\nCoordinates of Component 1\n"
        "1.000000 0.000000 0.000000 0 0\n"
        "1.000000 0.000000 0.000000 0 1\n"
        "1.000000 0.000000 0.000000 0 2\n"
        "1.000000 0.000000 0.000000 0 3\n",
        encoding="utf-8",
    )
    frame = next(readcon.iter_con(str(path)))
    whole = (1.0, 2.0)
    stop = threading.Event()
    errors: list[str] = []

    def writer() -> None:
        value = 2.0
        while not stop.is_set():
            frame.xyz[:, 0] = value
            value = 1.0 if value == 2.0 else 2.0

    def reader() -> None:
        for _ in range(2000):
            got = np.asarray(frame.coords_array())
            for value in got[:, 0]:
                if float(value) not in whole:
                    errors.append(repr(float(value)))
                    return
            view = np.asarray(frame.xyz)
            for value in view[:, 0]:
                if float(value) not in whole:
                    errors.append(repr(float(value)))
                    return

    writers = [threading.Thread(target=writer) for _ in range(2)]
    readers = [threading.Thread(target=reader) for _ in range(2)]
    for thread in writers + readers:
        thread.start()
    for thread in readers:
        thread.join()
    stop.set()
    for thread in writers:
        thread.join()
    assert errors == []
