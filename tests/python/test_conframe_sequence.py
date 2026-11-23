"""One atom store on ConFrame, plus the sequence protocol."""

import os
import tempfile

import numpy as np
import pytest

import readcon


RESOURCES = os.path.join(os.path.dirname(__file__), "..", "..", "resources", "test")


def _resource(fname):
    return os.path.join(RESOURCES, fname)


def atom(symbol, x, y=0.0, z=0.0, **kwargs):
    # The writer rejects a repeated atom id. The constructor's default is 0,
    # so each atom in these tests takes the next id unless one is given.
    if "atom_id" not in kwargs:
        kwargs["atom_id"] = atom.next_id
        atom.next_id += 1
    return readcon.Atom(symbol=symbol, x=x, y=y, z=z, **kwargs)


atom.next_id = 0


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


def assert_held_writes(frame, held, index, new_x):
    """`held` is the Atom in `index` and a write reaches that slot and a reparse."""
    assert frame.atoms[index] is held
    assert held.x == frame[index].x
    assert held.x == frame.atoms[index].x
    held.x = new_x
    assert frame[index].x == new_x
    assert frame.atoms[index].x == new_x
    assert round_trip(frame)[index].x == new_x


def assert_detached(frame, held):
    """A replaced or deleted Atom no longer writes any slot of `frame`."""
    assert all(item is not held for item in frame.atoms)
    before = xs(frame)
    held.x = -12345.0
    assert xs(frame) == before


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

    def test_held_atoms_item_survives_structural_edit(self):
        # Append keeps the previous order: an identity permutation.
        frame = readcon.read_first_frame(_resource("tiny_cuh2.con"))
        held = frame.atoms[0]
        other = frame.atoms[1]
        frame.atoms.append(atom("H", 0.5, mass=frame[2].mass))
        frame.atoms[2] = frame.atoms[2]
        held.x = 42.0
        other.x = 43.0
        assert frame.atoms[0] is held
        assert frame[0].x == 42.0
        assert round_trip(frame)[0].x == 42.0
        assert round_trip(frame)[1].x == 43.0
        replaced = frame.atoms[3]
        frame.atoms[3] = atom("H", 7.0, mass=frame[3].mass)
        replaced.x = -1.0
        assert round_trip(frame)[3].x == 7.0
        assert_detached(frame, replaced)

        # insert(0, Cu) on [H, Cu] stores [Cu, Cu, H]. Held atoms follow.
        frame = make_frame(atom("H", 1.0, mass=1.0), atom("Cu", 2.0, mass=64.0))
        held_h = frame.atoms[0]
        held_cu = frame.atoms[1]
        frame.atoms.insert(0, atom("Cu", 3.0, mass=64.0))
        assert symbols(frame) == ["Cu", "Cu", "H"]
        assert xs(frame) == [3.0, 2.0, 1.0]
        assert held_cu.x == 2.0
        assert held_h.x == 1.0
        assert_held_writes(frame, held_cu, 1, 22.0)
        assert_held_writes(frame, held_h, 2, 11.0)

        # Mixed extend: another H plus He. Cu moves from slot 1 to slot 2.
        frame = make_frame(atom("H", 1.0, mass=1.0), atom("Cu", 2.0, mass=64.0))
        held_h = frame.atoms[0]
        held_cu = frame.atoms[1]
        frame.atoms.extend([atom("He", 8.0, mass=4.0), atom("H", 0.5, mass=1.0)])
        assert symbols(frame) == ["H", "H", "Cu", "He"]
        assert xs(frame) == [1.0, 0.5, 2.0, 8.0]
        assert held_h.x == 1.0
        assert held_cu.x == 2.0
        assert_held_writes(frame, held_h, 0, 10.0)
        assert_held_writes(frame, held_cu, 2, 20.0)

        frame = make_frame(
            atom("H", 1.0, mass=1.0),
            atom("Cu", 2.0, mass=64.0),
            atom("He", 3.0, mass=4.0),
        )
        held_h = frame.atoms[0]
        held_cu = frame.atoms[1]
        held_he = frame.atoms[2]
        del frame.atoms[1]
        assert symbols(frame) == ["H", "He"]
        assert held_h.x == 1.0
        assert held_he.x == 3.0
        assert_held_writes(frame, held_h, 0, 12.0)
        assert_held_writes(frame, held_he, 1, 32.0)
        assert_detached(frame, held_cu)

        frame = make_frame(
            atom("H", 1.0, mass=1.0),
            atom("He", 2.0, mass=4.0),
            atom("Li", 3.0, mass=7.0),
        )
        held_h = frame.atoms[0]
        held_he = frame.atoms[1]
        held_li = frame.atoms[2]
        frame.atoms[1:2] = [
            atom("Ne", 9.0, mass=20.0),
            atom("Ar", 8.0, mass=40.0),
        ]
        assert symbols(frame) == ["H", "Ne", "Ar", "Li"]
        assert xs(frame) == [1.0, 9.0, 8.0, 3.0]
        assert held_h.x == 1.0
        assert held_li.x == 3.0
        assert_held_writes(frame, held_h, 0, 13.0)
        assert_held_writes(frame, held_li, 3, 33.0)
        assert_detached(frame, held_he)

        frame = make_frame(
            atom("H", 1.0, mass=1.0),
            atom("He", 2.0, mass=4.0),
            atom("Li", 3.0, mass=7.0),
            atom("Be", 4.0, mass=9.0),
        )
        held = [frame.atoms[i] for i in range(4)]
        del frame.atoms[::2]
        assert symbols(frame) == ["He", "Be"]
        assert xs(frame) == [2.0, 4.0]
        assert held[1].x == 2.0
        assert held[3].x == 4.0
        assert_held_writes(frame, held[1], 0, 21.0)
        assert_held_writes(frame, held[3], 1, 41.0)
        assert_detached(frame, held[0])
        assert_detached(frame, held[2])

        # Self-assignment must not detach. Both parents kept this attached.
        frame = make_frame(
            atom("H", 1.0, mass=1.0),
            atom("Cu", 2.0, mass=64.0),
            atom("He", 3.0, mass=4.0),
        )
        held = frame.atoms[1]
        neighbor = frame.atoms[0]
        tail = frame.atoms[2]
        frame.atoms[1] = held
        assert symbols(frame) == ["H", "Cu", "He"]
        assert held.x == 2.0
        assert_held_writes(frame, held, 1, 22.0)
        assert frame.atoms[0] is neighbor
        assert frame.atoms[2] is tail
        frame[1] = held
        assert frame.atoms[1] is held
        held.x = 23.0
        assert frame[1].x == 23.0
        assert round_trip(frame)[1].x == 23.0
        frame.atoms[-1] = tail
        assert frame.atoms[2] is tail
        tail.x = 33.0
        assert frame[2].x == 33.0
        assert round_trip(frame)[2].x == 33.0
        frame.atoms[1:2] = [held]
        assert frame.atoms[1] is held
        held.x = 24.0
        assert frame[1].x == 24.0
        assert round_trip(frame)[1].x == 24.0
        # Assigning a different slot copies. The source Atom stays put.
        frame.atoms[0] = held
        assert symbols(frame) == ["Cu", "Cu", "He"]
        assert frame.atoms[0] is not held
        assert frame.atoms[1] is held
        assert frame.atoms[2] is tail
        assert frame[0].x == 24.0
        held.x = 80.0
        assert frame[1].x == 80.0
        assert frame[0].x == 24.0

        # An Atom from another frame is copied. That object stays on its frame.
        other = make_frame(atom("Ne", 5.0, mass=20.0))
        foreign = other.atoms[0]
        frame.atoms[0] = foreign
        assert frame.atoms[0] is not foreign
        assert other.atoms[0] is foreign
        assert symbols(frame) == ["Ne", "Cu", "He"]
        assert frame[0].x == 5.0
        foreign.x = -4.0
        assert other[0].x == -4.0
        assert frame[0].x == 5.0
        assert frame.atoms[1] is held
        held.x = 25.0
        assert frame[1].x == 25.0
        assert round_trip(frame)[1].x == 25.0

    def test_view_index_follows_position_after_structural_edit(self):
        frame = make_frame(atom("H", 1.0, mass=1.0), atom("Cu", 2.0, mass=64.0))
        view = frame[1]
        frame.insert(0, atom("Cu", 3.0, mass=64.0))
        assert symbols(frame) == ["Cu", "Cu", "H"]
        assert view.symbol == "Cu"
        assert view.x == 2.0


def _file_text(name):
    with open(_resource(name), encoding="utf-8") as handle:
        return handle.read()


class TestSourceText:
    def test_iterator_text_matches_the_file(self):
        for name in ("tiny_cuh2.con", "tiny_multi_cuh2.con", "tiny_cuh2_forces.con"):
            file_text = _file_text(name)
            frames = list(readcon.iter_con(_resource(name)))
            assert frames
            pieces = [frame.source_text for frame in frames]
            assert all(piece is not None for piece in pieces)
            assert "".join(pieces) == file_text
            assert [frame.raw for frame in frames] == pieces
            cursor = 0
            for piece in pieces:
                assert file_text[cursor : cursor + len(piece)] == piece
                cursor += len(piece)

    def test_odd_whitespace_is_kept_verbatim(self):
        # A blank line is the user line (CON-header.4), so the extra
        # whitespace here stays inside the frame: trailing spaces on the
        # user line, spaces inside a coordinate line, and trailing spaces
        # on the last coordinate line.
        base = _file_text("tiny_cuh2.con")
        first = base.replace("Random Number Seed\n", "Random Number Seed  \n", 1)
        first = first.replace("    0.9045", "      0.9045", 1)
        first = first[:-1] + "   \n"
        second = base[:-1] + "  \n"
        odd = first + second
        with tempfile.NamedTemporaryFile("w", suffix=".con", delete=False) as handle:
            handle.write(odd)
            temp_path = handle.name
        frames = list(readcon.iter_con(temp_path))
        os.unlink(temp_path)
        assert len(frames) == 2
        assert "".join(frame.source_text for frame in frames) == odd
        assert "Random Number Seed  \n" in frames[0].source_text
        assert "      0.9045" in frames[0].source_text
        assert frames[0].source_text.endswith("   \n")
        assert frames[1].source_text.startswith("Random Number Seed\n")
        assert frames[1].source_text.endswith("  \n")

    def test_batch_reads_have_no_source_text(self):
        path = _resource("tiny_cuh2.con")
        assert readcon.read_first_frame(path).source_text is None
        assert readcon.read_con(path)[0].raw is None
        built = make_frame(atom("H", 0.0))
        assert built.source_text is None
        assert built[0:1].raw is None

    def test_mutation_drops_source_text(self):
        frame = next(readcon.iter_con(_resource("tiny_cuh2.con")))
        assert frame.source_text
        frame[0].x = 12.5
        assert frame.source_text is None
        assert frame.raw is None

        again = next(readcon.iter_con(_resource("tiny_cuh2.con")))
        kept = again.source_text
        again.metadata["note"] = "item assignment"
        assert again.source_text == kept
        again.set_energy(1.5)
        assert again.source_text is None

    def test_equality_ignores_source_text(self):
        src = next(readcon.iter_con(_resource("tiny_cuh2.con")))
        copied = [
            readcon.Atom(
                symbol=item.symbol,
                x=item.x,
                y=item.y,
                z=item.z,
                fixed=list(item.fixed),
                mass=item.mass,
                atom_id=item.atom_id,
            )
            for item in src
        ]
        built = readcon.ConFrame(
            cell=list(src.cell),
            angles=list(src.angles),
            atoms=copied,
        )
        assert built == src
        assert built.source_text is None
        assert src.raw


def _frames_with_live_xyz():
    """Parsed frames whose ``xyz`` is the coordinate buffer, not a snapshot."""
    path = _resource("tiny_cuh2.con")
    text = _file_text("tiny_cuh2.con")
    return [
        readcon.read_con(path)[0],
        next(readcon.iter_con(path)),
        readcon.read_con_string(text)[0],
        readcon.read_first_frame(path),
    ]


class TestAtomXyzAgreement:
    """``atoms``, a held ``Atom``, and ``xyz`` are one coordinate store."""

    def test_xyz_store_after_atoms_reaches_the_write(self, tmp_path):
        for frame in _frames_with_live_xyz():
            frame.atoms
            held = frame.atoms[0]
            before = float(held.x)
            frame.xyz[0, 0] = before + 4.25
            assert held.x == pytest.approx(before + 4.25)
            assert float(frame.xyz[0, 0]) == pytest.approx(before + 4.25)
            assert frame.atoms[0].x == pytest.approx(before + 4.25)
            assert frame[0].x == pytest.approx(before + 4.25)
            parsed = round_trip(frame)
            assert parsed[0].x == pytest.approx(before + 4.25)

    def test_held_atom_edit_shows_in_xyz_and_the_write(self):
        for frame in _frames_with_live_xyz():
            frame.atoms
            held = frame.atoms[0]
            other = float(frame.xyz[1, 0])
            held.x = 8.75
            held.y = -2.5
            assert float(frame.xyz[0, 0]) == pytest.approx(8.75)
            assert float(frame.xyz[0, 1]) == pytest.approx(-2.5)
            assert frame.atoms[0] is held
            assert frame[0].x == pytest.approx(8.75)
            assert float(frame.coords_array()[0, 0]) == pytest.approx(8.75)
            parsed = round_trip(frame)
            assert parsed[0].x == pytest.approx(8.75)
            assert parsed[0].y == pytest.approx(-2.5)
            assert parsed[1].x == pytest.approx(other)

    def test_assigning_xyz_updates_atoms_and_the_write(self):
        frame = readcon.read_con(_resource("tiny_multi_cuh2.con"))[0]
        frame.atoms
        updated = np.array(frame.xyz, copy=True)
        updated[0, 0] = 6.5
        updated[1, 2] = -1.25
        frame.xyz = updated
        assert frame.atoms[0].x == pytest.approx(6.5)
        assert float(frame.xyz[1, 2]) == pytest.approx(-1.25)
        held = frame.atoms[1]
        held.z = 3.25
        assert float(frame.xyz[1, 2]) == pytest.approx(3.25)
        parsed = round_trip(frame)
        assert parsed[0].x == pytest.approx(6.5)
        assert parsed[1].z == pytest.approx(3.25)

    def test_atom_and_xyz_edits_drop_source_text(self):
        path = _resource("tiny_cuh2.con")

        frame = next(readcon.iter_con(path))
        assert frame.source_text
        frame.atoms
        assert frame.source_text
        assert frame.raw

        frame = next(readcon.iter_con(path))
        assert frame.source_text
        frame.atoms
        frame.atoms[0].x = frame.atoms[0].x + 1.0
        assert frame.source_text is None
        assert frame.raw is None

        frame = next(readcon.iter_con(path))
        assert frame.source_text
        frame.xyz[0, 0] = float(frame.xyz[0, 0]) + 1.0
        assert frame.source_text is None
        assert frame.raw is None

        frame = next(readcon.iter_con(path))
        assert frame.source_text
        updated = np.array(frame.xyz, copy=True)
        updated[0, 2] = float(updated[0, 2]) + 1.0
        frame.xyz = updated
        assert frame.source_text is None
        assert frame.raw is None

        frame = next(readcon.iter_con(path))
        assert frame.source_text
        frame.atoms[0].symbol = "Ag"
        assert frame.source_text is None
        assert frame.raw is None
