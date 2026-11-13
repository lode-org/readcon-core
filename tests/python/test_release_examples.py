"""Examples from the how-to: threads, append, gzip, stdin text, coordinates."""

from pathlib import Path

import readcon


def _frame(shift: float = 0.0) -> readcon.ConFrame:
    atoms = [readcon.Atom("H", shift, 0.0, 0.0, atom_id=1, mass=1.0)]
    frame = readcon.ConFrame((10.0, 10.0, 10.0), (90.0, 90.0, 90.0), atoms)
    frame.metadata["units"] = {"length": "angstrom", "energy": "eV"}
    return frame


def test_thread_counts_read_the_same_frames(tmp_path: Path) -> None:
    path = tmp_path / "one.con"
    readcon.write_con(str(path), [_frame()])
    calling = readcon.read_con(str(path))
    one = readcon.read_con(str(path), n_threads=1)
    pool = readcon.read_con(str(path), n_threads=2)
    assert len(calling) == len(one) == len(pool) == 1
    assert calling[0].atoms[0].x == one[0].atoms[0].x == pool[0].atoms[0].x


def test_append_then_gzip_extension(tmp_path: Path) -> None:
    plain = tmp_path / "out.con"
    readcon.write_con(str(plain), [_frame(0.0)])
    readcon.write_con(str(plain), [_frame(1.0)], append=True)
    assert len(readcon.read_con(str(plain))) == 2
    gzip_path = tmp_path / "out.con.gz"
    readcon.write_con(str(gzip_path), [_frame(2.0)])
    back = readcon.read_con(str(gzip_path))
    assert len(back) == 1
    assert back[0].atoms[0].x == 2.0


def test_read_positions_and_read_coords_are_the_fast_path(tmp_path: Path) -> None:
    path = tmp_path / "one.con"
    frame = readcon.ConFrame(
        (10.0, 10.0, 10.0),
        (90.0, 90.0, 90.0),
        [readcon.Atom("H", 1.25, 0.0, 0.0, atom_id=1, mass=1.0)],
    )
    readcon.write_con(str(path), [frame])
    positions = readcon.read_positions(str(path))
    one_thread = readcon.read_positions(str(path), n_threads=1)
    coords = readcon.read_coords(str(path))
    assert positions.shape == one_thread.shape == (1, 1, 3)
    assert positions[0, 0, 0] == 1.25
    assert one_thread[0, 0, 0] == positions[0, 0, 0]
    assert coords["positions"][0, 0, 0] == positions[0, 0, 0]
    assert coords["masses"][0, 0] == 1.0
    assert list(coords["cell"][0]) == [10.0, 10.0, 10.0, 90.0, 90.0, 90.0]
    assert coords["n_frames"] == 1
    assert coords["n_atoms"] == 1


def test_string_round_trip_is_the_stdin_text_path() -> None:
    text = readcon.write_con_string([_frame(0.5)], start=0, stop=1)
    back = readcon.read_con_string(text)
    assert len(back) == 1
    assert back[0].metadata["units"]["length"] == "angstrom"
    assert back[0].atoms[0].x == 0.5
