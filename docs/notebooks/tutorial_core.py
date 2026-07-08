from __future__ import annotations

import os
import sys
from pathlib import Path

# Repo root: CI and local runs cwd to repository root.
REPO = Path(os.environ.get("READCON_TUT_ROOT", Path.cwd())).resolve()
FIXTURES = REPO / "resources" / "test"
MULTI = FIXTURES / "tiny_multi_cuh2.con"
FORCES = FIXTURES / "tiny_cuh2_forces.con"
work_dir = Path(os.environ.get("READCON_TUT_WORK", REPO / "docs" / "notebooks" / "out" / "tutorial_core"))
work_dir.mkdir(parents=True, exist_ok=True)
roundtrip_path = work_dir / "tutorial_roundtrip.con"
built_path = work_dir / "tutorial_built.con"
print("REPO =", REPO)
print("work_dir =", work_dir.resolve())

import readcon

print("readcon", getattr(readcon, "__version__", "?"))
print("CON_SPEC_VERSION", readcon.CON_SPEC_VERSION)
assert MULTI.is_file(), f"missing fixture {MULTI}"
assert FORCES.is_file(), f"missing fixture {FORCES}"

n = 0
for frame in readcon.iter_con(str(MULTI)):
    n += 1
    print(n, list(frame.cell), len(frame))

print("frames:", n)
assert n == 2, n

frame = readcon.read_first_frame(str(MULTI))
print("spec_version:", frame.spec_version)
# energy is a property (None when JSON omits it), not a method
print("energy:", frame.energy)
for atom in list(frame.atoms)[:2]:
    print(
        atom.symbol,
        round(atom.x, 4),
        round(atom.y, 4),
        round(atom.z, 4),
        "fixed=",
        atom.is_fixed,
        "atom_id=",
        atom.atom_id,
    )
assert frame.spec_version >= 2
assert frame.energy is None
assert list(frame.atoms)[0].symbol == "Cu"
assert list(frame.atoms)[0].atom_id == 0
assert list(frame.atoms)[0].is_fixed is True

frames = readcon.read_con(str(MULTI))
readcon.write_con(str(roundtrip_path), frames)
again = list(readcon.iter_con(str(roundtrip_path)))
print("wrote", len(frames), "frames; reread", len(again))
assert len(again) == len(frames) == 2
assert len(again[0]) == 4

ref = readcon.read_first_frame(str(FORCES))
print("has_forces:", ref.has_forces, "energy:", ref.energy)
assert ref.has_forces is True
assert ref.energy == -42.5

atoms = [
    readcon.Atom("Cu", 0.0, 0.0, 0.0, atom_id=0, mass=63.546),
    readcon.Atom("H", 1.5, 0.0, 0.0, atom_id=1, mass=1.008),
]
frame = readcon.ConFrame(
    cell=[10.0, 10.0, 10.0],
    angles=[90.0, 90.0, 90.0],
    atoms=atoms,
)
frame.set_energy(-1.25)
frame.write_con(str(built_path))

check = readcon.read_first_frame(str(built_path))
print("built atoms:", len(check), "energy:", check.energy)
assert len(check) == 2
assert check.energy == -1.25

import json

summary = {
    "multi_frames": 2,
    "roundtrip": str(roundtrip_path.resolve()),
    "built": str(built_path.resolve()),
    "built_energy": check.energy,
    "has_forces_fixture": bool(ref.has_forces),
}
(work_dir / "summary.json").write_text(
    json.dumps(summary, indent=2) + "\n", encoding="utf-8"
)
print(json.dumps(summary, indent=2))
print("OK — org-mode CON checkpoint tutorial finished", file=sys.stderr)
