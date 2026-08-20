#!/usr/bin/env python3
"""Print energy versus NEB bead for resources/examples/neb_band.con.

Usage (after ``pip install readcon`` or a maturin develop of this tree):

    python scripts/print_neb_band.py
    python scripts/print_neb_band.py path/to/band.con
"""

from __future__ import annotations

import sys
from pathlib import Path

import readcon


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "resources" / "examples" / "neb_band.con"
    frames = readcon.read_con(str(path))
    print(f"# {path}  n_frames={len(frames)}")
    print("bead\tenergy_eV\tfmax")
    for frame in frames:
        bead = frame.neb_bead if hasattr(frame, "neb_bead") else frame.metadata.get("neb_bead")
        energy = frame.energy if hasattr(frame, "energy") else frame.metadata.get("energy")
        fmax = frame.metadata.get("fmax")
        print(f"{bead}\t{energy}\t{fmax}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
