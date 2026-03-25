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

    def test_to_ase_sets_tags(self):
        frames = readcon.read_con(_resource("tiny_cuh2.con"))
        ase_atoms = frames[0].to_ase()
        tags = ase_atoms.get_tags()
        for i, atom in enumerate(frames[0].atoms):
            assert tags[i] == atom.atom_id

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
                         is_fixed=True, atom_id=3, mass=63.546),
            readcon.Atom(symbol="H", x=1.0, y=2.0, z=3.0,
                         is_fixed=False, atom_id=1, mass=1.008),
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
