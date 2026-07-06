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
        assert atoms[0].is_fixed is True  # backward-compat property
        assert atoms[0].fixed == [True, True, True]
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


class TestReadForces:
    def test_read_force_section(self):
        frames = readcon.read_con(_resource("tiny_cuh2_forces.con"))
        assert len(frames) == 1
        frame = frames[0]
        assert frame.has_forces
        assert frame.energy == pytest.approx(-42.5)
        assert frame.metadata["potential"]["type"] == "EMT"
        atom = frame.atoms[0]
        assert atom.has_forces
        assert atom.fixed == [True, True, True]
        assert atom.fx == pytest.approx(0.123456, abs=1e-6)
        assert atom.fy == pytest.approx(0.234567, abs=1e-6)
        assert atom.fz == pytest.approx(-0.345678, abs=1e-6)


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
        assert atom.fixed == [False, False, False]
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
            readcon.Atom(symbol="Cu", x=0.0, y=0.0, z=0.0, fixed=[True, True, True], atom_id=0, mass=63.546),
            readcon.Atom(symbol="Cu", x=1.0, y=1.0, z=1.0, fixed=[True, True, True], atom_id=1, mass=63.546),
            readcon.Atom(symbol="H", x=2.0, y=2.0, z=2.0, fixed=[False, False, False], atom_id=2, mass=1.008),
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
                         fixed=[True, True, True], atom_id=0, mass=63.546),
            readcon.Atom(symbol="H", x=1.0, y=2.0, z=3.0,
                         fixed=[False, False, False], atom_id=1, mass=1.008),
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

    def test_typed_metadata_helpers(self):
        frame = readcon.ConFrame(
            cell=[10.0, 10.0, 10.0],
            angles=[90.0, 90.0, 90.0],
            atoms=[readcon.Atom(symbol="H", x=0.0, y=0.0, z=0.0)],
        )
        frame.set_energy(-1.25)
        frame.set_frame_index(7)
        frame.set_time(3.5)
        frame.set_timestep(0.2)
        frame.set_neb_bead(4)
        frame.set_neb_band(2)
        frame.set_scalar_metadata("convergence", 1.0e-3)
        frame.set_string_metadata("generator", "eon")

        assert frame.energy == pytest.approx(-1.25)
        assert frame.frame_index == 7
        assert frame.time == pytest.approx(3.5)
        assert frame.timestep == pytest.approx(0.2)
        assert frame.neb_bead == 4
        assert frame.neb_band == 2
        assert frame.metadata["convergence"] == pytest.approx(0.001)
        assert frame.metadata["generator"] == "eon"

    def test_set_metadata_json(self):
        frame = readcon.ConFrame(
            cell=[10.0, 10.0, 10.0],
            angles=[90.0, 90.0, 90.0],
            atoms=[readcon.Atom(symbol="H", x=0.0, y=0.0, z=0.0)],
        )
        frame.set_metadata_json(
            '{"con_spec_version":2,"frame_index":5,"energy":-42.5,"generator":"test","sections":["forces"]}'
        )

        assert frame.frame_index == 5
        assert frame.energy == pytest.approx(-42.5)
        assert frame.metadata["generator"] == "test"
        assert "sections" not in frame.metadata

    def test_constructor_metadata(self):
        frame = readcon.ConFrame(
            cell=[10.0, 10.0, 10.0],
            angles=[90.0, 90.0, 90.0],
            atoms=[readcon.Atom(symbol="H", x=0.0, y=0.0, z=0.0)],
            metadata={"generator": "pytest", "nested": {"ok": True}},
        )

        assert frame.metadata["generator"] == "pytest"
        assert frame.metadata["nested"]["ok"] is True

    def test_metadata_property_setter(self):
        frame = readcon.ConFrame(
            cell=[10.0, 10.0, 10.0],
            angles=[90.0, 90.0, 90.0],
            atoms=[readcon.Atom(symbol="H", x=0.0, y=0.0, z=0.0)],
        )

        frame.metadata = {"generator": "setter", "values": [1, 2.5, None]}

        assert frame.metadata == {"generator": "setter", "values": [1, 2.5, None]}

    def test_metadata_rejects_non_json_values(self):
        frame = readcon.ConFrame(
            cell=[10.0, 10.0, 10.0],
            angles=[90.0, 90.0, 90.0],
            atoms=[readcon.Atom(symbol="H", x=0.0, y=0.0, z=0.0)],
        )

        with pytest.raises(ValueError):
            frame.metadata = {"bad": object()}

    def test_metadata_item_assignment_persists_through_writes(self):
        frame = readcon.ConFrame(
            cell=[10.0, 10.0, 10.0],
            angles=[90.0, 90.0, 90.0],
            atoms=[readcon.Atom(symbol="H", x=0.0, y=0.0, z=0.0)],
        )

        frame.metadata["generator"] = "item-setter"
        frame.metadata["nested"] = {"values": [1, 2.5, None], "ok": True}

        output = readcon.write_con_string([frame])
        reread = readcon.read_con_string(output)[0]
        assert reread.metadata["generator"] == "item-setter"
        assert reread.metadata["nested"]["values"] == [1, 2.5, None]
        assert reread.metadata["nested"]["ok"] is True

        with tempfile.NamedTemporaryFile(suffix=".con", delete=False) as f:
            tmppath = f.name
        try:
            readcon.write_con(tmppath, [frame])
            from_file = readcon.read_con(tmppath)[0]
            assert from_file.metadata["generator"] == "item-setter"
            assert from_file.metadata["nested"]["values"] == [1, 2.5, None]
        finally:
            os.unlink(tmppath)

    def test_metadata_item_assignment_rejects_non_json_on_write(self):
        frame = readcon.ConFrame(
            cell=[10.0, 10.0, 10.0],
            angles=[90.0, 90.0, 90.0],
            atoms=[readcon.Atom(symbol="H", x=0.0, y=0.0, z=0.0)],
        )

        frame.metadata["bad"] = object()

        with pytest.raises((TypeError, ValueError), match="metadata|JSON"):
            readcon.write_con_string([frame])

    def test_atoms_live_list_mutations_persist_through_write(self):
        frame = readcon.ConFrame(
            cell=[10.0, 10.0, 10.0],
            angles=[90.0, 90.0, 90.0],
            atoms=[readcon.Atom(symbol="H", x=0.0, y=0.0, z=0.0, atom_id=0, mass=1.008)],
        )

        atoms = frame.atoms
        atoms.append(readcon.Atom(symbol="Cu", x=1.0, y=1.0, z=1.0, atom_id=1, mass=63.546))
        atoms[0] = readcon.Atom(symbol="He", x=2.0, y=2.0, z=2.0, atom_id=0, mass=4.0026)
        atoms[1].x = 4.5

        reread = readcon.read_con_string(readcon.write_con_string([frame]))[0]
        assert len(reread) == 2
        assert [atom.symbol for atom in reread.atoms] == ["He", "Cu"]
        assert reread.atoms[0].x == pytest.approx(2.0)
        assert reread.atoms[1].x == pytest.approx(4.5)
        assert reread.atoms[1].mass == pytest.approx(63.546, abs=0.01)

    def test_read_first_frame_and_iter_con(self):
        path = _resource("tiny_multi_cuh2.con")

        first = readcon.read_first_frame(path)
        assert len(first) == 4
        assert first.atoms[0].symbol == "Cu"

        iterator = readcon.iter_con(path)
        assert iter(iterator) is iterator
        frames = list(iterator)
        assert len(frames) == 2
        assert [len(frame) for frame in frames] == [4, 4]

    def test_count_frames_and_streaming_matches_batch(self):
        path = _resource("tiny_multi_cuh2.con")
        assert readcon.count_frames(path) == 2
        batch = readcon.read_all_frames(path)
        streamed = list(readcon.iter_con(path))
        assert len(streamed) == len(batch)
        for a, b in zip(streamed, batch):
            assert len(a) == len(b)
            assert a.atoms[0].symbol == b.atoms[0].symbol
            assert a.atoms[0].x == pytest.approx(b.atoms[0].x)

    def test_read_all_positions_shape_matches_atoms(self):
        path = _resource("tiny_multi_cuh2.con")
        positions = readcon.read_all_positions(path)
        frames = readcon.read_all_frames(path)
        assert len(positions) == len(frames)
        for pos, fr in zip(positions, frames):
            assert pos.shape == (len(fr.atoms), 3)
            assert float(pos[0, 0]) == pytest.approx(fr.atoms[0].x)

    def test_coords_array_matches_atoms_and_cached_path(self):
        path = _resource("tiny_cuh2.con")
        fr = readcon.read_first_frame(path)
        arr = fr.coords_array()
        assert arr.shape == (len(fr.atoms), 3)
        assert float(arr[0, 0]) == pytest.approx(fr.atoms[0].x)
        assert float(arr[0, 1]) == pytest.approx(fr.atoms[0].y)
        assert float(arr[0, 2]) == pytest.approx(fr.atoms[0].z)


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


class TestNumpyArrays:
    def test_coords_array_shape(self):
        np = pytest.importorskip("numpy")
        frame = readcon.read_con(_resource("tiny_cuh2.con"))[0]
        coords = frame.coords_array()
        assert coords.shape == (len(frame), 3)
        assert coords.dtype == np.float64
        # First atom's x matches the AoS getter.
        assert coords[0, 0] == pytest.approx(frame.atoms[0].x)

    def test_velocities_array_returns_none_without_velocities(self):
        frame = readcon.read_con(_resource("tiny_cuh2.con"))[0]
        assert frame.velocities_array() is None

    def test_forces_array_round_trips(self):
        np = pytest.importorskip("numpy")
        frame = readcon.read_con(_resource("tiny_cuh2_forces.con"))[0]
        forces = frame.forces_array()
        assert forces is not None
        assert forces.shape == (len(frame), 3)
        # Forces match the AoS atom view.
        assert forces[0, 0] == pytest.approx(frame.atoms[0].fx)

    def test_atom_ids_array(self):
        np = pytest.importorskip("numpy")
        frame = readcon.read_con(_resource("tiny_cuh2.con"))[0]
        ids = frame.atom_ids_array()
        assert ids.dtype == np.uint64
        assert ids.shape == (len(frame),)

    def test_build_atom_id_index(self):
        frame = readcon.read_con(_resource("tiny_cuh2.con"))[0]
        idx = frame.build_atom_id_index()
        assert isinstance(idx, dict)
        assert len(idx) == len(frame)
        for atom_id, position in idx.items():
            assert frame.atoms[position].atom_id == atom_id


class TestErrorHandling:
    def test_bad_file_path(self):
        with pytest.raises(OSError):
            readcon.read_con("/nonexistent/path.con")

    def test_malformed_data(self):
        with pytest.raises(OSError):
            readcon.read_con_string("not a valid con file\n")


def test_read_all_frames_matches_read_con():
    """Batch ergonomics alias must match read_con on a real fixture."""
    from pathlib import Path
    tiny = Path(__file__).resolve().parents[2] / "resources" / "test" / "tiny_cuh2.con"
    a = readcon.read_con(str(tiny))
    b = readcon.read_all_frames(str(tiny))
    assert len(a) == len(b) >= 1
    assert a[0].coords_array().shape == b[0].coords_array().shape
