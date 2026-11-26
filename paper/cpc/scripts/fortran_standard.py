#!/usr/bin/env python3
"""Check the stored Fortran standard of the readcon module.

``--check`` needs no compiler. It fails unless the stored digest is that of
``fortran/ReadCon/src/readcon.f90`` and the stored standard follows the results.
``standard.json`` is the earlier record; this series reads the referee record.

    python3 paper/cpc/scripts/fortran_standard.py --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
SOURCE = "fortran/ReadCon/src/readcon.f90"
STANDARDS = {
    "f95": "Fortran 95",
    "f2003": "Fortran 2003",
    "f2008": "Fortran 2008",
    "f2018": "Fortran 2018",
}


def digest() -> str:
    return hashlib.sha256((REPO / SOURCE).read_bytes()).hexdigest()


def oldest(results: dict) -> str:
    accepted = [std for std in STANDARDS if results[std]["accepted"]]
    if not accepted:
        raise SystemExit(f"{SOURCE}: no standard accepts the module")
    names = list(STANDARDS)
    if accepted != names[names.index(accepted[0]) :]:
        raise SystemExit(f"{SOURCE}: a newer standard rejects the module: {results}")
    return accepted[0]


def check(record: dict) -> list[str]:
    problems = []
    if record["source_sha256"] != digest():
        problems.append(f"{SOURCE} changed since the record was written")
    if set(record["results"]) != set(STANDARDS):
        problems.append(
            f"the record tests {sorted(record['results'])}, not {sorted(STANDARDS)}"
        )
        return problems
    std = oldest(record["results"])
    if (record["oldest_accepted"], record["standard"]) != (std, STANDARDS[std]):
        problems.append(
            f"the record names {record['standard']}, but its results give {STANDARDS[std]}"
        )
    return problems


def record_path() -> Path:
    """The referee measurement. ``standard.json`` stays the earlier record."""
    return ROOT / "data" / "fortran" / "standard-referee-r1.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check", action="store_true", help="check the record without a compiler"
    )
    args = parser.parse_args()
    if not args.check:
        parser.error("this series only checks the stored record")
    out = record_path()
    problems = check(json.loads(out.read_text(encoding="utf-8")))
    for problem in problems:
        print(f"{out.relative_to(ROOT)}: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
