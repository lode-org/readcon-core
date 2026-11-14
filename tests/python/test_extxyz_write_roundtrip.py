# Copyright (c) readcon-core developers
"""The extended XYZ writer round-trips the committed fixtures."""

from pathlib import Path

import numpy as np
import pytest
import readcon

FIXTURES = Path(__file__).resolve().parents[2] / "bench" / "h2h" / "fixtures"


def _same(left, right, tol=1e-9):
    assert np.asarray(left, dtype=np.float64) == pytest.approx(
        np.asarray(right, dtype=np.float64), abs=tol
    )


@pytest.mark.parametrize("name", ["small-1.extxyz", "small-n.extxyz"])
def test_write_rereads_with_readcon(tmp_path, name):
    original = readcon.read_extxyz(str(FIXTURES / name))
    out = tmp_path / name
    readcon.write_extxyz(str(out), original)
    again = readcon.read_extxyz(str(out))
    assert again["species"] == original["species"]
    _same(again["positions"], original["positions"])
    _same(again["masses"], original["masses"])
    _same(again["cell"], original["cell"], tol=1e-6)
    _same(again["arrays"]["forces"], original["arrays"]["forces"])


def _hwm_kib() -> int:
    for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
        if line.startswith("VmHWM:"):
            return int(line.split()[1])
    raise AssertionError("VmHWM")


def test_write_does_not_copy_numeric_columns(tmp_path):
    """The writer formats the caller's arrays in place.

    A second owned copy of the positions, masses and forces would raise
    the process high-water mark by about that many bytes on top of the
    output buffer. The bound is the file plus three quarters of the
    numeric payload, which still sits under one extra copy.
    """
    n_atoms = 250_000
    positions = np.zeros((1, n_atoms, 3), dtype=np.float64)
    masses = np.full((1, n_atoms), 63.546, dtype=np.float64)
    forces = np.zeros((1, n_atoms, 3), dtype=np.float64)
    positions[0, -1, 2] = 1.25
    forces[0, 1, 0] = 0.25
    species = [["Cu"] * n_atoms]
    data = {
        "positions": positions,
        "masses": masses,
        "cell": np.array([[30.0, 30.0, 30.0, 90.0, 90.0, 90.0]], dtype=np.float64),
        "species": species,
        "arrays": {
            "species": species,
            "pos": np.array(positions, copy=True),
            "masses": np.array(masses, copy=True),
            "forces": np.array(forces, copy=True),
        },
    }
    numeric = (
        data["arrays"]["pos"].nbytes
        + data["arrays"]["masses"].nbytes
        + data["arrays"]["forces"].nbytes
    )
    float(positions.sum() + masses.sum() + forces.sum())
    before = _hwm_kib()
    out = tmp_path / "wide.extxyz"
    readcon.write_extxyz(str(out), data)
    growth = (_hwm_kib() - before) * 1024
    file_size = out.stat().st_size
    assert growth < file_size + (numeric * 3) // 4, (growth, file_size, numeric)
    again = readcon.read_extxyz(str(out))
    assert again["species"][0][-1] == "Cu"
    assert again["positions"][0, -1, 2] == pytest.approx(1.25)
    assert again["arrays"]["forces"][0, 1, 0] == pytest.approx(0.25)


def test_write_rereads_with_ase_and_extxyz(tmp_path):
    pytest.importorskip("ase")
    pytest.importorskip("extxyz")
    import extxyz
    from ase.io import read as ase_read

    from ase.io.formats import ioformats

    original = readcon.read_extxyz(str(FIXTURES / "small-1.extxyz"))
    out = tmp_path / "small-1.extxyz"
    readcon.write_extxyz(str(out), original)
    # ASE 3.29 registers its own reader as extxyz. Older builds register
    # the libAtoms reader as cextxyz. Use whichever names this ASE has.
    registered = [name for name in ("extxyz", "cextxyz") if name in ioformats]
    assert registered, "ASE did not register an extended XYZ reader"
    for fmt in registered:
        image = ase_read(str(out), index=0, format=fmt)
        assert image.get_chemical_symbols() == list(original["species"][0])
        _same(image.positions, original["positions"][0])
        forces = (
            image.get_forces() if image.calc is not None else image.arrays["forces"]
        )
        _same(forces, original["arrays"]["forces"][0])
        _same(image.cell.lengths(), original["cell"][0, :3], tol=1e-6)
        _same(image.cell.angles(), original["cell"][0, 3:], tol=1e-6)
    frame = extxyz.read_dicts(str(out))
    frame = frame[0] if isinstance(frame, list) else frame
    assert list(frame.arrays["species"]) == list(original["species"][0])
    _same(frame.arrays["pos"], original["positions"][0])
    _same(frame.arrays["forces"], original["arrays"]["forces"][0])
    _same(frame.arrays["masses"], original["masses"][0])
