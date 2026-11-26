"""The Fortran module's stored standard is Fortran 2008."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

CPC = Path(__file__).resolve().parents[1]


def test_the_fortran_record_matches_the_source() -> None:
    done = subprocess.run(
        [sys.executable, str(CPC / "scripts" / "fortran_standard.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
