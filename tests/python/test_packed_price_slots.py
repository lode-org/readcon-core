"""A list whose frames were taken out does not leave a price behind.

Indexing a `read_con` result moves each frame out of its slot without a
drop at that address. A later list allocated at the same address with the
same coordinates and a longer header must still write its own bytes.
"""

from __future__ import annotations

import random
from pathlib import Path


def _text(n_frames: int, n_atoms: int, species: tuple[str, ...]) -> str:
    rng = random.Random(1234)
    coords = [
        [tuple(rng.uniform(0, 29) for _ in range(3)) for _ in range(n_atoms)]
        for _ in range(n_frames)
    ]
    counts = [n_atoms] if len(species) == 1 else [n_atoms - n_atoms // 3, n_atoms // 3]
    masses = {"Cu": "63.546", "H": "1.008"}
    parts = []
    for frame in coords:
        parts.append(
            "\n"
            '{"con_spec_version":3,"con_spec_minor":1,'
            '"units":{"length":"angstrom","energy":"eV"}}\n'
            "30 30 30\n90 90 90\n\n\n"
            f"{len(species)}\n{' '.join(map(str, counts))}\n"
            f"{' '.join(masses[s] for s in species)}\n"
        )
        at = 0
        for t, (sym, count) in enumerate(zip(species, counts)):
            parts.append(f"{sym}\nCoordinates of Component {t + 1}\n")
            for i in range(at, at + count):
                x, y, z = frame[i]
                parts.append(f"{x!r} {y!r} {z!r} 0 {i}\n")
            at += count
    return "".join(parts)


def test_a_reused_slot_address_writes_its_own_frames(tmp_path: Path) -> None:
    import readcon

    one = tmp_path / "one.con"
    two = tmp_path / "two.con"
    one.write_text(_text(2, 5000, ("Cu",)), encoding="utf-8")
    two.write_text(_text(2, 5000, ("Cu", "H")), encoding="utf-8")
    want = readcon.write_con_string(list(readcon.read_con_string(two.read_text()))).encode()
    for _ in range(5):
        frames = readcon.read_con(str(one), n_threads=1)
        readcon.write_con(str(tmp_path / "a.con"), frames, n_threads=1)
        held = frames[:]
        del held, frames
        frames = readcon.read_con(str(two), n_threads=1)
        out = tmp_path / "b.con"
        readcon.write_con(str(out), frames, n_threads=1)
        assert out.read_bytes() == want
        del frames
