"""A fresh-file publish leaves no scratch name beside the path.

Ranked writes do this by default. One MPI_Allgather shares each rank's
byte length and frame count. Rank 0 renames the finished file onto the
path, then one gather writes the .rcidx sidecar. Spare reuse is not the
default.
"""

import sys
import tempfile
from pathlib import Path

import readcon


def main() -> None:
    atom = readcon.Atom(
        "Cu",
        1.25,
        0.0,
        0.0,
        fixed=[True, False, False],
        atom_id=7,
        mass=63.546,
    )
    frame = readcon.ConFrame((8.0, 8.0, 8.0), (90.0, 90.0, 90.0), [atom])
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        path = directory / "ranked.con"
        readcon.write_con(str(path), [frame])
        scratches = [
            item.name
            for item in directory.iterdir()
            if item.name.startswith(".readcon-write-")
        ]
        if scratches:
            raise SystemExit(f"publish left a scratch name: {scratches}")
        back = readcon.read_first_frame(str(path))
        got = back.atoms[0]
        if got.symbol != "Cu" or got.atom_id != 7 or got.x != 1.25:
            raise SystemExit("fresh file dropped a field the text round trip keeps")
        if list(got.fixed) != [True, False, False]:
            raise SystemExit(f"fixed flags were not kept: {got.fixed}")


if __name__ == "__main__":
    main()
    sys.exit(0)
