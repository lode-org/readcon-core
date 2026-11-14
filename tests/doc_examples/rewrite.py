"""Rewrite replaces the path only after the spare is a complete file."""

import sys
import tempfile
from pathlib import Path

import readcon


def frame_at(x: float) -> readcon.ConFrame:
    atom = readcon.Atom(
        "Cu",
        x,
        0.0,
        0.0,
        fixed=[False, False, False],
        atom_id=1,
        mass=63.546,
    )
    return readcon.ConFrame((10.0, 10.0, 10.0), (90.0, 90.0, 90.0), [atom])


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "traj.con"
        spare = Path(str(path) + ".rewrite")
        readcon.write_con(str(path), [frame_at(1.0)])
        readcon.write_con(str(path), [frame_at(3.5)], rewrite=True, keep_spare=False)
        if spare.exists():
            raise SystemExit("keep_spare=False left the spare")
        text = path.read_text(encoding="utf-8")
        if "3.5" not in text or "1.0" in text.split("Coordinates")[-1]:
            raise SystemExit("published file is not the finished rewrite")
        readcon.write_con(str(path), [frame_at(4.0)], rewrite=True, keep_spare=True)
        if not spare.exists():
            raise SystemExit("keep_spare=True did not park the previous inode")


if __name__ == "__main__":
    main()
    sys.exit(0)
