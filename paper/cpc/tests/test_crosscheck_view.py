"""applied_unit and pbc_effective are what the cross-check compares."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "corpus_crosscheck.py"
NATURAL = "(u*Å^2/eV)^0.5"
MAJOR3_NO_TIME = """\
corpus31 minor-1 convel, no time
{"con_spec_version":3,"con_spec_minor":1,"units":{"length":"angstrom","energy":"eV","mass":"amu"},"sections":["velocities"]}
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
MAJOR4_TIME = """\
corpus31 major 4
{"con_spec_version":4,"con_spec_minor":0,"units":{"length":"angstrom","energy":"eV","mass":"amu","time":"fs"}}
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
"""
PBC_ABSENT = """\
corpus31 version 2 without pbc
{"con_spec_version":2}
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
"""
PBC_PARTIAL = """\
corpus31 pbc slab
{"con_spec_version":3,"con_spec_minor":1,"units":{"length":"angstrom","energy":"eV","mass":"amu","time":"fs"},"sections":[],"pbc":[true,true,false]}
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
"""
PBC_FULL = PBC_PARTIAL.replace('"pbc":[true,true,false]', '"pbc":[true,true,true]', 1)


def _module():
    sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("corpus_crosscheck_view", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _frame(tmp_path: Path, text: str, name: str):
    readcon = pytest.importorskip("readcon")
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return readcon.read_con(str(path))[0]


def test_major3_without_units_time_uses_the_natural_unit(tmp_path: Path) -> None:
    frame = _frame(tmp_path, MAJOR3_NO_TIME, "major3.convel")
    assert frame.spec_version == 3
    assert (frame.metadata or {}).get("units", {}).get("time") is None
    assert _module().applied_unit(frame) == NATURAL


def test_major4_uses_the_declared_time_unit(tmp_path: Path) -> None:
    frame = _frame(tmp_path, MAJOR4_TIME, "major4.con")
    assert frame.spec_version == 4
    assert _module().applied_unit(frame) == "fs"


def test_pbc_absent_partial_and_full_come_from_pbc_effective(tmp_path: Path) -> None:
    module = _module()
    cases = (
        ("absent.con", PBC_ABSENT, [True, True, True]),
        ("partial.con", PBC_PARTIAL, [True, True, False]),
        ("full.con", PBC_FULL, [True, True, True]),
    )
    for name, text, want in cases:
        frame = _frame(tmp_path, text, name)
        assert list(frame.pbc_effective) == want
        assert module.readcon_view([frame])[0]["pbc"] == want
