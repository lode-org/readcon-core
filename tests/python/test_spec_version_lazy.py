"""The selected major is written before atoms are materialised."""

import json

import readcon

MAJOR4 = """\
seed
{"con_spec_version":4,"units":{"length":"angstrom","energy":"eV"}}
10 10 10
90 90 90
0 0
0 0 0
1
1
1.0
H
Coordinates of Component 1
0 0 0 0 0
"""

MAJOR4_FS = """\
seed
{"con_spec_version":4,"units":{"length":"angstrom","energy":"eV","time":"fs"},"sections":["velocities"]}
10 10 10
90 90 90
0 0
0 0 0
1
1
1.0
H
Coordinates of Component 1
0 0 0 0 0

H
Velocities of Component 1
0.1 0 0 0 0
"""


def _major(text: str) -> int:
    return json.loads(text.splitlines()[1])["con_spec_version"]


def test_spec_version_setter_before_atoms():
    frames = readcon.read_con_string(MAJOR4)
    frame = frames[0]
    assert frame.atoms_materialized is False
    assert frame.spec_version == 4
    frame.spec_version = 3
    assert frame.spec_version == 3
    assert frame.atoms_materialized is False
    assert _major(readcon.write_con_string([frame])) == 3
    assert frame.atoms_materialized is False
    assert _major(readcon.write_con_string(frames)) == 3


def test_spec_version_setter_before_atoms_with_legacy_time():
    frames = readcon.read_con_string(MAJOR4_FS)
    frame = frames[0]
    assert frame.atoms_materialized is False
    assert frame.has_velocities is True
    frame.spec_version = 3
    assert _major(readcon.write_con_string([frame])) == 3
    _ = frame.atoms
    assert _major(readcon.write_con_string([frame])) == 3


def test_spec_version_setter_after_atoms():
    frames = readcon.read_con_string(MAJOR4)
    frame = frames[0]
    _ = frame.atoms
    assert frame.atoms_materialized is True
    frame.spec_version = 3
    assert _major(readcon.write_con_string([frame])) == 3
