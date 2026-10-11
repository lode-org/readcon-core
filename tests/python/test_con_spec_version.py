"""A CON 3.1 file keeps con_spec_version in frame metadata."""

import readcon

V31 = """\
CON 3.1
{"con_spec_version":3,"con_spec_minor":1,"units":{"length":"angstrom","energy":"eV","mass":"amu"}}
10.000000 10.000000 10.000000
90.000000 90.000000 90.000000


1
1
1.007940
H
Coordinates of Component 1
0.000000 0.000000 0.000000 0 0
"""


def test_con_31_metadata_reports_spec_major_and_rewrite_matches():
    frame = readcon.read_con_string(V31)[0]
    assert frame.spec_version == 3
    assert frame.metadata["con_spec_version"] == 3
    assert frame.metadata["con_spec_minor"] == 1
    first = readcon.write_con_string([frame])
    again = readcon.read_con_string(first)[0]
    assert again.metadata["con_spec_version"] == 3
    second = readcon.write_con_string([again])
    assert first == second
