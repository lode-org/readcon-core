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


class TestErrorHandling:
    def test_bad_file_path(self):
        with pytest.raises(OSError):
            readcon.read_con("/nonexistent/path.con")

    def test_malformed_data(self):
        with pytest.raises(OSError):
            readcon.read_con_string("not a valid con file\n")
