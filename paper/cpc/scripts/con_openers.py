#!/usr/bin/env python3
"""Which toolkits open a CON file: a version-1 file and a CON 3.1 file with per-axis masks.

    python paper/cpc/scripts/con_openers.py

chemfiles, MDAnalysis and Open Babel are asked for CON by format name and, where
they guess, by the ``.con`` extension; OVITO detects formats itself. ASE's eon
reader is the one other CON reader. Writes ``data/failure/con_openers.json``.
"""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import provenance  # noqa: E402

FILES = {
    "version1": ROOT / "data" / "hcn.con",
    "con31": ROOT / "data" / "v31_masks_0to7.con",
}
OUT = ROOT / "data" / "failure" / "con_openers.json"


def first_line(exc: BaseException) -> str:
    text = str(exc).strip().splitlines()
    return f"{type(exc).__name__}: {text[0] if text else ''}"[:200]


def attempt(fn, path: Path) -> dict:
    try:
        atoms = fn(path)
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as exc:  # noqa: BLE001 - chemfiles.ChemfilesError derives from BaseException
        return {"opens": False, "error": first_line(exc)}
    return {"opens": True, "atoms": atoms}


def chemfiles_by_name(path: Path) -> int:
    import chemfiles as cf
    cf.set_warnings_callback(lambda message: None)
    with cf.Trajectory(str(path), "r", "CON") as t:
        return len(t.read().atoms)


def chemfiles_by_extension(path: Path) -> int:
    import chemfiles as cf
    cf.set_warnings_callback(lambda message: None)
    with cf.Trajectory(str(path), "r") as t:
        return len(t.read().atoms)


def mdanalysis_by_name(path: Path) -> int:
    import MDAnalysis as mda
    return len(mda.Universe(str(path), format="CON", topology_format="CON").atoms)


def mdanalysis_by_extension(path: Path) -> int:
    import MDAnalysis as mda
    return len(mda.Universe(str(path)).atoms)


def ovito_detected(path: Path) -> int:
    from ovito.io import import_file
    return import_file(str(path)).compute().particles.count


def openbabel_by_name(path: Path) -> int:
    from openbabel import pybel
    if "con" not in pybel.informats:
        raise ValueError("con is not an Open Babel input format")
    return len(next(pybel.readfile("con", str(path))).atoms)


def ase_eon(path: Path) -> int:
    import ase.io
    return len(ase.io.read(str(path), format="eon"))


READERS = {
    "chemfiles, format CON": chemfiles_by_name,
    "chemfiles, by extension": chemfiles_by_extension,
    "MDAnalysis, format CON": mdanalysis_by_name,
    "MDAnalysis, by extension": mdanalysis_by_extension,
    "OVITO, detected": ovito_detected,
    "Open Babel, format con": openbabel_by_name,
    "ASE eon reader": ase_eon,
}


def main() -> None:
    results = {name: {key: attempt(fn, path) for key, path in FILES.items()} for name, fn in READERS.items()}
    record = {
        "files": {key: provenance.portable(path) for key, path in FILES.items()},
        "readers": results,
        "provenance": provenance.record(),
    }
    OUT.write_text(json.dumps(record, indent=2) + "\n")
    for name, by_file in results.items():
        print(f"{name}: " + "; ".join(f"{k} {'opens' if v['opens'] else v['error']}" for k, v in by_file.items()))


if __name__ == "__main__":
    main()
