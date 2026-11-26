"""A POSCAR velocity row must name a convention, not the lack of one."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_manuscript.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_manuscript_velocity", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_angstrom_per_fs_is_a_convention_and_no_unit_convention_is_not() -> None:
    cm = _load()
    assert cm.velocity_row_problems("angstrom/fs convention, not declared") == []
    assert cm.velocity_row_problems("natural unit, no in-file declaration") == []
    problems = cm.velocity_row_problems("no unit convention, not declared")
    assert problems
    assert cm.velocity_row_problems("angstrom/fs convention")
