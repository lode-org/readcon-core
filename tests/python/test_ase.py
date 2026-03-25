import os

import pytest

ase = pytest.importorskip("ase")
import numpy as np

import readcon

RESOURCES = os.path.join(os.path.dirname(__file__), "..", "..", "resources", "test")


def _resource(fname):
    return os.path.join(RESOURCES, fname)


class TestAseAtomId:
    """atom_id roundtrip through ASE Atoms."""

    def test_to_ase_does_not_modify_tags(self):
        frames = readcon.read_con(_resource("tiny_cuh2.con"))
        ase_atoms = frames[0].to_ase()
        tags = ase_atoms.get_tags()
        # tags must remain at default (all zeros), not overwritten
        assert all(t == 0 for t in tags)

    def test_to_ase_sets_atom_id_array(self):
        frames = readcon.read_con(_resource("tiny_cuh2.con"))
        ase_atoms = frames[0].to_ase()
        atom_id_arr = ase_atoms.get_array("atom_id")
        for i, atom in enumerate(frames[0].atoms):
            assert atom_id_arr[i] == atom.atom_id

    def test_roundtrip_via_ase(self):
        frames = readcon.read_con(_resource("tiny_cuh2.con"))
        original_ids = [a.atom_id for a in frames[0].atoms]
        ase_atoms = frames[0].to_ase()
        frame_back = readcon.ConFrame.from_ase(ase_atoms)
        roundtrip_ids = [a.atom_id for a in frame_back.atoms]
        assert roundtrip_ids == original_ids

    def test_from_ase_falls_back_to_tags(self):
        atoms = ase.Atoms("CuH", positions=[[0, 0, 0], [1, 1, 1]],
                          cell=[10, 10, 10], pbc=True)
        atoms.set_tags([42, 7])
        frame = readcon.ConFrame.from_ase(atoms)
        assert frame.atoms[0].atom_id == 42
        assert frame.atoms[1].atom_id == 7

    def test_from_ase_falls_back_to_sequential(self):
        atoms = ase.Atoms("CuH", positions=[[0, 0, 0], [1, 1, 1]],
                          cell=[10, 10, 10], pbc=True)
        frame = readcon.ConFrame.from_ase(atoms)
        assert frame.atoms[0].atom_id == 0
        assert frame.atoms[1].atom_id == 1

    def test_from_ase_prefers_atom_id_over_tags(self):
        atoms = ase.Atoms("CuH", positions=[[0, 0, 0], [1, 1, 1]],
                          cell=[10, 10, 10], pbc=True)
        atoms.set_tags([99, 99])
        atoms.set_array("atom_id", np.array([10, 20]))
        frame = readcon.ConFrame.from_ase(atoms)
        assert frame.atoms[0].atom_id == 10
        assert frame.atoms[1].atom_id == 20

    def test_nonsequential_atom_id_roundtrip(self):
        atoms_list = [
            readcon.Atom(symbol="Cu", x=0.0, y=0.0, z=0.0,
                         fixed=[True, True, True], atom_id=3, mass=63.546),
            readcon.Atom(symbol="H", x=1.0, y=2.0, z=3.0,
                         fixed=[False, False, False], atom_id=1, mass=1.008),
        ]
        frame = readcon.ConFrame(
            cell=[10.0, 10.0, 10.0],
            angles=[90.0, 90.0, 90.0],
            atoms=atoms_list,
        )
        ase_atoms = frame.to_ase()
        frame_back = readcon.ConFrame.from_ase(ase_atoms)
        assert frame_back.atoms[0].atom_id == 3
        assert frame_back.atoms[1].atom_id == 1


class TestAseVelocities:
    """Velocity roundtrip through ASE Atoms."""

    def test_to_ase_sets_velocities(self):
        frames = readcon.read_con(_resource("tiny_cuh2.convel"))
        assert frames[0].has_velocities
        ase_atoms = frames[0].to_ase()
        vels = ase_atoms.get_velocities()
        assert vels is not None
        atom0 = frames[0].atoms[0]
        assert vels[0][0] == pytest.approx(atom0.vx, abs=1e-8)
        assert vels[0][1] == pytest.approx(atom0.vy, abs=1e-8)
        assert vels[0][2] == pytest.approx(atom0.vz, abs=1e-8)

    def test_to_ase_no_velocities_when_absent(self):
        frames = readcon.read_con(_resource("tiny_cuh2.con"))
        assert not frames[0].has_velocities
        ase_atoms = frames[0].to_ase()
        vels = ase_atoms.get_velocities()
        # ASE may return None or all-zero array when velocities are not set
        if vels is not None:
            assert np.allclose(vels, 0.0)

    def test_velocity_roundtrip_via_ase(self):
        frames = readcon.read_con(_resource("tiny_cuh2.convel"))
        ase_atoms = frames[0].to_ase()
        frame_back = readcon.ConFrame.from_ase(ase_atoms)
        assert frame_back.has_velocities
        for orig, back in zip(frames[0].atoms, frame_back.atoms):
            assert back.vx == pytest.approx(orig.vx, abs=1e-8)
            assert back.vy == pytest.approx(orig.vy, abs=1e-8)
            assert back.vz == pytest.approx(orig.vz, abs=1e-8)

    def test_from_ase_with_velocities(self):
        atoms = ase.Atoms("CuH", positions=[[0, 0, 0], [1, 1, 1]],
                          cell=[10, 10, 10], pbc=True)
        atoms.set_velocities([[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])
        frame = readcon.ConFrame.from_ase(atoms)
        assert frame.has_velocities
        assert frame.atoms[0].vx == pytest.approx(0.1)
        assert frame.atoms[1].vz == pytest.approx(0.6)

    def test_from_ase_no_velocities(self):
        atoms = ase.Atoms("CuH", positions=[[0, 0, 0], [1, 1, 1]],
                          cell=[10, 10, 10], pbc=True)
        frame = readcon.ConFrame.from_ase(atoms)
        assert not frame.has_velocities
        assert frame.atoms[0].vx is None


class TestAseMasses:
    """Mass roundtrip through ASE Atoms."""

    def test_to_ase_sets_masses(self):
        frames = readcon.read_con(_resource("tiny_cuh2.con"))
        ase_atoms = frames[0].to_ase()
        masses = ase_atoms.get_masses()
        cu_atom = frames[0].atoms[0]
        assert masses[0] == pytest.approx(cu_atom.mass, abs=0.01)

    def test_mass_roundtrip_via_ase(self):
        atoms_list = [
            readcon.Atom(symbol="Pt", x=0.0, y=0.0, z=0.0,
                         mass=195.08, atom_id=0),
        ]
        frame = readcon.ConFrame(
            cell=[10.0, 10.0, 10.0],
            angles=[90.0, 90.0, 90.0],
            atoms=atoms_list,
        )
        ase_atoms = frame.to_ase()
        assert ase_atoms.get_masses()[0] == pytest.approx(195.08, abs=0.01)
        frame_back = readcon.ConFrame.from_ase(ase_atoms)
        assert frame_back.atoms[0].mass == pytest.approx(195.08, abs=0.01)

    def test_convel_full_roundtrip(self):
        """Full convel -> ASE -> convel roundtrip preserving everything."""
        frames = readcon.read_con(_resource("tiny_cuh2.convel"))
        ase_atoms = frames[0].to_ase()
        frame_back = readcon.ConFrame.from_ase(ase_atoms)

        # Check all fields survived
        assert frame_back.has_velocities
        assert len(frame_back) == len(frames[0])
        for orig, back in zip(frames[0].atoms, frame_back.atoms):
            assert back.symbol == orig.symbol
            assert back.x == pytest.approx(orig.x, abs=1e-10)
            assert back.y == pytest.approx(orig.y, abs=1e-10)
            assert back.z == pytest.approx(orig.z, abs=1e-10)
            assert back.mass == pytest.approx(orig.mass, abs=0.01)
            assert back.vx == pytest.approx(orig.vx, abs=1e-8)
            assert back.vy == pytest.approx(orig.vy, abs=1e-8)
            assert back.vz == pytest.approx(orig.vz, abs=1e-8)
