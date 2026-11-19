"""``gen_spec_supp.reference_cellpar_to_cell`` is ``ase.geometry.cellpar_to_cell`` without ASE.

The CON-cell.6 check of the supplement compares the parsed formula with ASE,
and a host without ASE compares it with this construction. The construction
must give ASE's cell bit for bit and fail where ASE fails, with the same
error, or a host without ASE would check against a different function.
"""

from __future__ import annotations

import importlib.util
import random
import sys
import warnings
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "paper" / "cpc" / "scripts" / "gen_spec_supp.py"

# Cells for which 1 - cos_beta**2 - cy**2 and 1 - cos_beta*cos_beta - cy*cy differ in the last bit.
POW_CELLS = [
    [13.555, 18.118, 6.077, 70.05, 103.05, 103.05],
    [3.383, 5.31, 18.769, 112.23, 115.09, 115.23],
    [11.154, 2.203, 10.799, 115.8, 63.68, 68.35],
    [10.461, 3.755, 16.67, 86.11, 70.41, 70.72],
    [2.348, 3.878, 9.226, 62.97, 101.64, 62.93],
    [12.759, 10.149, 14.772, 92.98, 70.41, 105.1],
]
DEGENERATE = [
    [3.0, 4.0, 5.0, 90.0, 90.0, 90.0],
    [3.0, 4.0, 5.0, 90.0, 90.0, -90.0],
    [3.0, 4.0, 5.0, 90.0 + 1e-15, 90.0 - 1e-15, 90.0 + 1e-14],
    [3.0, 4.0, 5.0, 90.0, 90.0, 0.0],
    [3.0, 4.0, 5.0, 90.0, 90.0, 180.0],
    [3.0, 4.0, 5.0, 0.0, 0.0, 60.0],
    [3.0, 4.0, 5.0, 180.0, 90.0, 60.0],
    [3.0, 4.0, 5.0, 10.0, 170.0, 120.0],
    [1.0, 1.0, 1.0, 120.0, 120.0, 120.0],
    [0.0, 4.0, 5.0, 60.0, 70.0, 80.0],
]


def _load():
    spec = importlib.util.spec_from_file_location("gen_spec_supp_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _outcome(function, cellpar: list[float]):
    """The nine bit patterns of the cell, or the name of the exception."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            cell = function(cellpar)
        except Exception as error:
            return type(error).__name__
    return [float(value).hex() for row in cell for value in row]


def _random_cells(count: int) -> list[list[float]]:
    rng = random.Random(20260217)
    return [
        [rng.uniform(0.1, 50.0) for _ in range(3)]
        + [rng.uniform(15.0, 165.0) for _ in range(3)]
        for _ in range(count)
    ]


def test_reference_cell_is_exact_where_the_cell_is_orthogonal() -> None:
    reference = _load().reference_cellpar_to_cell
    assert np.array_equal(
        reference([3.0, 4.0, 5.0, 90.0, 90.0, 90.0]), np.diag([3.0, 4.0, 5.0])
    )


def test_reference_cell_fails_like_ase_where_gamma_is_zero() -> None:
    reference = _load().reference_cellpar_to_cell
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for cellpar in (DEGENERATE[3], DEGENERATE[5]):
            with pytest.raises(AssertionError):
                reference(cellpar)


def test_reference_cell_is_bit_identical_to_ase() -> None:
    reference = _load().reference_cellpar_to_cell
    if importlib.util.find_spec("ase") is not None:
        from ase.geometry import cellpar_to_cell

        cells = POW_CELLS + DEGENERATE + _random_cells(50000)
        differing = [
            cellpar
            for cellpar in cells
            if _outcome(reference, cellpar) != _outcome(cellpar_to_cell, cellpar)
        ]
        assert differing == [], differing[:3]
        errors = [_outcome(cellpar_to_cell, cellpar) for cellpar in DEGENERATE]
        assert "AssertionError" in errors, errors
        assert "ZeroDivisionError" not in errors, errors


def test_the_run_says_which_cell_check_ran(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load()
    check = module.org_source()[2]
    if importlib.util.find_spec("ase") is not None:
        assert check == "matches ase.geometry.cellpar_to_cell on 200 random cells"
    monkeypatch.setitem(sys.modules, "ase", None)
    monkeypatch.setitem(sys.modules, "ase.geometry", None)
    check = module.org_source()[2]
    assert "numpy construction of ase.geometry.cellpar_to_cell" in check, check
    assert "ASE is not installed" in check, check
    assert check.endswith("on 200 random cells"), check


def test_spec_macros_accept_the_matching_unreleased_tree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load()
    current = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    record = tmp_path / "measurement.json"
    record.write_text(
        '{"tags": [], "tree": {"release": '
        f'"{current}", "tagged": false, "spec_blob": "current-blob"}}}}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "SPEC", tmp_path / "spec.org")
    monkeypatch.setattr(module, "VERSIONS", record)
    monkeypatch.setattr(module, "package_version", lambda: current)
    monkeypatch.setattr(
        module, "git", lambda *args, **kwargs: SimpleNamespace(stdout="current-blob\n")
    )
    rendered = module.spec_macros("- CON-test.1 :: MUST :: test\n")
    assert rf"\newcommand{{\specTextRelease}}{{{current}}}" in rendered

    monkeypatch.setattr(module, "package_version", lambda: "9.9.9")
    with pytest.raises(SystemExit, match="no release tag"):
        module.spec_macros("- CON-test.1 :: MUST :: test\n")
