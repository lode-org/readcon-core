# Copyright (c) readcon-core developers
"""Species and forces in the committed extended XYZ fixtures come back."""

from pathlib import Path

import pytest
import readcon

FIXTURES = Path(__file__).resolve().parents[2] / "bench" / "h2h" / "fixtures"


def _forces(index: int) -> tuple[float, float, float]:
    return ((index % 5) * 0.25, (index % 3) * 0.5, float(index % 2))


@pytest.mark.parametrize("name,frames", [("small-1.extxyz", 1), ("small-n.extxyz", 8)])
def test_species_and_forces_round_trip(name, frames):
    got = readcon.read_extxyz(str(FIXTURES / name))
    species = got["species"]
    forces = got["arrays"]["forces"]
    assert len(species) == frames
    assert forces.shape == (frames, 10, 3)
    assert set(got["arrays"]) >= {"species", "pos", "masses", "forces"}
    for frame in range(frames):
        assert list(species[frame]) == ["Cu"] * 10
        for atom in range(10):
            assert list(forces[frame, atom]) == pytest.approx(_forces(atom))
    assert got["positions"].shape == (frames, 10, 3)
    assert got["positions"][0, 1, 0] == pytest.approx(1.0)
    assert got["masses"][0, 0] == pytest.approx(63.546)
