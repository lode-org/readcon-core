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


def _zstd_write(tmp_path: Path, source: dict) -> bool:
    path = tmp_path / "zstd-probe.extxyz.zst"
    try:
        readcon.write_extxyz(str(path), source, n_threads=1)
    except ValueError as exc:
        if "zstd" in str(exc).lower():
            return False
        raise
    path.unlink()
    return True


def test_gzip_and_zstd_extxyz_round_trip(tmp_path: Path) -> None:
    plain = tmp_path / "frame.extxyz"
    plain.write_text(PLAIN)
    source = readcon.read_extxyz(str(plain), n_threads=1)
    suffixes = [".gz"]
    if _zstd_write(tmp_path, source):
        suffixes.append(".zst")
    for suffix in suffixes:
        path = tmp_path / f"frame.extxyz{suffix}"
        readcon.write_extxyz(str(path), source, n_threads=1)
        assert path.stat().st_size < plain.stat().st_size
        got = readcon.read_extxyz(str(path), n_threads=1)
        np.testing.assert_allclose(np.asarray(got["positions"]), source["positions"])
        np.testing.assert_allclose(np.asarray(got["cell"]), source["cell"])
        assert list(got["species"][0]) == list(source["species"][0])
        again = readcon.read_extxyz(str(path), n_threads=2)
        np.testing.assert_allclose(np.asarray(again["positions"]), source["positions"])
