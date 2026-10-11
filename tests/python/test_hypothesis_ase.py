"""Hypothesis checks for string reads and the ASE cell, pbc, and time unit."""

from __future__ import annotations

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, settings
from hypothesis import strategies as st

ase = pytest.importorskip("ase")

import readcon

NATURAL = "(amu*angstrom^2/eV)^0.5"
FINITE = st.floats(
    min_value=-5.0,
    max_value=5.0,
    allow_nan=False,
    allow_infinity=False,
    width=64,
)
LENGTH = st.floats(
    min_value=2.0,
    max_value=40.0,
    allow_nan=False,
    allow_infinity=False,
    width=64,
)


def _orthogonal_frame(cell, pbc, velocity):
    atoms = [
        readcon.Atom(
            symbol="Cu",
            x=0.1,
            y=-0.2,
            z=0.3,
            vx=velocity,
            vy=0.0,
            vz=0.0,
            atom_id=7,
            mass=63.546,
        )
    ]
    return readcon.ConFrame(
        cell=cell,
        angles=[90.0, 90.0, 90.0],
        atoms=atoms,
        metadata={
            "con_spec_minor": 1,
            "pbc": list(pbc),
            "units": {
                "length": "angstrom",
                "energy": "eV",
                "mass": "amu",
                "time": NATURAL,
            },
        },
    )


@settings(max_examples=40, deadline=None)
@given(text=st.text(max_size=240))
def test_read_con_string_rejects_or_returns_frames(text):
    try:
        frames = readcon.read_con_string(text)
    except readcon.ConError:
        return
    assert isinstance(frames, list)


@settings(max_examples=30, deadline=None)
@given(
    cell=st.tuples(LENGTH, LENGTH, LENGTH),
    pbc=st.tuples(st.booleans(), st.booleans(), st.booleans()),
    velocity=FINITE,
)
def test_string_round_trip_keeps_cell_pbc_and_natural_velocity(cell, pbc, velocity):
    frame = _orthogonal_frame(list(cell), pbc, velocity)
    text = readcon.write_con_string([frame])
    again = readcon.read_con_string(text)[0]
    assert again.cell[0] == pytest.approx(cell[0])
    assert again.cell[2] == pytest.approx(cell[2])
    assert list(again.metadata["pbc"]) == list(pbc)
    assert again.metadata["units"]["time"] == NATURAL
    assert again.atoms[0].vx == pytest.approx(velocity)


@settings(max_examples=30, deadline=None)
@given(
    cell=st.tuples(LENGTH, LENGTH, LENGTH),
    pbc=st.tuples(st.booleans(), st.booleans(), st.booleans()),
    velocity=FINITE,
)
def test_ase_round_trip_keeps_cell_pbc_and_natural_velocity(cell, pbc, velocity):
    atoms = ase.Atoms(
        "Cu", positions=[[0.1, -0.2, 0.3]], cell=list(cell), pbc=list(pbc)
    )
    atoms.set_velocities([[velocity, 0.0, 0.0]])
    frame = readcon.ConFrame.from_ase(atoms)
    assert list(frame.metadata["pbc"]) == list(pbc)
    assert frame.metadata["units"]["time"] == NATURAL
    assert frame.metadata["con_spec_minor"] == 1
    vx = frame.atoms[0].vx
    if abs(velocity) <= 1.0e-12:
        assert vx is None or vx == pytest.approx(0.0)
    else:
        assert vx == pytest.approx(velocity)
    back = frame.to_ase()
    assert list(back.pbc) == list(pbc)
    assert back.cell[0, 0] == pytest.approx(cell[0])
    assert back.cell[2, 2] == pytest.approx(cell[2])
    got = back.get_velocities()
    if abs(velocity) <= 1.0e-12:
        assert got is None or got[0, 0] == pytest.approx(0.0)
    else:
        assert got[0, 0] == pytest.approx(velocity)
        inflated = velocity * (10.180505710759414**2)
        assert abs(got[0, 0] - inflated) > 1.0e-3
