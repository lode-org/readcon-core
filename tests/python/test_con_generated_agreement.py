"""Generated ``.con`` and convel frames through the Python and ASE paths.

A write followed by a read returns the same frames. ``read_con_string``,
``read_con``, and ``ConFrame.to_ase`` / ``from_ase`` agree. Damaged text
raises instead of returning a shorter trajectory.
"""

import struct

import pytest

ase = pytest.importorskip("ase")
import readcon


def _bits(value):
    return struct.unpack("<Q", struct.pack("<d", float(value)))[0]


def _atom(symbol, xyz, fixed, atom_id, mass, velocity=None, force=None):
    kwargs = {}
    if velocity is not None:
        kwargs["vx"], kwargs["vy"], kwargs["vz"] = velocity
    if force is not None:
        kwargs["fx"], kwargs["fy"], kwargs["fz"] = force
    return readcon.Atom(
        symbol=symbol,
        x=xyz[0],
        y=xyz[1],
        z=xyz[2],
        fixed=list(fixed),
        atom_id=atom_id,
        mass=mass,
        **kwargs,
    )


def _frame(atoms):
    return readcon.ConFrame([10.5, 11.0, 12.25], [90.0, 90.0, 120.0], atoms)


def _geometry():
    return _frame(
        [
            _atom("Cu", (0.0, -0.0, 1.0), (True, False, False), 10, 63.546, (-0.0, 0.1, -0.2), (0.0, -0.0, 1.5)),
            _atom("H", (1.25e-10, -1.0e20, 2.5), (False, True, False), 11, 1.008, (1.0e-20, 0.0, -0.0), (-2.0, 3.0, -4.0)),
            _atom("O", (1.7976931348623157e308, -1.5, 4.0), (True, True, True), 12, 15.999, (0.5, -0.5, 0.25), (1.0e-8, 9.0, -0.0)),
        ]
    )


def _one():
    return _frame([_atom("He", (-0.0, 2.5e-7, -1.5), (False, False, True), 7, 4.0026)])


def _rows(frame):
    out = []
    for atom in frame.atoms:
        velocity = None if atom.vx is None else (_bits(atom.vx), _bits(atom.vy), _bits(atom.vz))
        force = None if atom.fx is None else (_bits(atom.fx), _bits(atom.fy), _bits(atom.fz))
        out.append(
            (
                atom.symbol,
                _bits(atom.x),
                _bits(atom.y),
                _bits(atom.z),
                tuple(bool(flag) for flag in atom.fixed),
                int(atom.atom_id),
                _bits(atom.mass),
                velocity,
                force,
            )
        )
    return out


def _same(got, expect):
    assert len(got) == len(expect)
    for left, right in zip(got, expect):
        assert _rows(left) == _rows(right)
        assert [_bits(value) for value in left.cell] == [_bits(value) for value in right.cell]
        assert [_bits(value) for value in left.angles] == [_bits(value) for value in right.angles]


def _read_paths(text, tmp_path, name):
    string_frames = readcon.read_con_string(text)
    path = tmp_path / name
    path.write_bytes(text.encode("utf-8"))
    file_frames = readcon.read_con(str(path), n_threads=1)
    threaded = readcon.read_con(str(path), n_threads=4)
    _same(string_frames, file_frames)
    _same(threaded, file_frames)
    return file_frames


def test_python_round_trip_matches_file_and_threads(tmp_path):
    frames = [_geometry(), _one(), _frame([])]
    text = readcon.write_con_string(frames)
    got = _read_paths(text, tmp_path, "generated.con")
    _same(got, frames)
    crlf = text.replace("\n", "\r\n")
    _same(_read_paths(crlf, tmp_path, "generated-crlf.con"), frames)
    bare = text[:-1] if text.endswith("\n") else text
    _same(_read_paths(bare, tmp_path, "generated-bare.convel"), frames)


def test_scientific_notation_and_signed_zero(tmp_path):
    text = readcon.write_con_string([_one()])
    marker = "Coordinates of Component 1\n"
    at = text.find(marker) + len(marker)
    line_end = text.find("\n", at)
    parts = text[at:line_end].split()
    parts[0] = "-0.0e0"
    parts[1] = "1.25e-10"
    parts[2] = "-1.0E+2"
    rewritten = text[:at] + " ".join(parts) + text[line_end:]
    got = _read_paths(rewritten, tmp_path, "scientific.con")
    assert _bits(got[0].atoms[0].x) == _bits(-0.0)
    assert _bits(got[0].atoms[0].y) == _bits(1.25e-10)
    assert _bits(got[0].atoms[0].z) == _bits(-100.0)


def test_ase_path_matches_python_frames():
    frames = [_geometry(), _one()]
    text = readcon.write_con_string(frames)
    read_back = readcon.read_con_string(text)
    for original in read_back:
        restored = readcon.ConFrame.from_ase(original.to_ase())
        assert _rows(restored) == _rows(original)


def test_zero_count_and_truncated_text_raise(tmp_path):
    text = """\
zero count
{"con_spec_version":3,"con_spec_minor":1,"units":{"length":"angstrom","energy":"eV","mass":"amu","time":"fs"}}
1.0 1.0 1.0
90.0 90.0 90.0
0 0
0 0 0
2
1 0
4.0 12.0
He
Coordinates of Component 1
0.0 0.0 0.0 0 1
"""
    with pytest.raises(Exception, match="count"):
        readcon.read_con_string(text)

    whole = readcon.write_con_string([_geometry(), _one()])
    label = "Coordinates of Component 1\n"
    cut = whole.rfind(label) + len(label)
    with pytest.raises(Exception, match="ended unexpectedly"):
        readcon.read_con_string(whole[:cut])
    path = tmp_path / "torn.con"
    path.write_text(whole[:cut], encoding="utf-8")
    with pytest.raises(Exception, match="ended unexpectedly"):
        readcon.read_con(str(path))
    with pytest.raises(Exception, match="ended unexpectedly|JSON|invalid"):
        readcon.read_con_string(whole + 'partial\n{"con_spec_version":3}\n1.0')


def test_bad_tokens_name_the_problem():
    text = readcon.write_con_string([_one()])
    marker = "Coordinates of Component 1\n"
    at = text.find(marker) + len(marker)
    line_end = text.find("\n", at)
    for row, needle in (
        ("nan 0.0 0.0 0 1", "non-finite"),
        ("0.0 0.0 0.0 8 1", "fixed"),
        ("0.0 1e 0.0 0 1", "invalid"),
    ):
        damaged = text[:at] + row + text[line_end:]
        with pytest.raises(Exception, match=needle):
            readcon.read_con_string(damaged)
