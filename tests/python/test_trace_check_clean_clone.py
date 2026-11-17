"""``trace_numbers.py --check`` is green on a clean clone's first run.

``paper/cpc/data/trace/`` is gitignored, so a fresh checkout has no ledger.
``--check`` must build the ledger it needs before checking, so the first run
reports no drift rather than a missing ledger.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "paper" / "cpc" / "scripts" / "trace_numbers.py"
LEDGER = ROOT / "paper" / "cpc" / "data" / "trace" / "numbers.csv"


def test_check_builds_the_ledger_on_a_clean_tree() -> None:
    had_ledger = LEDGER.is_file()
    backup = LEDGER.read_bytes() if had_ledger else None
    if had_ledger:
        LEDGER.unlink()
    try:
        done = subprocess.run(
            [sys.executable, str(SCRIPT), "--check"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert done.returncode == 0, done.stdout + done.stderr
        assert "0 problems" in done.stdout, done.stdout
        assert LEDGER.is_file(), "--check did not build the missing ledger"
    finally:
        if backup is not None:
            LEDGER.write_bytes(backup)
