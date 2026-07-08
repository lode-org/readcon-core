"""CI runner for the One Good Tutorial (docs/orgmode/tutorial.org).

Walks the same Python path as the published tutorial against in-repo
fixtures. Lean ``maturin develop --features python`` is enough; chemfiles
is not required. Invoked by ``.github/workflows/ci_python.yml`` via
``pytest tests/python/``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import readcon

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "resources" / "test"
MULTI = FIXTURES / "tiny_multi_cuh2.con"
FORCES = FIXTURES / "tiny_cuh2_forces.con"


def test_tutorial_step1_iter_multi_frame():
    """Tutorial step 1: iterate every frame of tiny_multi_cuh2.con."""
    assert MULTI.is_file(), f"missing fixture {MULTI}"
    n = 0
    cells = []
    counts = []
    for frame in readcon.iter_con(str(MULTI)):
        n += 1
        cells.append(list(frame.cell))
        counts.append(len(frame))
    assert n == 2
    assert counts == [4, 4]
    assert cells[0][0] == pytest.approx(15.3456, abs=1e-4)
    assert cells[0][1] == pytest.approx(21.702, abs=1e-3)
    assert cells[0][2] == pytest.approx(100.0, abs=1e-3)


def test_tutorial_step2_inspect_identity():
    """Tutorial step 2: read_first_frame, atom_id, fixed flags, energy property."""
    frame = readcon.read_first_frame(str(MULTI))
    assert frame.spec_version >= 2
    # Property, not a method — tutorial must use frame.energy
    assert frame.energy is None
    atoms = list(frame.atoms)
    assert len(atoms) == 4
    first = atoms[0]
    assert first.symbol == "Cu"
    assert first.atom_id == 0
    assert first.is_fixed is True
    assert first.x == pytest.approx(0.6394, abs=1e-3)


def test_tutorial_step3_roundtrip(tmp_path: Path):
    """Tutorial step 3: write_con round-trip preserves frame count."""
    frames = readcon.read_con(str(MULTI))
    assert len(frames) == 2
    out = tmp_path / "tutorial_roundtrip.con"
    readcon.write_con(str(out), frames)
    again = list(readcon.iter_con(str(out)))
    assert len(again) == len(frames)
    assert len(again[0]) == 4
    assert again[0].cell[0] == pytest.approx(frames[0].cell[0], abs=1e-6)


def test_tutorial_step4_build_checkpoint_with_energy(tmp_path: Path):
    """Tutorial step 4: forces fixture + build frame with set_energy / write_con."""
    ref = readcon.read_first_frame(str(FORCES))
    assert ref.has_forces is True
    assert ref.energy == pytest.approx(-42.5)

    atoms = [
        readcon.Atom("Cu", 0.0, 0.0, 0.0, atom_id=0, mass=63.546),
        readcon.Atom("H", 1.5, 0.0, 0.0, atom_id=1, mass=1.008),
    ]
    frame = readcon.ConFrame(
        cell=[10.0, 10.0, 10.0],
        angles=[90.0, 90.0, 90.0],
        atoms=atoms,
    )
    frame.set_energy(-1.25)
    out = tmp_path / "tutorial_built.con"
    frame.write_con(str(out))

    check = readcon.read_first_frame(str(out))
    assert len(check) == 2
    assert check.energy == pytest.approx(-1.25)
    assert list(check.atoms)[0].symbol == "Cu"
    assert list(check.atoms)[1].atom_id == 1
