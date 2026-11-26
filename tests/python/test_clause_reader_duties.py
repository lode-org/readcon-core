"""Reader-duty coverage probes and conformance tests around IDs and flat cells."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

try:
    import readcon
except ModuleNotFoundError as exc:  # pragma: no cover - exercised in CI setup checks
    if os.environ.get("CI") == "true":
        raise AssertionError(
            "readcon must be importable in CI for reader-duty checks"
        ) from exc
    pytest.skip(
        "readcon module is unavailable in this environment", allow_module_level=True
    )


def _con_text(
    *,
    ids: tuple[int, int] = (7, 42),
    box: str = "10 11 12",
    angles: str = "90 90 90",
    validate: bool = False,
    bonds=None,
) -> str:
    metadata: dict[str, object] = {"con_spec_version": 2}
    if validate:
        metadata["validate"] = True
        metadata["sections"] = []
    if bonds is not None:
        metadata["bonds"] = bonds
    header = (
        "seed\n"
        + json.dumps(metadata, separators=(",", ":"))
        + "\n"
        + f"{box}\n"
        + f"{angles}\n"
        + "0 0\n"
        + "0 0 0\n"
        + "1\n"
        + "2\n"
        + "1.0\n"
        + "H\n"
        + "Coordinates of Component 1\n"
    )
    rows = f"0 0 0 0 {ids[0]}\n1 1 1 0 {ids[1]}\n"
    return header + rows


def test_con_id_2_accepts_ids_not_starting_at_zero_or_one() -> None:
    frames = readcon.read_con_string(_con_text(ids=(17, 23)))
    assert [atom.atom_id for atom in frames[0].atoms] == [17, 23]


def test_con_id_7_returns_atoms_in_file_order_with_ids() -> None:
    frames = readcon.read_con_string(_con_text(ids=(99, 3)))
    assert [atom.atom_id for atom in frames[0].atoms] == [99, 3]
    assert [(atom.x, atom.y, atom.z) for atom in frames[0].atoms] == [
        (0.0, 0.0, 0.0),
        (1.0, 1.0, 1.0),
    ]


def test_con_validate_2_validate_true_does_not_relax_base_rejections() -> None:
    broken = _con_text().replace("1 1 1 0 42", "1 1 nope 0 42")
    with pytest.raises(Exception) as base:
        readcon.read_con_string(broken)
    with pytest.raises(type(base.value)) as validated:
        readcon.read_con_string(
            broken.replace(
                '"con_spec_version":2',
                '"con_spec_version":2,"validate":true,"sections":[]',
            )
        )
    assert str(validated.value) == str(base.value)


def test_con_bonds_2_rejects_malformed_bonds_when_validate_true() -> None:
    with pytest.raises(Exception):
        readcon.read_con_string(_con_text(validate=True, bonds=[[0], [1, 2, 3, 4]]))


def test_con_compress_5_one_frame_zstd_without_index_is_readable(
    tmp_path: Path,
) -> None:
    frame = readcon.read_con_string(_con_text())[0]
    out = tmp_path / "single.con.zst"
    try:
        readcon.write_con(str(out), [frame], compression="zstd", n_threads=1)
    except Exception as exc:  # pragma: no cover - zstd feature may be disabled
        if "zstd" in str(exc).lower():
            pytest.skip("zstd feature is unavailable in this build")
        raise
    back = readcon.read_con(str(out), n_threads=1)
    assert len(back) == 1 and len(back[0].atoms) == 2


def test_con_token_1_rejects_non_digit_integer_tokens() -> None:
    bad = _con_text().replace("\n2\n1.0\n", "\n+2\n1.0\n", 1)
    with pytest.raises(Exception):
        readcon.read_con_string(bad)


def _frame(atom_ids: tuple[int, int], z_shift: float = 0.0) -> readcon.ConFrame:
    return readcon.ConFrame(
        (10.0, 10.0, 10.0),
        (90.0, 90.0, 90.0),
        [
            readcon.Atom("Cu", 0.0, 0.0, z_shift, atom_id=atom_ids[0], mass=63.546),
            readcon.Atom(
                "Cu", 1.0, 1.0, 1.0 + z_shift, atom_id=atom_ids[1], mass=63.546
            ),
        ],
    )


def test_id_uniqueness_within_frame_is_enforced() -> None:
    frame = _frame((4, 4))
    with pytest.raises(Exception):
        readcon.write_con_string([frame])


def test_id_persistence_across_frames_is_implementation_defined_and_stable(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ids.con"
    readcon.write_con(str(path), [_frame((11, 12), 0.0), _frame((11, 12), 0.25)])
    back = readcon.read_con(str(path))
    assert [atom.atom_id for atom in back[0].atoms] == [11, 12]
    assert [atom.atom_id for atom in back[1].atoms] == [11, 12]


def test_flat_cell_acceptance_is_implementation_defined_and_deterministic() -> None:
    frame = readcon.ConFrame(
        (10.0, 10.0, 1e-9),
        (90.0, 90.0, 90.0),
        [readcon.Atom("H", 0.0, 0.0, 0.0, atom_id=0, mass=1.0)],
    )
    text = readcon.write_con_string([frame])
    first = readcon.read_con_string(text)[0].cell
    second = readcon.read_con_string(text)[0].cell
    assert first == second
    assert abs(first[2] - 1e-9) <= 1e-12
