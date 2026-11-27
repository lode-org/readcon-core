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


NO_TIME = FRAME.replace(
    '"units":{"length":"angstrom","energy":"eV","mass":"amu","time":"fs"}',
    '"units":{"length":"angstrom","energy":"eV","mass":"amu"}',
    1,
)


def test_needs_time_starts_at_major_4() -> None:
    """Major 4 with velocities and no units.time is invalid; major 3 is not.

    spec_major rejects an unknown major before this line, so this test admits
    major 4 for the call. ``major > 4`` would accept that frame, and
    ``major >= 3`` would reject the major-3 frame.
    """
    indep_reader = _reader()
    known = indep_reader.KNOWN_MAJORS
    indep_reader.KNOWN_MAJORS = (2, 3, 4)
    try:
        assert indep_reader.read_text(NO_TIME)[0]["major"] == 3
        major4 = NO_TIME.replace(
            '"con_spec_version":3,"con_spec_minor":1',
            '"con_spec_version":4,"con_spec_minor":0',
            1,
        )
        try:
            indep_reader.read_text(major4)
        except indep_reader.Rejection as exc:
            assert exc.cls == "InvalidUnits"
            assert exc.clause == "CON-units.11"
        else:
            raise AssertionError("major 4 velocities without units.time were accepted")
    finally:
        indep_reader.KNOWN_MAJORS = known


def _admit_major4(indep_reader):
    known = indep_reader.KNOWN_MAJORS
    indep_reader.KNOWN_MAJORS = (2, 3, 4)
    return known


def test_major4_without_velocities_needs_no_time() -> None:
    """The needs_time rejection applies only when a velocities section is named.

    Dropping that conjunct rejects a major-4 frame that stores no velocities.
    """
    indep_reader = _reader()
    known = _admit_major4(indep_reader)
    text = NO_TIME.replace(
        '"con_spec_version":3,"con_spec_minor":1,"units":{"length":"angstrom","energy":"eV","mass":"amu"},"sections":["velocities"]',
        '"con_spec_version":4,"con_spec_minor":0,"units":{"length":"angstrom","energy":"eV","mass":"amu"},"sections":[]',
        1,
    )
    head, _, _ = text.partition("\n\nPt\nVelocities")
    try:
        frame = indep_reader.read_text(head + "\n")[0]
    finally:
        indep_reader.KNOWN_MAJORS = known
    assert frame["major"] == 4
    assert frame["velocities"] is None


def test_legacy_major4_velocities_need_a_time_unit() -> None:
    """A legacy velocity block on major 4 without units.time is invalid.

    Replacing ``if needs_time`` with false on the legacy path accepts it.
    """
    indep_reader = _reader()
    known = _admit_major4(indep_reader)
    text = FRAME.replace(
        '{"con_spec_version":3,"con_spec_minor":1,"units":{"length":"angstrom","energy":"eV","mass":"amu","time":"fs"},"sections":["velocities"]}',
        '{"con_spec_version":4,"con_spec_minor":0,"units":{"length":"angstrom","energy":"eV","mass":"amu"}}',
        1,
    )
    try:
        try:
            indep_reader.read_text(text)
        except indep_reader.Rejection as exc:
            assert exc.cls == "InvalidUnits"
            assert exc.clause == "CON-units.11"
        else:
            raise AssertionError(
                "legacy major-4 velocities without units.time were accepted"
            )
    finally:
        indep_reader.KNOWN_MAJORS = known


def test_a_coordinate_label_is_checked_when_validate_is_off() -> None:
    indep_reader = _reader()
    bad = FRAME.replace("Coordinates of Component 1", "Coordinates of CompXnent 1", 1)
    try:
        indep_reader.read_text(bad)
    except indep_reader.Rejection as exc:
        assert exc.cls == "ValidationError"
    else:
        raise AssertionError("a bad coordinate label was accepted")
