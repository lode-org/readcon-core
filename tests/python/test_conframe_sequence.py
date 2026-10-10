"""One atom store on ConFrame, plus the sequence protocol."""

import os

import pytest

import readcon


RESOURCES = os.path.join(os.path.dirname(__file__), "..", "..", "resources", "test")


def _resource(fname):
    return os.path.join(RESOURCES, fname)


def atom(symbol, x, y=0.0, z=0.0, **kwargs):
    return readcon.Atom(symbol=symbol, x=x, y=y, z=z, **kwargs)


def make_frame(*atoms, **kwargs):
    return readcon.ConFrame(
        cell=kwargs.get("cell", [10.0, 10.0, 10.0]),
        angles=kwargs.get("angles", [90.0, 90.0, 90.0]),
        atoms=list(atoms),
        metadata=kwargs.get("metadata"),
    )


def round_trip(frame):
    text = readcon.write_con_string([frame], precision=17)
    return readcon.read_con_string(text)[0]


def symbols(frame):
    return [item.symbol for item in frame]


def xs(frame):
    return [item.x for item in frame]


class TestSingleStore:
    def test_view_write_matches_arrays_and_reparse(self):
        frame = make_frame(atom("H", 0.0, mass=1.0), atom("He", 1.0, mass=4.0))
        frame[0].x = 12.5
        assert frame.atoms[0].x == 12.5
        assert float(frame.xyz[0, 0]) == 12.5
        assert float(frame.coords_array()[0, 0]) == 12.5
        assert float(frame.xyz[1, 0]) == 1.0
        parsed = round_trip(frame)
        assert parsed[0].x == 12.5
        assert parsed[1].x == 1.0
        assert symbols(parsed) == ["H", "He"]

    def test_parsed_frame_mutation_agrees(self):
        frame = readcon.read_first_frame(_resource("tiny_cuh2.con"))
        original = [item.x for item in frame]
        frame[0].x = 12.5
        assert frame.atoms[0].x == 12.5
        assert float(frame.xyz[0, 0]) == 12.5
        assert float(frame.coords_array()[0, 0]) == 12.5
        parsed = round_trip(frame)
        assert parsed[0].symbol == "Cu"
        assert parsed[0].x == pytest.approx(12.5)
        assert parsed[1].x == pytest.approx(original[1])

    def test_array_mutation_does_not_write_back(self):
        frame = make_frame(atom("H", 1.5))
        xyz = frame.xyz
        coords = frame.coords_array()
        xyz[0, 0] = -999.0
        coords[0, 0] = -999.0
        assert frame[0].x == 1.5
        assert float(frame.xyz[0, 0]) == 1.5
        assert float(frame.coords_array()[0, 0]) == 1.5

    def test_velocity_and_force_sections_track_the_view(self):
        frame = make_frame(atom("H", 0.0, mass=1.0), atom("He", 1.0, mass=4.0))
        assert frame.vel is None
        assert frame.frc is None
        assert frame.velocities_array() is None
        assert frame.forces_array() is None
        frame[1].vx = 0.5
        frame[0].fx = -0.25
        assert frame.has_velocities
        assert frame.has_forces
        assert frame[1].vx == 0.5
        assert frame[1].vy == 0.0
        assert frame[0].fx == -0.25
        assert float(frame.vel[1, 0]) == 0.5
        assert float(frame.velocities_array()[1, 0]) == 0.5
        assert float(frame.frc[0, 0]) == -0.25
        assert float(frame.forces_array()[0, 0]) == -0.25
        parsed = round_trip(frame)
        assert parsed[1].vx == 0.5
        assert parsed[0].fx == -0.25
        assert float(parsed.vel[1, 0]) == 0.5
        assert float(parsed.forces_array()[0, 0]) == -0.25

    def test_len_is_the_one_store(self):
        frame = make_frame(atom("H", 0.0), atom("He", 1.0))
        assert len(frame) == len(frame.atoms) == 2
        assert bool(frame) is True
        empty = make_frame()
        assert len(empty) == 0
        assert bool(empty) is False


class TestSequence:
    def test_iter_reversed_and_negative_index(self):
        frame = make_frame(atom("H", 0.0), atom("He", 1.0), atom("Li", 2.0))
        assert symbols(frame) == ["H", "He", "Li"]
        assert [item.symbol for item in reversed(frame)] == ["Li", "He", "H"]
        assert frame[-1].symbol == "Li"
        assert frame[-1].x == 2.0
        with pytest.raises(IndexError):
            _ = frame[3]
        with pytest.raises(IndexError):
            _ = frame[-4]

    def test_slice_getitem_returns_frame(self):
        frame = make_frame(atom("H", 0.0), atom("He", 1.0), atom("Li", 2.0))
        mid = frame[1:]
        assert isinstance(mid, readcon.ConFrame)
        assert symbols(mid) == ["He", "Li"]
        assert xs(mid) == [1.0, 2.0]
        assert symbols(frame[::2]) == ["H", "Li"]
        assert symbols(frame[::-1]) == ["Li", "He", "H"]
        empty = frame[0:0]
        assert isinstance(empty, readcon.ConFrame)
        assert len(empty) == 0
        assert bool(empty) is False
        # A slice is a new frame. Editing it does not change the parent.
        mid[0].x = 8.0
        assert frame[1].x == 1.0

    def test_setitem_and_self_views(self):
        frame = make_frame(atom("H", 0.0, mass=1.0), atom("He", 4.0, mass=4.0))
        frame[0] = frame[1]
        assert symbols(frame) == ["He", "He"]
        assert xs(frame) == [4.0, 4.0]
        frame.append(frame[0])
        assert len(frame) == 3
        assert symbols(frame) == ["He", "He", "He"]

    def test_slice_set_and_del(self):
        frame = make_frame(
            atom("H", 0.0, mass=1.0),
            atom("He", 1.0, mass=4.0),
            atom("Li", 2.0, mass=8.0),
        )
        frame[1:2] = [atom("Ne", 3.0, mass=16.0)]
        assert symbols(frame) == ["H", "Ne", "Li"]
        frame[1:1] = [atom("He", 1.5, mass=4.0)]
        assert symbols(frame) == ["H", "He", "Ne", "Li"]
        del frame[1]
        assert symbols(frame) == ["H", "Ne", "Li"]
        del frame[::2]
        assert symbols(frame) == ["Ne"]
        other = make_frame(atom("H", 0.0), atom("He", 1.0), atom("Li", 2.0))
        with pytest.raises(ValueError):
            other[::2] = [atom("Be", 9.0)]

    def test_append_insert_extend_use_type_group_order(self):
        frame = make_frame(atom("H", 0.0, mass=1.0), atom("Cu", 1.0, mass=64.0))
        frame.append(atom("H", 2.0, mass=1.0))
        assert symbols(frame) == ["H", "H", "Cu"]
        assert xs(frame) == [0.0, 2.0, 1.0]
        frame.insert(0, atom("Cu", 4.0, mass=64.0))
        # Cu is now the first symbol encountered, so both Cu atoms lead.
        assert symbols(frame) == ["Cu", "Cu", "H", "H"]
        assert xs(frame) == [4.0, 1.0, 0.0, 2.0]
        frame.extend([atom("He", 8.0, mass=4.0), atom("H", 0.5, mass=1.0)])
        assert symbols(frame) == ["Cu", "Cu", "H", "H", "H", "He"]
        assert xs(frame) == [4.0, 1.0, 0.0, 2.0, 0.5, 8.0]
        parsed = round_trip(frame)
        assert symbols(parsed) == symbols(frame)
        assert xs(parsed) == xs(frame)

    def test_insert_clamps_like_list(self):
        frame = make_frame(atom("H", 0.0, mass=1.0))
        frame.insert(-10, atom("He", 1.0, mass=4.0))
        assert symbols(frame) == ["He", "H"]
        frame.insert(50, atom("Li", 2.0, mass=8.0))
        assert symbols(frame) == ["He", "H", "Li"]

    def test_contains(self):
        frame = make_frame(
            atom("H", 0.0, mass=1.0, fixed=[True, False, False]),
            atom("He", 1.0, mass=4.0),
        )
        assert atom("H", 0.0, mass=1.0, fixed=[True, False, False]) in frame
        assert frame[1] in frame.atoms
        assert atom("H", 9.0, mass=1.0) not in frame
        assert "H" not in frame
        assert 0 not in frame

    def test_equality_is_physical_content(self):
        left = make_frame(
            atom("H", 0.0, y=0.5, mass=1.0, atom_id=7, energy=3.0),
            metadata={"generator": "left"},
        )
        right = make_frame(
            atom("H", 0.0, y=0.5, mass=1.0, atom_id=9, energy=8.0),
            metadata={"generator": "right"},
        )
        assert left == right
        assert not (left != right)
        right[0].x = 1.0
        assert left != right
        missing = make_frame(atom("H", 0.0, y=0.5, mass=1.0))
        present = make_frame(atom("H", 0.0, y=0.5, mass=1.0, vx=0.0, vy=0.0, vz=0.0))
        assert missing != present
        nan = make_frame(atom("H", float("nan"), mass=1.0))
        assert nan != nan
        swapped = make_frame(atom("He", 0.0, mass=4.0), atom("H", 1.0, mass=1.0))
        other_order = make_frame(atom("H", 1.0, mass=1.0), atom("He", 0.0, mass=4.0))
        assert swapped != other_order
        assert left != "frame"
        assert (left == object()) is False

    def test_mass_disagreement_stays_until_write(self):
        frame = make_frame(
            atom("H", 0.0, mass=1.0),
            atom("H", 4.0, mass=2.0),
        )
        assert symbols(frame) == ["H", "H"]
        assert xs(frame) == [0.0, 4.0]
        assert [item.mass for item in frame] == [1.0, 2.0]
        with pytest.raises(ValueError, match="inconsistent masses"):
            readcon.write_con_string([frame])
        agreed = make_frame(atom("H", 0.0, mass=1.0), atom("H", 4.0, mass=1.0))
        agreed[1].mass = 2.0
        assert agreed[0].mass == 1.0
        assert agreed[1].mass == 2.0
        assert float(agreed.xyz[1, 0]) == 4.0
        with pytest.raises(ValueError, match="inconsistent masses"):
            readcon.write_con_string([agreed])

    def test_view_index_follows_position_after_structural_edit(self):
        frame = make_frame(atom("H", 1.0, mass=1.0), atom("Cu", 2.0, mass=64.0))
        view = frame[1]
        frame.insert(0, atom("Cu", 3.0, mass=64.0))
        assert symbols(frame) == ["Cu", "Cu", "H"]
        assert view.symbol == "Cu"
        assert view.x == 2.0
