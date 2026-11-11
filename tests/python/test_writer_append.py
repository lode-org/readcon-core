"""Append and in-memory CON writes."""

import readcon


def frames():
    out = []
    for index in range(3):
        out.append(
            readcon.ConFrame(
                cell=[4.0, 4.0, 4.0],
                angles=[90.0, 90.0, 90.0],
                atoms=[
                    readcon.Atom(
                        symbol="Cu",
                        x=float(index),
                        y=0.1,
                        z=0.2,
                        atom_id=index,
                        fixed=[False, False, False],
                    )
                ],
            )
        )
    return out


def test_append_matches_whole_file_and_string(tmp_path):
    written = frames()
    whole = tmp_path / "whole.con"
    readcon.write_con(str(whole), written)
    part = tmp_path / "part.con"
    readcon.write_con(str(part), written[:1])
    readcon.write_con(str(part), written[1:], append=True)
    assert part.read_bytes() == whole.read_bytes()
    assert readcon.write_con_string(written).encode() == whole.read_bytes()
    readcon.write_con(str(part), written[:1])
    assert part.read_bytes() == readcon.write_con_string(written[:1]).encode()


def test_append_refuses_gzip(tmp_path):
    path = tmp_path / "x.con.gz"
    try:
        readcon.write_con(str(path), frames()[:1], append=True)
    except ValueError as exc:
        assert "uncompressed" in str(exc)
    else:
        raise AssertionError("gzip append was accepted")
