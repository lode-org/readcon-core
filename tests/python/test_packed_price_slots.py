"""A list whose frames were taken out does not leave a price behind.

Indexing a `read_con` result moves each frame out of its slot without a
drop at that address. A later list allocated at the same address with the
same coordinates and a longer header must still write its own bytes.
"""

from __future__ import annotations

import gzip
import random
import subprocess
from pathlib import Path

import pytest


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


@pytest.mark.parametrize("n_threads", [1, 2, 8])
def test_a_reused_slot_address_writes_its_own_frames(
    tmp_path: Path, n_threads: int
) -> None:
    import readcon

    one = tmp_path / "one.con"
    two = tmp_path / "two.con"
    one.write_text(_text(2, 5000, ("Cu",)), encoding="utf-8")
    two.write_text(_text(2, 5000, ("Cu", "H")), encoding="utf-8")
    want = readcon.write_con_string(
        list(readcon.read_con_string(two.read_text()))
    ).encode()
    for _ in range(5):
        frames = readcon.read_con(str(one), n_threads=n_threads)
        readcon.write_con(str(tmp_path / "a.con"), frames, n_threads=n_threads)
        held = frames[:]
        del held, frames
        frames = readcon.read_con(str(two), n_threads=n_threads)
        out = tmp_path / "b.con"
        readcon.write_con(str(out), frames, n_threads=n_threads)
        assert out.read_bytes() == want

        out_gz = tmp_path / "b.con.gz"
        readcon.write_con(str(out_gz), frames, n_threads=n_threads)
        assert gzip.decompress(out_gz.read_bytes()) == want

        out_zst = tmp_path / "b.con.zst"
        try:
            readcon.write_con(str(out_zst), frames, n_threads=n_threads)
        except ValueError as exc:
            if "zstd feature" not in str(exc):
                raise
        else:
            raw = subprocess.check_output(["zstd", "-dc", str(out_zst)])
            assert raw == want

        del frames


@pytest.mark.parametrize("n_threads", [1, 2, 8])
def test_mutated_read_con_list_matches_serial_plain_and_compressed(
    tmp_path: Path, n_threads: int
) -> None:
    import readcon

    src = tmp_path / "src.con"
    src.write_text(_text(12, 16, ("Cu", "H")), encoding="utf-8")
    frames = readcon.read_con(str(src), n_threads=n_threads)

    plain_a = tmp_path / "a.con"
    readcon.write_con(str(plain_a), frames, n_threads=n_threads)
    held = frames[:]
    held[0].xyz[0, 0] = 1.2345678901234567e22
    held[1].xyz[0, 1] = 1.0
    held[2].metadata = {**held[2].metadata, "note": "longer metadata entry"}

    want = readcon.write_con_string(held).encode()

    plain_b = tmp_path / "b.con"
    readcon.write_con(str(plain_b), held, n_threads=n_threads)
    assert plain_b.read_bytes() == want

    gz_b = tmp_path / "b.con.gz"
    readcon.write_con(str(gz_b), held, n_threads=n_threads)
    assert gzip.decompress(gz_b.read_bytes()) == want

    zst_b = tmp_path / "b.con.zst"
    try:
        readcon.write_con(str(zst_b), held, n_threads=n_threads)
    except ValueError as exc:
        if "zstd feature" not in str(exc):
            raise
    else:
        assert subprocess.check_output(["zstd", "-dc", str(zst_b)]) == want
