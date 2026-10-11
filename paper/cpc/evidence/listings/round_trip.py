#!/usr/bin/env python3
"""Read and write one CON frame with the Python API on main.

The default writer is the round-trip printer. precision=6 is the
fixed-decimal writer. Neither call depends on the unpushed ASE branch
or on readcon-core issue 51.
"""

import sys

import readcon


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else "v31_slab.con"
    frames = readcon.read_con(path)
    frame = frames[0]
    print("frames", len(frames))
    print("atoms", len(frame.atoms))
    print("spec", frame.metadata.get("con_spec_version"), frame.metadata.get("con_spec_minor"))
    print("time", frame.metadata.get("units", {}).get("time"))
    atom = frame.atoms[-1]
    print("adsorbate", atom.symbol, atom.atom_id, atom.fixed, atom.vx, atom.vy, atom.vz)
    readcon.write_con("round_trip.con", frames)
    readcon.write_con("fixed6.con", frames, precision=6)
    again = readcon.read_con("round_trip.con")
    same = all(
        (a.x, a.y, a.z) == (b.x, b.y, b.z)
        for a, b in zip(frame.atoms, again[0].atoms)
    )
    print("round_trip_positions", same)


if __name__ == "__main__":
    main()
