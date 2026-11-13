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
