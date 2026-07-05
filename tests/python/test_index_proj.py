"""Drive shipped PyO3 entry points for campaign index_proj + canonical writer."""
import os
import tempfile

import pytest

import readcon

RESOURCES = os.path.join(os.path.dirname(__file__), "..", "..", "resources", "test")


def _resource(fname):
    return os.path.join(RESOURCES, fname)


class TestIndexProjectionPython:
    def test_tiny_cuh2_per_field_getters(self):
        frames = readcon.read_con(_resource("tiny_cuh2.con"))
        assert len(frames) == 1
        frame = frames[0]

        # Per-field accessors must exist and match index_projection() dict.
        proj = frame.index_projection()
        assert frame.index_natoms == proj["n_atoms"] == len(frame.atoms)
        assert frame.composition_formula == proj["formula"]
        assert ":" in frame.composition_formula
        assert frame.sections_mask == proj["sections_mask"]

        assert frame.total_mass is not None
        assert frame.total_mass == pytest.approx(proj["total_mass"])
        assert frame.total_mass > 0.0

        assert frame.cell_volume is not None
        assert frame.cell_volume == pytest.approx(proj["cell_volume"], rel=1e-6)
        assert frame.cell_volume > 0.0

        # Finite index energy vs legacy: fixture may omit energy → both None
        assert frame.index_energy == proj["energy"]
        if frame.index_energy is not None:
            assert frame.index_energy == pytest.approx(frame.energy)

        assert frame.fmax == proj["fmax"]

        j = frame.index_projection_json()
        assert '"formula"' in j
        assert frame.composition_formula in j or "formula" in j
        assert '"n_atoms"' in j

    def test_forces_fixture_fmax_and_mask(self):
        frames = readcon.read_con(_resource("tiny_cuh2_forces.con"))
        frame = frames[0]
        assert frame.has_forces
        assert frame.sections_mask != 0
        assert frame.fmax is not None and frame.fmax > 0.0
        # Legacy energy present; index_energy is finite-only and should match
        assert frame.energy == pytest.approx(-42.5)
        assert frame.index_energy == pytest.approx(-42.5)
        proj = frame.index_projection()
        assert proj["has_forces"] is True
        assert proj["fmax"] == pytest.approx(frame.fmax)

    def test_canonical_write_con_string_byte_identical(self):
        frames = readcon.read_con(_resource("tiny_cuh2.con"))
        a = readcon.write_con_string(frames, precision=6, canonical=True)
        b = readcon.write_con_string(frames, precision=6, canonical=True)
        assert a == b
        assert len(a) > 0
        # Non-canonical may differ in metadata key order; at least produces text
        c = readcon.write_con_string(frames, precision=6, canonical=False)
        assert len(c) > 0

    def test_canonical_write_con_path_byte_identical(self):
        frames = readcon.read_con(_resource("tiny_cuh2.con"))
        with tempfile.TemporaryDirectory() as td:
            p1 = os.path.join(td, "a.con")
            p2 = os.path.join(td, "b.con")
            readcon.write_con(p1, frames, precision=6, canonical=True)
            readcon.write_con(p2, frames, precision=6, canonical=True)
            with open(p1, "rb") as f:
                b1 = f.read()
            with open(p2, "rb") as f:
                b2 = f.read()
            assert b1 == b2
            assert len(b1) > 0

    def test_frame_write_con_canonical(self):
        frames = readcon.read_con(_resource("tiny_cuh2.con"))
        frame = frames[0]
        with tempfile.TemporaryDirectory() as td:
            p1 = os.path.join(td, "a.con")
            p2 = os.path.join(td, "b.con")
            frame.write_con(p1, canonical=True)
            frame.write_con(p2, canonical=True)
            with open(p1, "rb") as f:
                b1 = f.read()
            with open(p2, "rb") as f:
                b2 = f.read()
            assert b1 == b2
