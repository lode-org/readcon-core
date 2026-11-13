"""Bulk CON columns match the serial Rust read, field by field.

``ConFrameList.columns`` fills one NumPy array per field from the parsed
frames. ``write_columns`` reads those arrays back. Walking ``frame.atoms``
is the slow path these tests keep as the oracle.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np


def _write_convel(path: Path) -> None:
    path.write_text(
        "bulk\n"
        '{"con_spec_version":2}\n'
        "4.000000 5.000000 6.000000\n"
        "90.000000 90.000000 90.000000\n"
        "0 0\n"
        "0 0\n"
        "1\n"
        "4\n"
        "63.546000\n"
        "Cu\n"
        "Coordinates of Component 1\n"
        " 0.000000 0.000000 0.000000 7 0\n"
        " 1.000000 0.000000 0.000000 0 1\n"
        " 0.000000 1.000000 0.000000 1 2\n"
        " 1.000000 1.000000 1.000000 0 3\n"
        "\n"
        "Cu\n"
        "Velocities of Component 1\n"
        " 0.000000 0.000000 0.000000 7 0\n"
        " 0.125000 -0.250000 0.500000 0 1\n"
        " -0.125000 0.250000 -0.500000 1 2\n"
        " 0.250000 0.000000 0.000000 0 3\n"
        "\n",
        encoding="utf-8",
    )


def test_columns_match_serial_rust_and_atoms(tmp_path: Path) -> None:
    import readcon

    path = tmp_path / "four.convel"
    _write_convel(path)
    serial = np.asarray(readcon.read_positions(str(path), n_threads=1))
    frames = readcon.read_con(str(path), n_threads=1)
    cols = frames.columns()
    positions = np.asarray(cols["positions"])
    assert positions.tobytes() == serial.tobytes()
    masses = np.asarray(cols["masses"])
    fixed = np.asarray(cols["fixed"])
    velocities = np.asarray(cols["velocities"])
    assert cols["forces"] is None
    for index, frame in enumerate(frames):
        assert np.array_equal(positions[index], np.asarray(frame.xyz))
        atom_mass = np.array([float(atom.mass) for atom in frame.atoms])
        atom_fixed = np.array(
            [[1.0 if flag else 0.0 for flag in atom.fixed] for atom in frame.atoms]
        )
        assert masses[index].tobytes() == atom_mass.tobytes()
        assert fixed[index].tobytes() == atom_fixed.tobytes()
        assert velocities[index].tobytes() == np.asarray(frame.vel).tobytes()


def test_write_columns_keeps_distinct_masses(tmp_path: Path) -> None:
    import readcon

    src = tmp_path / "in.convel"
    dst = tmp_path / "out.convel"
    _write_convel(src)
    frames = readcon.read_con(str(src), n_threads=1)
    cols = frames.columns()
    cols["masses"][0] = [1.0, 1.0, 12.0, 12.0]
    readcon.write_columns(str(dst), cols, n_threads=1)
    again = readcon.read_con(str(dst), n_threads=1).columns()
    assert np.array_equal(again["masses"][0], [1.0, 1.0, 12.0, 12.0])
    assert np.array_equal(again["positions"], cols["positions"])
    assert np.array_equal(again["velocities"], cols["velocities"])


def test_columns_can_run_beside_a_frame_index(tmp_path: Path) -> None:
    import threading

    import readcon

    path = tmp_path / "wide.con"
    n_atoms = 20000
    lines = [
        "wide",
        '{"con_spec_version":2}',
        "10.0 10.0 10.0",
        "90.0 90.0 90.0",
        "0 0",
        "0 0",
        "1",
        str(n_atoms),
        "63.546",
        "Cu",
        "Coordinates of Component 1",
    ]
    lines.extend(f" {i}.0 0.0 0.0 0 {i}" for i in range(n_atoms))
    lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    frames = readcon.read_con(str(path), n_threads=1)
    stop = threading.Event()

    def index_frames() -> None:
        while not stop.is_set():
            _ = len(frames)

    thread = threading.Thread(target=index_frames)
    thread.start()
    try:
        for _ in range(8):
            cols = frames.columns()
            assert cols["positions"].shape == (1, n_atoms, 3)
    finally:
        stop.set()
        thread.join(timeout=10)
    assert not thread.is_alive()


def test_write_columns_round_trip(tmp_path: Path) -> None:
    import readcon

    src = tmp_path / "in.convel"
    dst = tmp_path / "out.convel"
    _write_convel(src)
    frames = readcon.read_con(str(src), n_threads=1)
    cols = frames.columns()
    readcon.write_columns(str(dst), cols, n_threads=1)
    again = readcon.read_con(str(dst), n_threads=1).columns()
    for key in ("positions", "masses", "fixed", "cell", "velocities"):
        assert np.asarray(again[key]).tobytes() == np.asarray(cols[key]).tobytes()
