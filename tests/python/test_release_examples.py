"""Examples from the 0.19 how-to: threads, append, gzip, stdin text, units."""

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


def test_string_round_trip_is_the_stdin_text_path() -> None:
    text = readcon.write_con_string([_frame(0.5)], start=0, stop=1)
    back = readcon.read_con_string(text)
    assert len(back) == 1
    assert back[0].metadata["units"]["length"] == "angstrom"
    assert back[0].atoms[0].x == 0.5
