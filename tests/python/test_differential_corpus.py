"""Differential parsing checks against ASE and the C reference reader.

Every test reads a file of ``resources/test`` with ``readcon.read_con(path)``,
the path reader. The byte reader on a caller's buffer is not exercised here.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

try:
    from ase.io import read as ase_read
except ImportError:  # pragma: no cover - exercised only when deps are missing
    if os.environ.get("CI"):
        pytest.fail("ASE is required for differential corpus tests in CI")
    pytest.skip(
        "ASE is required for differential corpus tests", allow_module_level=True
    )

import readcon

REPO_ROOT = Path(__file__).resolve().parents[2]
RESOURCES = REPO_ROOT / "resources" / "test"
EON_C_READER = REPO_ROOT / "addl" / "referenceImpls" / "eon_cpp" / "bench_con_reader.c"
CORPUS = [
    "cuh2.con",
    "sulfolene.con",
    "tiny_cuh2.con",
    "tiny_multi_cuh2.con",
]
# The C reader prints column 4 as written, which spec 2 and later read as
# the bitmask of the fixed axes (CON-mask.4).
FIRST_BITMASK_SPEC = 2


def _flag_bits(fixed) -> int:
    return sum(1 << axis for axis, held in enumerate(fixed) if held)


def _as_ase_list(path: Path):
    parsed = ase_read(path, index=":", format="eon")
    return parsed if isinstance(parsed, list) else [parsed]


def _as_readcon_rows(frames):
    return [
        [
            {
                "symbol": atom.symbol,
                "xyz": np.array([atom.x, atom.y, atom.z], dtype=float),
                "flag": _flag_bits(atom.fixed),
                "atom_id": int(atom.atom_id),
            }
            for atom in frame.atoms
        ]
        for frame in frames
    ]


def _parse_eon_dump(stdout: str):
    frames = []
    current = None
    for raw in stdout.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        if parts[0] == "FRAME":
            if current is not None:
                frames.append(current)
            current = {"index": int(parts[1]), "atoms": []}
            continue
        if parts[0] != "ATOM" or current is None:
            continue
        current["atoms"].append(
            {
                "frame": int(parts[1]),
                "atom": int(parts[2]),
                "symbol": parts[3],
                "xyz": np.array(
                    [float(parts[4]), float(parts[5]), float(parts[6])], dtype=float
                ),
                "flag": int(parts[7]),
                "atom_id": int(parts[8]),
            }
        )
    if current is not None:
        frames.append(current)
    return frames


@pytest.fixture(scope="session")
def eon_dump_binary(tmp_path_factory):
    cc = shutil.which("cc")
    if cc is None:
        if os.environ.get("CI"):
            pytest.fail("cc is required for differential corpus tests in CI")
        pytest.skip("cc is unavailable on this host")
    out = tmp_path_factory.mktemp("eon-reader") / "bench_con_reader"
    subprocess.run([cc, "-O2", "-o", str(out), str(EON_C_READER), "-lm"], check=True)
    return out


@pytest.mark.parametrize("name", CORPUS)
def test_readcon_matches_ase_on_real_corpus(name):
    path = RESOURCES / name
    readcon_rows = _as_readcon_rows(readcon.read_con(str(path)))
    ase_frames = _as_ase_list(path)
    assert len(readcon_rows) == len(ase_frames), name
    for row_atoms, ase_atoms in zip(readcon_rows, ase_frames):
        assert len(row_atoms) == len(ase_atoms), name
        assert [
            atom["symbol"] for atom in row_atoms
        ] == ase_atoms.get_chemical_symbols()
        expected = ase_atoms.get_positions()
        np.testing.assert_array_equal(
            np.array([atom["xyz"] for atom in row_atoms], dtype=float),
            expected,
        )


@pytest.mark.parametrize("name", CORPUS)
def test_readcon_matches_eon_reader_on_real_corpus(name, eon_dump_binary):
    path = RESOURCES / name
    frames = readcon.read_con(str(path))
    assert all(frame.spec_version >= FIRST_BITMASK_SPEC for frame in frames), name
    readcon_rows = _as_readcon_rows(frames)
    proc = subprocess.run(
        [str(eon_dump_binary), "--dump", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    eon_rows = _parse_eon_dump(proc.stdout)
    assert len(readcon_rows) == len(eon_rows), name
    for frame_idx, (ours, eon) in enumerate(zip(readcon_rows, eon_rows)):
        assert eon["index"] == frame_idx
        assert len(ours) == len(eon["atoms"]), name
        for atom_idx, (our_atom, eon_atom) in enumerate(zip(ours, eon["atoms"])):
            assert eon_atom["frame"] == frame_idx
            assert eon_atom["atom"] == atom_idx
            assert our_atom["symbol"] == eon_atom["symbol"]
            np.testing.assert_array_equal(our_atom["xyz"], eon_atom["xyz"])
            assert our_atom["flag"] == eon_atom["flag"]
            assert our_atom["atom_id"] == eon_atom["atom_id"]
