"""Entry point for every Snakemake head-to-head rule.

The rule pins the process to one core and calls one arm. Each arm lives in an
asv module and records six serial samples.
"""

from __future__ import annotations

import fcntl
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import measure
import support

_LOCK = None


def _hold_lock() -> None:
    global _LOCK
    path = support.WORK / "campaign.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    _LOCK = path.open("a", encoding="utf-8")
    fcntl.flock(_LOCK.fileno(), fcntl.LOCK_EX)


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("missing arm")
    arm = sys.argv[1]
    if arm == "fresh-once":
        support.ensure_pinned()
        measure.fresh_once(Path(sys.argv[2]))
        return
    support.ensure_pinned()
    _hold_lock()
    if arm == "prepare":
        support.prepare()
        return
    if arm == "report":
        measure.write_report()
        return
    runners = {
        "readcon_c": measure.run_readcon_c,
        "readcon_fortran": measure.run_readcon_fortran,
        "readcon_python": measure.run_readcon_python,
        "eon_cpp": measure.run_eon_cpp,
        "eon_python": measure.run_eon_python,
        "ase": measure.run_ase,
        "chemfiles": lambda: measure.run_native("chemfiles"),
        "mdanalysis": lambda: measure.run_native("mdanalysis"),
        "ovito": lambda: measure.run_native("ovito"),
        "pymatgen": lambda: measure.run_native("pymatgen"),
        "numpy": lambda: measure.run_native("numpy"),
        "ase_traj": lambda: measure.run_native("ase_traj"),
    }
    if arm not in runners:
        raise SystemExit(f"unknown arm {arm}")
    runners[arm]()


if __name__ == "__main__":
    main()
