#!/usr/bin/env python3
"""Listing 1: the survey frame of Table 2 as the installed readcon writer emits it.

The frame is ``failure_matrix.fixture()`` and the writer is
``failure_matrix.w_readcon``, the route the survey grades. Writes

* ``src/figures/generated/survey_frame.con``, the file itself, which the
  listing prints byte for byte;
* ``src/figures/generated/survey_listing.tex``, the listing with its caption;
* ``data/survey_frame.json``, the readcon version, byte count, SHA-256 and
  provenance.

The script reads the file back and stops unless the identifiers, masks and
binary64 coordinates survive. ``--tables`` writes the listing from the
committed record and stops if the file no longer has its recorded SHA-256.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

import failure_matrix as fm

ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "src" / "figures" / "generated"
FRAME = GENERATED / "survey_frame.con"


RECORD = ROOT / "data" / "survey_frame.json"


def write_listing(record: dict) -> None:
    caption = (
        "A Pt(100) slab of two layers of four atoms with one adatom, as one CON 3.1 frame with velocities "
        f"written by readcon-core {record['readcon']}. Section~\\ref{{sec:worked}} reads it line by line."
    )
    (GENERATED / "survey_listing.tex").write_text(
        "% Written by paper/cpc/scripts/survey_listing.py.\n"
        f"\\lstinputlisting[numbers=left,numberstyle=\\tiny,caption={{{caption}}},label={{lst:frame}}]"
        "{figures/generated/survey_frame.con}\n"
    )


def measure() -> dict:
    import provenance
    import readcon

    fx = fm.fixture()
    fm.w_readcon(fx, FRAME)
    back = readcon.read_con(str(FRAME))[0]
    ids = [int(atom.atom_id) for atom in back.atoms]
    pos = np.array([[atom.x, atom.y, atom.z] for atom in back.atoms])
    fixed = np.array([list(atom.fixed) for atom in back.atoms])
    if (
        ids != [int(i) for i in fx["ids"]]
        or not (pos == fx["pos"]).all()
        or not (fixed == fx["mask"]).all()
    ):
        raise SystemExit("the survey frame does not read back to the fixture")
    data = FRAME.read_bytes()
    record = {
        "readcon": readcon.__version__,
        "bytes": len(data),
        "lines": data.count(b"\n"),
        "sha256": hashlib.sha256(data).hexdigest(),
        "ids": ids,
        "source": "scripts/failure_matrix.py fixture() written by w_readcon",
        "provenance": provenance.record(),
    }
    RECORD.write_text(json.dumps(record, indent=2) + "\n")
    return record


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--tables",
        action="store_true",
        help="write the listing from the committed record only",
    )
    args = parser.parse_args()
    if args.tables:
        record = json.loads(RECORD.read_text())
        if hashlib.sha256(FRAME.read_bytes()).hexdigest() != record["sha256"]:
            raise SystemExit(
                f"{FRAME.name} differs from the SHA-256 in {RECORD.name}; rerun survey_listing.py"
            )
    else:
        record = measure()
    write_listing(record)
    print(json.dumps({k: v for k, v in record.items() if k != "provenance"}))


if __name__ == "__main__":
    main()
