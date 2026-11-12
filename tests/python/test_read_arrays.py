"""Positions, velocities, and forces come back bit-identical to the atoms.

The array accessors copy the parsed buffers directly. These checks lock
that copy to the per-atom values, including before `.atoms` is built.
"""

import os

import numpy as np
import pytest

import readcon

ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "resources", "test")
FILES = (
    "tiny_cuh2.con",
    "tiny_cuh2.convel",
    "tiny_cuh2_forces.con",
    "tiny_cuh2_vel_forces.con",
    "tiny_multi_cuh2.con",
    "tiny_multi_cuh2.convel",
    "cuh2.con",
)


def _same_float(got, expected):
    assert np.float64(got).tobytes() == np.float64(expected).tobytes()


def _snapshot(frame):
    xyz = np.array(frame.xyz, copy=True)
    vel = None if frame.vel is None else np.array(frame.vel, copy=True)
    frc = None if frame.frc is None else np.array(frame.frc, copy=True)
    coords = np.array(frame.coords_array(), copy=True)
    velocities = frame.velocities_array()
    forces = frame.forces_array()
    if velocities is not None:
        velocities = np.array(velocities, copy=True)
    if forces is not None:
        forces = np.array(forces, copy=True)
    return xyz, vel, frc, coords, velocities, forces


@pytest.mark.parametrize("name", FILES)
def test_arrays_match_atoms_bit_for_bit(name):
    frames = readcon.read_all_frames(os.path.join(ROOT, name))
    assert len(frames) >= 1
    for frame in frames:
        xyz, vel, frc, coords, velocities, forces = _snapshot(frame)
        assert xyz.dtype == np.float64
        assert xyz.flags["C_CONTIGUOUS"]
        assert np.array_equal(coords, xyz)
        if vel is None:
            assert velocities is None
        else:
            assert velocities.dtype == np.float64
            assert np.array_equal(velocities, vel)
        if frc is None:
            assert forces is None
        else:
            assert forces.dtype == np.float64
            assert np.array_equal(forces, frc)
        atoms = list(frame.atoms)
        assert xyz.shape == (len(atoms), 3)
        for i, atom in enumerate(atoms):
            _same_float(xyz[i, 0], atom.x)
            _same_float(xyz[i, 1], atom.y)
            _same_float(xyz[i, 2], atom.z)
            _same_float(coords[i, 0], atom.x)
            if vel is None:
                assert atom.vx is None and atom.vy is None and atom.vz is None
            else:
                _same_float(vel[i, 0], atom.vx)
                _same_float(vel[i, 1], atom.vy)
                _same_float(vel[i, 2], atom.vz)
            if frc is None:
                assert atom.fx is None and atom.fy is None and atom.fz is None
            else:
                _same_float(frc[i, 0], atom.fx)
                _same_float(frc[i, 1], atom.fy)
                _same_float(frc[i, 2], atom.fz)


def test_array_methods_are_fresh_and_follow_atom_edits():
    frame = readcon.read_first_frame(os.path.join(ROOT, "tiny_cuh2_vel_forces.con"))
    coords = frame.coords_array()
    velocities = frame.velocities_array()
    forces = frame.forces_array()
    coords[0, 0] = -999.0
    velocities[0, 0] = -999.0
    forces[0, 0] = -999.0
    again = frame.coords_array()
    assert float(again[0, 0]) == pytest.approx(frame.atoms[0].x)
    assert float(again[0, 0]) != pytest.approx(-999.0)
    assert float(frame.velocities_array()[0, 0]) == pytest.approx(frame.atoms[0].vx)
    assert float(frame.forces_array()[0, 0]) == pytest.approx(frame.atoms[0].fx)
    frame.atoms[0].x = 12.5
    frame.atoms[0].vx = -1.25
    frame.atoms[0].fx = 4.5
    assert float(frame.coords_array()[0, 0]) == pytest.approx(12.5)
    assert float(frame.velocities_array()[0, 0]) == pytest.approx(-1.25)
    assert float(frame.forces_array()[0, 0]) == pytest.approx(4.5)


def test_read_all_frames_positions_match_read_positions():
    path = os.path.join(ROOT, "tiny_multi_cuh2.convel")
    frames = readcon.read_all_frames(path)
    block = readcon.read_positions(path)
    for index, frame in enumerate(frames):
        got = np.array(frame.xyz, copy=False)
        assert got.tobytes() == np.ascontiguousarray(block[index]).tobytes()
