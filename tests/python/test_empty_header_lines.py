"""Empty header lines on the Python readers, including the streaming iterator."""

from pathlib import Path

import readcon

CORPUS = Path(__file__).resolve().parents[2] / "resources" / "conformance" / "valid"


def test_iter_con_keeps_an_empty_user_line():
    frames = list(readcon.iter_con(str(CORPUS / "empty_user_line.con")))
    assert len(frames) == 1
    assert frames[0].prebox_header[0] == ""
    assert frames[0].prebox_header[1].startswith("{")
    assert frames[0].spec_version == 2


def test_read_con_string_keeps_two_empty_user_lines():
    text = (CORPUS / "empty_user_line_two.con").read_text()
    frames = readcon.read_con_string(text)
    assert len(frames) == 2
    assert [frame.prebox_header[0] for frame in frames] == ["", ""]
    assert [frame.spec_version for frame in frames] == [2, 2]
    streamed = list(readcon.iter_con(str(CORPUS / "empty_user_line_two.con")))
    assert len(streamed) == 2
    assert streamed[1].prebox_header[0] == ""


def test_empty_line_two_is_version_one():
    line2 = readcon.read_con_string((CORPUS / "empty_line2.con").read_text())
    assert len(line2) == 1
    assert list(line2[0].prebox_header) == ["generator", ""]
    assert line2[0].spec_version == 1

    both = readcon.read_con_string((CORPUS / "empty_header_both.con").read_text())
    assert len(both) == 1
    assert list(both[0].prebox_header) == ["", ""]
    assert both[0].spec_version == 1
