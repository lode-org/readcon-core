import gzip
import os
import zlib

import pytest
import readcon

RESOURCES = os.path.join(os.path.dirname(__file__), "..", "..", "resources", "test")


def _read(name):
    with open(os.path.join(RESOURCES, name), "rb") as fh:
        return fh.read()


def _outcome(iterator):
    """Frames as CON text before the first error, then the error text."""
    frames = []
    try:
        for frame in iterator:
            frames.append(readcon.write_con_string([frame]))
    except OSError as e:
        return frames, str(e)
    return frames, None


def _texts():
    frame = _read("cuh2.con")
    five = frame * 5
    bad = frame.replace(b"0.63939999999999997", b"0.6393999999999999x", 1)
    return {
        "five": five,
        "tiny": _read("tiny_multi_cuh2.convel") * 3,
        "cut": five[:-5000],
        "broken": frame * 2 + bad + frame * 2,
    }


@pytest.mark.parametrize("name", ["five", "tiny", "cut", "broken"])
def test_stream_con_matches_iter_con(tmp_path, name):
    text = _texts()[name]
    plain = tmp_path / f"{name}.con"
    plain.write_bytes(text)
    gz = tmp_path / f"{name}.con.gz"
    gz.write_bytes(gzip.compress(text))
    members = tmp_path / f"{name}.members.con.gz"
    third = len(text) // 3
    members.write_bytes(gzip.compress(text[:third]) + gzip.compress(text[third:]))
    for path in (plain, gz, members):
        want = _outcome(readcon.iter_con(str(path)))
        if name == "five":
            assert len(want[0]) == 5 and want[1] is None
        if name in ("cut", "broken"):
            assert want[1] is not None and want[1].startswith("parse error: ")
        stream = readcon.stream_con(str(path))
        assert iter(stream) is stream
        assert _outcome(stream) == want, path.name
        assert next(stream, None) is None


@pytest.mark.parametrize(
    "copies, cut",
    [(5, 1), (5, 8), (80, 1), (80, "half")],
)
def test_stream_con_truncated_gzip_gives_decoded_frames_then_the_error(
    tmp_path, copies, cut
):
    data = gzip.compress(_read("cuh2.con") * copies)
    data = data[: len(data) // 2] if cut == "half" else data[:-cut]
    gz = tmp_path / "cut.con.gz"
    gz.write_bytes(data)
    with pytest.raises(OSError) as err:
        _outcome(readcon.iter_con(str(gz)))
    decoded = tmp_path / "decoded.con"
    decoded.write_bytes(zlib.decompressobj(wbits=31).decompress(data))
    frames = _outcome(readcon.iter_con(str(decoded)))[0]
    if cut == "half":
        assert 0 < len(frames) < copies
    else:
        assert len(frames) == copies
    stream = readcon.stream_con(str(gz))
    assert _outcome(stream) == (frames, str(err.value))
    assert next(stream, None) is None


def test_stream_con_open_errors_match_iter_con(tmp_path):
    missing = str(tmp_path / "missing.con")
    with pytest.raises(OSError) as want:
        readcon.iter_con(missing)
    with pytest.raises(OSError) as got:
        readcon.stream_con(missing)
    assert str(got.value) == str(want.value)
