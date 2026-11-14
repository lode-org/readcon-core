"""Short CON decimals match a round trip, including a tie."""

import sys
import tempfile
from pathlib import Path

import readcon


def main() -> None:
    atom = readcon.Atom(
        "Cu",
        1.5,
        0.25,
        2.0,
        fixed=[False, False, False],
        atom_id=1,
        mass=63.546,
    )
    frame = readcon.ConFrame((10.0, 10.0, 10.0), (90.0, 90.0, 90.0), [atom])
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "short.con"
        readcon.write_con(str(path), [frame])
        text = path.read_text(encoding="utf-8")
        for spelling in ("1.5", "0.25", "2.0"):
            if spelling not in text:
                raise SystemExit(f"missing short decimal {spelling}")
        back = readcon.read_con(str(path))
        got = back[0].atoms[0]
        if (got.x, got.y, got.z) != (1.5, 0.25, 2.0):
            raise SystemExit(f"round trip changed coordinates: {got.x} {got.y} {got.z}")


if __name__ == "__main__":
    main()
    sys.exit(0)
