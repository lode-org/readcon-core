#!/usr/bin/env python3
"""Build a four-image campaign-shaped CON from resources/test/cuh2.con.

Each frame keeps the 218-atom geometry. Line 2 is rewritten with declared
neb_bead / energy / fmax tags. Those energies are fixture labels, not a
measured CuH2 NEB.

Usage:
    python scripts/make_cuh2_band.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "resources" / "test" / "cuh2.con"
DEST = ROOT / "resources" / "examples" / "cuh2_band.con"

# Declared campaign tags (same numbers as neb_band.con).
BEADS = (
    (0, "reactant", -1.20, 0.31),
    (1, "saddle", -0.40, 0.08),
    (2, "descending", -0.65, 0.12),
    (3, "product", -1.10, 0.27),
)


def main() -> int:
    text = SRC.read_text()
    lines = text.splitlines(keepends=True)
    if len(lines) < 2:
        raise SystemExit(f"short fixture: {SRC}")
    out: list[str] = []
    for bead, role, energy, fmax in BEADS:
        meta = {
            "con_spec_version": 3,
            "units": {"length": "angstrom", "energy": "eV"},
            "neb_bead": bead,
            "neb_band": 0,
            "energy": energy,
            "fmax": fmax,
        }
        frame = list(lines)
        frame[0] = f"cuh2 band image {bead} ({role})\n"
        frame[1] = json.dumps(meta, separators=(",", ":")) + "\n"
        out.extend(frame)
        if not frame[-1].endswith("\n"):
            out.append("\n")
    DEST.write_text("".join(out))
    print(f"wrote {DEST} ({DEST.stat().st_size} bytes, {len(BEADS)} frames)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
