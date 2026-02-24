import os
import tempfile
import pytest

import readcon


RESOURCES = os.path.join(os.path.dirname(__file__), "..", "..", "resources", "test")


def _resource(fname):
    return os.path.join(RESOURCES, fname)


class TestReadCon:
    def test_read_con_file(self):
        frames = readcon.read_con(_resource("tiny_cuh2.con"))
        assert len(frames) == 1
        frame = frames[0]
        assert len(frame) == 4
        assert frame.cell[0] == pytest.approx(15.3456, abs=1e-4)
        assert frame.angles[0] == pytest.approx(90.0)
        assert not frame.has_velocities

    def test_read_con_atoms(self):
        frames = readcon.read_con(_resource("tiny_cuh2.con"))
        atoms = frames[0].atoms
        assert atoms[0].symbol == "Cu"
        assert atoms[0].x == pytest.approx(0.6394, abs=1e-3)
        assert atoms[0].is_fixed is True
        assert atoms[0].atom_id == 0
        assert not atoms[0].has_velocity
        assert atoms[0].vx is None

    def test_read_multi_frame(self):
        frames = readcon.read_con(_resource("tiny_multi_cuh2.con"))
        assert len(frames) == 2
        assert len(frames[0]) == 4
        assert len(frames[1]) == 4


class TestReadConvel:
    def test_read_convel(self):
        frames = readcon.read_con(_resource("tiny_cuh2.convel"))
        assert len(frames) == 1
        frame = frames[0]
        assert frame.has_velocities
        atom = frame.atoms[0]
        assert atom.has_velocity
        assert atom.vx == pytest.approx(0.001234, abs=1e-6)
        assert atom.vy == pytest.approx(0.002345, abs=1e-6)

    def test_read_multi_convel(self):
        frames = readcon.read_con(_resource("tiny_multi_cuh2.convel"))
        assert len(frames) == 2
        assert frames[0].has_velocities
        assert frames[1].has_velocities


class TestReadConString:
    def test_read_string(self):
        with open(_resource("tiny_cuh2.con")) as f:
            contents = f.read()
        frames = readcon.read_con_string(contents)
        assert len(frames) == 1
        assert len(frames[0]) == 4


class TestWriteCon:
    def test_roundtrip(self):
        frames = readcon.read_con(_resource("tiny_multi_cuh2.con"))
        with tempfile.NamedTemporaryFile(suffix=".con", delete=False) as f:
            tmppath = f.name
        try:
            readcon.write_con(tmppath, frames)
            frames2 = readcon.read_con(tmppath)
            assert len(frames2) == len(frames)
            for orig, reread in zip(frames, frames2):
                assert len(orig) == len(reread)
        finally:
            os.unlink(tmppath)

    def test_write_string_roundtrip(self):
        frames = readcon.read_con(_resource("tiny_cuh2.con"))
        output = readcon.write_con_string(frames)
        frames2 = readcon.read_con_string(output)
        assert len(frames2) == len(frames)
        assert len(frames2[0]) == len(frames[0])


class TestConvelWriteRoundtrip:
    def test_convel_roundtrip(self):
        frames = readcon.read_con(_resource("tiny_cuh2.convel"))
        output = readcon.write_con_string(frames)
        frames2 = readcon.read_con_string(output)
        assert len(frames2) == 1
        assert frames2[0].has_velocities
        assert frames2[0].atoms[0].vx == pytest.approx(frames[0].atoms[0].vx, abs=1e-6)


class TestAtomConstructor:
    def test_basic(self):
        atom = readcon.Atom(symbol="Cu", x=1.0, y=2.0, z=3.0)
        assert atom.symbol == "Cu"
        assert atom.x == 1.0
        assert atom.is_fixed is False
        assert atom.atom_id == 0
        assert atom.mass is None

    def test_with_mass(self):
        atom = readcon.Atom(symbol="Cu", x=0.0, y=0.0, z=0.0, mass=63.546)
        assert atom.mass == pytest.approx(63.546)

    def test_with_velocity(self):
        atom = readcon.Atom(symbol="H", x=0.0, y=0.0, z=0.0, vx=0.1, vy=0.2, vz=0.3)
        assert atom.has_velocity
        assert atom.vx == pytest.approx(0.1)

    def test_repr(self):
        atom = readcon.Atom(symbol="Cu", x=1.0, y=2.0, z=3.0, atom_id=5)
        r = repr(atom)
        assert "Cu" in r
        assert "5" in r


class TestConFrameConstructor:
    def test_build_frame(self):
        atoms = [
            readcon.Atom(symbol="Cu", x=0.0, y=0.0, z=0.0, is_fixed=True, atom_id=0, mass=63.546),
            readcon.Atom(symbol="Cu", x=1.0, y=1.0, z=1.0, is_fixed=True, atom_id=1, mass=63.546),
            readcon.Atom(symbol="H", x=2.0, y=2.0, z=2.0, is_fixed=False, atom_id=2, mass=1.008),
        ]
        frame = readcon.ConFrame(
            cell=[10.0, 10.0, 10.0],
            angles=[90.0, 90.0, 90.0],
            atoms=atoms,
            prebox_header=["header1", "header2"],
        )
        assert len(frame) == 3
        assert frame.cell[0] == 10.0
        assert frame.angles[2] == 90.0
        assert not frame.has_velocities

    def test_roundtrip(self):
        atoms = [
            readcon.Atom(symbol="Cu", x=0.123456789012345, y=0.0, z=0.0,
                         is_fixed=True, atom_id=0, mass=63.546),
            readcon.Atom(symbol="H", x=1.0, y=2.0, z=3.0,
                         is_fixed=False, atom_id=1, mass=1.008),
        ]
        frame = readcon.ConFrame(
            cell=[15.0, 15.0, 100.0],
            angles=[90.0, 90.0, 90.0],
            atoms=atoms,
        )
        output = readcon.write_con_string([frame], precision=17)
        frames2 = readcon.read_con_string(output)
        assert len(frames2) == 1
        assert frames2[0].atoms[0].x == pytest.approx(0.123456789012345, abs=1e-15)

    def test_repr(self):
        frame = readcon.ConFrame(
            cell=[10.0, 10.0, 10.0],
            angles=[90.0, 90.0, 90.0],
            atoms=[readcon.Atom(symbol="H", x=0.0, y=0.0, z=0.0)],
        )
        r = repr(frame)
        assert "natoms=1" in r


class TestMass:
    def test_mass_from_file(self):
        frames = readcon.read_con(_resource("tiny_cuh2.con"))
        cu_atom = frames[0].atoms[0]
        assert cu_atom.mass is not None
        assert cu_atom.mass == pytest.approx(63.546, abs=0.01)

    def test_mass_roundtrip(self):
        atoms = [
            readcon.Atom(symbol="Pt", x=0.0, y=0.0, z=0.0, mass=195.08),
        ]
        frame = readcon.ConFrame(
            cell=[10.0, 10.0, 10.0],
            angles=[90.0, 90.0, 90.0],
            atoms=atoms,
        )
        output = readcon.write_con_string([frame])
        frames2 = readcon.read_con_string(output)
        assert frames2[0].atoms[0].mass == pytest.approx(195.08, abs=0.01)


class TestPrecision:
    def test_default_precision_6(self):
        atoms = [
            readcon.Atom(symbol="Cu", x=1.23456789012345, y=0.0, z=0.0),
        ]
        frame = readcon.ConFrame(
            cell=[10.0, 10.0, 10.0],
            angles=[90.0, 90.0, 90.0],
            atoms=atoms,
        )
        output = readcon.write_con_string([frame])
        # Default precision=6, so only 6 decimal places
        frames2 = readcon.read_con_string(output)
        assert frames2[0].atoms[0].x == pytest.approx(1.234568, abs=1e-6)

    def test_high_precision_17(self):
        atoms = [
            readcon.Atom(symbol="Cu", x=1.23456789012345, y=0.0, z=0.0),
        ]
        frame = readcon.ConFrame(
            cell=[10.0, 10.0, 10.0],
            angles=[90.0, 90.0, 90.0],
            atoms=atoms,
        )
        output = readcon.write_con_string([frame], precision=17)
        frames2 = readcon.read_con_string(output)
        assert frames2[0].atoms[0].x == pytest.approx(1.23456789012345, abs=1e-14)


class TestErrorHandling:
    def test_bad_file_path(self):
        with pytest.raises(OSError):
            readcon.read_con("/nonexistent/path.con")

    def test_malformed_data(self):
        with pytest.raises(OSError):
            readcon.read_con_string("not a valid con file\n")
