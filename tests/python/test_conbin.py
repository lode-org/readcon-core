"""Round-trips and error cases for the CON-bin readers."""

import struct
from pathlib import Path

import numpy as np
import pytest

import readcon

RESOURCES = Path(__file__).resolve().parents[2] / "resources" / "test"
TINY = RESOURCES / "tiny_cuh2.con"
WITH_VELOCITY = RESOURCES / "tiny_cuh2.convel"

# Layout of the six header fields. Offsets match the spec table.
MAGIC = b"CONBIN01"
MAGIC_LEN = len(MAGIC)
VERSION_BYTES = 4
FLAGS_BYTES = 4
COUNT_BYTES = 8
FLAGS_OFFSET = MAGIC_LEN + VERSION_BYTES
COUNTS_OFFSET = FLAGS_OFFSET + FLAGS_BYTES
OFFSET_FIELD = COUNTS_OFFSET + COUNT_BYTES + COUNT_BYTES
COORDS_PER_ATOM = 3
F32_BYTES = 4
F64_BYTES = 8

# An aligned offset that still sits inside the 40-byte header fields.
INSIDE_HEADER_OFFSET = COUNTS_OFFSET + F32_BYTES


def _require_conbin():
    if not hasattr(readcon, "write_conbin"):
        pytest.skip("CON-bin readers are built on Unix only")


def _write(tmp_path, binary32, source=TINY):
    out = tmp_path / ("f32.conbin" if binary32 else "f64.conbin")
    n_frames, n_atoms = readcon.write_conbin(str(source), str(out), binary32)
    return out, n_frames, n_atoms


def _positions_from_text(frame, dtype):
    return np.array(
        [[atom.x, atom.y, atom.z] for atom in frame.atoms],
        dtype=dtype,
    )


def test_f64_round_trip_without_velocities(tmp_path):
    _require_conbin()
    path, n_frames, n_atoms = _write(tmp_path, False)
    text = readcon.read_con(str(TINY))
    assert text[0].vel is None
    pos, vel, n = readcon.read_conbin(str(path))
    assert n_frames == 1
    assert n == n_atoms == len(text[0])
    assert pos.shape == (1, n_atoms * COORDS_PER_ATOM)
    # The writer stores a velocity run of zeros when the text has none.
    assert vel.shape == pos.shape
    assert np.all(np.asarray(vel) == 0)
    got = np.asarray(pos).reshape(n_atoms, COORDS_PER_ATOM)
    assert np.array_equal(got, _positions_from_text(text[0], np.float64))


def test_f64_round_trip_with_velocities(tmp_path):
    _require_conbin()
    path, _n_frames, n_atoms = _write(tmp_path, False, WITH_VELOCITY)
    text = readcon.read_con(str(WITH_VELOCITY))
    pos, vel, n = readcon.read_conbin(str(path))
    assert n == n_atoms
    assert vel is not None
    got = np.asarray(pos).reshape(n_atoms, COORDS_PER_ATOM)
    assert np.array_equal(got, _positions_from_text(text[0], np.float64))
    assert np.array_equal(
        np.asarray(vel).reshape(n_atoms, COORDS_PER_ATOM), np.asarray(text[0].vel)
    )


def test_f32_file_is_not_read_as_binary64(tmp_path):
    _require_conbin()
    path, _n_frames, _n_atoms = _write(tmp_path, True)
    with pytest.raises(ValueError, match="binary32"):
        readcon.read_conbin(str(path))


def test_bad_magic(tmp_path):
    _require_conbin()
    path, _n_frames, _n_atoms = _write(tmp_path, False)
    data = bytearray(path.read_bytes())
    data[:MAGIC_LEN] = b"NOTABIN!"
    path.write_bytes(data)
    with pytest.raises(OSError, match="CONBIN01"):
        readcon.read_conbin(str(path))


def test_offset_inside_header(tmp_path):
    _require_conbin()
    path, _n_frames, _n_atoms = _write(tmp_path, False)
    data = bytearray(path.read_bytes())
    struct.pack_into("<Q", data, OFFSET_FIELD, INSIDE_HEADER_OFFSET)
    path.write_bytes(data)
    with pytest.raises(OSError, match="payload offset"):
        readcon.read_conbin(str(path))


def test_truncated_payload(tmp_path):
    _require_conbin()
    path, _n_frames, _n_atoms = _write(tmp_path, False)
    data = path.read_bytes()
    offset = struct.unpack_from("<Q", data, OFFSET_FIELD)[0]
    path.write_bytes(data[: offset + F64_BYTES])
    with pytest.raises((OSError, ValueError), match="ended unexpectedly"):
        readcon.read_conbin(str(path))
