"""Column slabs match a full-frame read."""

from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "resources" / "test"


def _compare(path: Path, threads: int) -> None:
    import readcon

    frames = readcon.read_con(str(path), n_threads=1)
    full = frames.columns()
    got = readcon.read_column_slabs(str(path), n_threads=threads)
    assert got["n_frames"] == len(frames)
    assert np.array_equal(np.asarray(got["positions"]), np.asarray(full["positions"]))
    assert np.array_equal(np.asarray(got["masses"]), np.asarray(full["masses"]))
    assert np.array_equal(np.asarray(got["fixed"]), np.asarray(full["fixed"]))
    assert np.array_equal(np.asarray(got["cell"]), np.asarray(full["cell"]))
    assert np.array_equal(np.asarray(got["atom_ids"]), np.asarray(full["atom_ids"]))
    assert np.array_equal(
        np.asarray(got["atomic_numbers"]), np.asarray(full["atomic_numbers"])
    )
    assert isinstance(got["symbols"], list)
    assert got["symbols"] and isinstance(got["symbols"][0], list)
    for key in ("velocities", "forces"):
        if full[key] is None:
            assert got[key] is None
        else:
            assert np.array_equal(np.asarray(got[key]), np.asarray(full[key]))
    for index, frame in enumerate(frames):
        assert np.array_equal(
            np.asarray(got["positions"][index]), np.asarray(frame.xyz)
        )
        assert [atom.symbol for atom in frame.atoms] == list(got["symbols"][index])
        if frame.vel is not None:
            assert np.array_equal(
                np.asarray(got["velocities"][index]), np.asarray(frame.vel)
            )


def test_column_slabs_match_full_frames() -> None:
    names = [
        "tiny_cuh2.con",
        "tiny_multi_cuh2.con",
        "tiny_cuh2.convel",
        "tiny_multi_cuh2.convel",
        "tiny_cuh2_forces.con",
    ]
    for name in names:
        for threads in (1, 4):
            _compare(CORPUS / name, threads)


def test_present_sections_match_the_frame(tmp_path: Path) -> None:
    import readcon

    names = [
        "tiny_cuh2_charges_spins_magmoms.con",
        "tiny_cuh2_displacements.con",
        "tiny_cuh2_spreads.con",
    ]
    for name in names:
        path = CORPUS / name
        frames = readcon.read_con(str(path))
        got = readcon.read_column_slabs(str(path))
        for index, frame in enumerate(frames):
            atoms = list(frame.atoms)
            if frame.disp is not None:
                assert np.array_equal(
                    np.asarray(got["displacements"][index]), np.asarray(frame.disp)
                )
            if frame.spread is not None:
                assert np.array_equal(
                    np.asarray(got["spreads"][index]), np.asarray(frame.spread)
                )
            charges = [atom.charge for atom in atoms]
            if any(value is not None for value in charges):
                assert np.allclose(
                    np.asarray(got["charges"][index], dtype=float),
                    np.asarray(charges, dtype=float),
                )
            spins = [atom.spin for atom in atoms]
            if any(value is not None for value in spins):
                assert np.allclose(
                    np.asarray(got["spins"][index], dtype=float),
                    np.asarray(spins, dtype=float),
                )
            mag = [(atom.mx, atom.my, atom.mz) for atom in atoms]
            if any(item[0] is not None for item in mag):
                assert np.allclose(
                    np.asarray(got["magmoms"][index], dtype=float),
                    np.asarray(mag, dtype=float),
                )
    energy = (
        "seed\n"
        '{"con_spec_version":2,"sections":["energies"]}\n'
        "1.0 1.0 1.0\n"
        "90 90 90\n"
        "0 0\n"
        "0 0 0\n"
        "1\n"
        "1\n"
        "1.0\n"
        "H\n"
        "Coordinates of Component 1\n"
        "0.1 -0.2 0.3 0 0\n"
        "\n"
        "H\n"
        "Energies of Component 1\n"
        "0.25 0 0\n"
    )
    path = tmp_path / "energy.con"
    path.write_text(energy, encoding="utf-8")
    frames = readcon.read_con(str(path))
    got = readcon.read_column_slabs(str(path))
    assert frames[0].atoms[0].energy == pytest.approx(float(got["energies"][0, 0]))


def test_float32_masses_match_the_stored_value(tmp_path: Path) -> None:
    import readcon

    text = (
        "seed\n"
        '{"con_spec_version":3,"units":{"length":"angstrom","energy":"eV"},'
        '"storage_dtypes":{"masses":"float32"}}\n'
        "1.0 1.0 1.0\n"
        "90 90 90\n"
        "0 0\n"
        "0 0 0\n"
        "1\n"
        "1\n"
        "0.1\n"
        "H\n"
        "Coordinates of Component 1\n"
        "0.0 0.0 0.0 0 0\n"
    )
    path = tmp_path / "mass.con"
    path.write_text(text, encoding="utf-8")
    got = readcon.read_column_slabs(str(path))
    stored = np.float64(np.float32(0.1))
    assert got["masses"][0, 0] == stored
    assert got["masses"][0, 0] != 0.1


def test_an_empty_file_names_the_path(tmp_path: Path) -> None:
    import readcon

    path = tmp_path / "empty.con"
    path.write_bytes(b"")
    with pytest.raises(ValueError, match="no frames"):
        readcon.read_column_slabs(str(path))


def test_repeated_frames_match_full_frames(tmp_path: Path) -> None:
    text = (CORPUS / "tiny_cuh2.con").read_text(encoding="utf-8")
    path = tmp_path / "four.con"
    path.write_text(text * 4, encoding="utf-8")
    _compare(path, 1)
    _compare(path, 4)
