"""The independent reader follows CON-coord.1 and CON-units.8."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
FRAME = """\
corpus31 minor-1 convel, time fs
{"con_spec_version":3,"con_spec_minor":1,"units":{"length":"angstrom","energy":"eV","mass":"amu","time":"fs"},"sections":["velocities"]}
10.0 10.0 10.0
90.0 90.0 90.0
0 0
0 0 0
1
2
195.084
Pt
Coordinates of Component 1
0.0 0.0 0.0 0 0
2.5 2.5 0.0 0 1

Pt
Velocities of Component 1
0.01 0.0 0.0 0 0
0.0 -0.02 0.0 0 1
"""


def _reader():
    sys.path.insert(0, str(SCRIPTS))
    import indep_reader

    return indep_reader


def test_major_3_velocities_use_the_natural_unit() -> None:
    indep_reader = _reader()
    frame = indep_reader.read_text(FRAME)[0]
    assert frame["major"] == 3
    assert frame["time_unit"] == indep_reader.NATURAL_TIME
    assert frame["time_override"] == ("fs", indep_reader.NATURAL_TIME)


def test_a_coordinate_label_is_checked_when_validate_is_off() -> None:
    indep_reader = _reader()
    bad = FRAME.replace("Coordinates of Component 1", "Coordinates of CompXnent 1", 1)
    try:
        indep_reader.read_text(bad)
    except indep_reader.Rejection as exc:
        assert exc.cls == "ValidationError"
    else:
        raise AssertionError("a bad coordinate label was accepted")
