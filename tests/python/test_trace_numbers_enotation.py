"""The number scanner reads e-notation inside ``\\num{...}`` as one number.

A siunitx ``\\num{2.2606e-3}`` must be traced as the single value 0.0022606,
not split into a dropped mantissa and a bare integer ``3``.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "paper" / "cpc" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import trace_numbers  # noqa: E402


def _scan(line: str):
    return trace_numbers.scan_lines("rg_main.tex", [(1, line)])


def test_num_enotation_is_one_number() -> None:
    printed, identifiers = _scan(
        r"readcon-db takes a median of \num{2.2606e-3}~s here."
    )
    normals = [p.normal for p in printed]
    assert "2.2606e-3" in normals, normals
    one = next(p for p in printed if p.normal == "2.2606e-3")
    assert abs(float(one.value) - 0.0022606) < 1e-12
    # The exponent is not left behind as a bare integer, printed or identifier.
    assert all(p.normal != "3" for p in printed), normals
    assert all(text != "3" for _, _, text, *_ in identifiers), identifiers


def test_num_enotation_variants_are_whole_numbers() -> None:
    cases = {
        "5.5270e-3": 0.0055270,
        "1.9523e-2": 0.019523,
        "1.939e-2": 0.01939,
        "3.447e-2": 0.03447,
    }
    for text, value in cases.items():
        printed, _ = _scan(rf"the read is \num{{{text}}}~s here.")
        normals = [p.normal for p in printed]
        assert text in normals, (text, normals)
        one = next(p for p in printed if p.normal == text)
        assert abs(float(one.value) - value) < 1e-12, (text, one.value)


def test_plain_num_is_still_read() -> None:
    printed, _ = _scan(r"the ratio is \num{0.6440} of the raw time.")
    assert any(p.normal == "0.6440" for p in printed)
