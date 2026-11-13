"""Compressed extended XYZ round-trips through the same reader as plain text."""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import readcon

PLAIN = (
    "2\n"
    'Lattice="10 0 0 0 10 0 0 0 10" Properties=species:S:1:pos:R:3 pbc="T T T"\n'
    "Cu 0.0 0.0 0.0\n"
    "H 1.5 0.0 0.0\n"
)


def test_million_pattern_formula_stays_on_the_stored_atoms(tmp_path: Path) -> None:
    """The formula of a parsed frame must not rebuild every atom.

    The previous getter copied each symbol into a new frame. On a
    million-atom file that copy was about half a second and varied by
    tens of percent.
    """
    n = 8_000
    lines = [
        "grid",
        '{"con_spec_version":2}',
        "20 20 20",
        "90 90 90",
        "0 0",
        "0 0",
        "1",
        str(n),
        "63.546",
        "Cu",
        "Coordinates of Component 1",
    ]
    lines.extend(f"0 0 0 0 {i}" for i in range(n))
    path = tmp_path / "wide.con"
    path.write_text("\n".join(lines) + "\n")
    frame = readcon.read_con(str(path))[0]
    started = time.perf_counter()
    formula = frame.composition_formula
    elapsed = time.perf_counter() - started
    assert formula == f"Cu:{n}"
    assert elapsed < 0.05, elapsed


def test_gzip_and_zstd_extxyz_round_trip(tmp_path: Path) -> None:
    plain = tmp_path / "frame.extxyz"
    plain.write_text(PLAIN)
    source = readcon.read_extxyz(str(plain), n_threads=1)
    for suffix in (".gz", ".zst"):
        path = tmp_path / f"frame.extxyz{suffix}"
        readcon.write_extxyz(str(path), source, n_threads=1)
        assert path.stat().st_size < plain.stat().st_size
        got = readcon.read_extxyz(str(path), n_threads=1)
        np.testing.assert_allclose(np.asarray(got["positions"]), source["positions"])
        np.testing.assert_allclose(np.asarray(got["cell"]), source["cell"])
        assert list(got["species"][0]) == list(source["species"][0])
        again = readcon.read_extxyz(str(path), n_threads=2)
        np.testing.assert_allclose(np.asarray(again["positions"]), source["positions"])
