"""Compressed extended XYZ round-trips through the same reader as plain text."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import readcon

PLAIN = (
    "2\n"
    'Lattice="10 0 0 0 10 0 0 0 10" Properties=species:S:1:pos:R:3 pbc="T T T"\n'
    "Cu 0.0 0.0 0.0\n"
    "H 1.5 0.0 0.0\n"
)


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
