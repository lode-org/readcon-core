"""CON frames expose ASE geometry and cached results in ASE units."""

import numpy as np
import pytest
from ase import Atoms, units

import readcon


def test_to_ase_converts_geometry_forces_and_energy():
    cell = np.array([[10.0, 1.0, 0.0], [0.0, 11.0, 1.0], [1.0, 0.0, 12.0]])
    frame = readcon.ConFrame(
        cell=[10, 11, 12],
        angles=[90, 90, 90],
        atoms=[
            readcon.Atom(
                symbol="H",
                x=1,
                y=2,
                z=3,
                mass=2.014,
                atom_id=41,
                fx=0.1,
                fy=0.2,
                fz=0.3,
            )
        ],
        metadata={
            "units": {"length": "bohr", "energy": "hartree", "mass": "amu"},
            "lattice_vectors": cell.tolist(),
            "pbc": [True, False, True],
            "energy": -0.5,
        },
    )
    atoms = frame.to_ase()
    np.testing.assert_allclose(atoms.positions, np.array([[1, 2, 3]]) * units.Bohr)
    np.testing.assert_allclose(atoms.cell, cell * units.Bohr)
    np.testing.assert_array_equal(atoms.pbc, [True, False, True])
    np.testing.assert_array_equal(atoms.arrays["atom_id"], [41])
    assert atoms.get_masses()[0] == pytest.approx(2.014)
    assert atoms.get_potential_energy() == pytest.approx(-0.5 * units.Hartree)
    assert atoms.info["energy"] == pytest.approx(-0.5 * units.Hartree)
    np.testing.assert_allclose(
        atoms.get_forces(), np.array([[0.1, 0.2, 0.3]]) * units.Hartree / units.Bohr
    )
    assert frame.energy == -0.5
    np.testing.assert_array_equal(frame.xyz, [[1, 2, 3]])


def test_to_ase_keeps_energy_without_force_section():
    frame = readcon.ConFrame(
        cell=[10, 10, 10],
        angles=[90, 90, 90],
        atoms=[readcon.Atom(symbol="H", x=0, y=0, z=0, atom_id=0)],
        metadata={"energy": 2.5},
    )
    atoms = frame.to_ase()
    assert atoms.get_potential_energy() == 2.5
    assert "forces" not in atoms.calc.results


def test_ase_roundtrip_keeps_full_cell_and_open_axes(tmp_path):
    original = Atoms(
        "He",
        positions=[[1, 2, 3]],
        cell=[[5, 1, 0], [0, 6, 1], [1, 0, 7]],
        pbc=[False, True, False],
    )
    frame = readcon.ConFrame.from_ase(original)
    path = tmp_path / "frame.con"
    readcon.write_con(str(path), [frame])
    restored = readcon.read_first_frame(str(path)).to_ase()
    np.testing.assert_allclose(restored.positions, original.positions)
    np.testing.assert_allclose(restored.cell, original.cell)
    np.testing.assert_array_equal(restored.pbc, original.pbc)


def test_v31_velocity_uses_declared_time():
    frame = readcon.ConFrame(
        cell=[10, 10, 10],
        angles=[90, 90, 90],
        atoms=[
            readcon.Atom(symbol="H", x=0, y=0, z=0, mass=1, atom_id=0, vx=1, vy=2, vz=3)
        ],
        metadata={
            "con_spec_minor": 1,
            "units": {"length": "bohr", "energy": "hartree", "time": "fs"},
        },
    )
    np.testing.assert_allclose(
        frame.to_ase().get_velocities(), np.array([[1, 2, 3]]) * units.Bohr / units.fs
    )


def test_to_ase_rejects_dimensionally_invalid_length():
    frame = readcon.ConFrame(
        cell=[10, 10, 10],
        angles=[90, 90, 90],
        atoms=[],
        metadata={"units": {"length": "eV", "energy": "eV"}},
    )
    with pytest.raises(ValueError, match="incompatible units"):
        frame.to_ase()
