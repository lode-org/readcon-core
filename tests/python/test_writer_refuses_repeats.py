"""Every benchmark writer refuses a second copy of one frame."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bench" / "h2h"))
sys.path.insert(0, str(ROOT / "bench" / "h2h" / "asv"))
sys.path.insert(0, str(ROOT / "benches"))
sys.path.insert(0, str(ROOT / "paper" / "cpc" / "bench"))

import bench_parallel_frames
import camp24_run
import cross_format
import db_v2
import frames_guard
import h5md_vs_con
import make_payloads
import run_h2h
import run_mpi_v2
import scale_r6


def _zeros(n_atoms: int, frame: int = 0, seed: int = 1):
    del frame, seed
    return np.zeros((n_atoms, 3))


def _identical(spec: dict) -> dict:
    spec = dict(spec)
    spec["positions"] = np.zeros((2, 1, 3))
    return spec


def test_each_writer_refuses_repeated_frames(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(frames_guard, "perturb_frame", lambda text, frame, seed=1: text)
    monkeypatch.setattr(frames_guard, "thermal_shift", _zeros)
    with pytest.raises(SystemExit, match="byte-identical"):
        frames_guard.distinct_frame_list("h\n1.0 2.0 3.0 0 0\n", 2)
    with pytest.raises(SystemExit, match="byte-identical"):
        frames_guard.write_distinct_copies(
            tmp_path / "copies.con", "h\n1.0 2.0 3.0 0 0\n", 2
        )
    with pytest.raises(SystemExit, match="byte-identical"):
        run_h2h.write_grid(tmp_path / "grid.con", 1, 2)
    with pytest.raises(SystemExit, match="byte-identical"):
        db_v2.write_con(tmp_path / "db.con")
    with pytest.raises(SystemExit, match="byte-identical"):
        run_mpi_v2.write_con(tmp_path / "mpi.con")
    with pytest.raises(SystemExit, match="byte-identical"):
        bench_parallel_frames.write_inputs(np.zeros((2, 1, 3)))
    with pytest.raises(SystemExit, match="byte-identical"):
        h5md_vs_con.thermal_positions(np.zeros((1, 3)), 2)
    with pytest.raises(SystemExit, match="byte-identical"):
        frames_guard.require_distinct_texts(["frame\n", "frame\n"])
    spec = _identical({})
    with pytest.raises(SystemExit, match="byte-identical"):
        cross_format.write_readcon(tmp_path / "rc.con", spec, None)
    with pytest.raises(SystemExit, match="byte-identical"):
        cross_format.write_xyz_for_readcon(tmp_path / "x.xyz", spec)
    with pytest.raises(SystemExit, match="byte-identical"):
        cross_format.write_chemfiles(tmp_path / "c.xyz", spec, "XYZ")
    with pytest.raises(SystemExit, match="byte-identical"):
        cross_format.write_ase(tmp_path / "a.traj", spec)
    with pytest.raises(SystemExit, match="byte-identical"):
        cross_format.write_ovito(tmp_path / "o.xyz", spec)
    with pytest.raises(SystemExit, match="byte-identical"):
        cross_format.write_mdtraj(tmp_path / "m.xyz", spec)
    with pytest.raises(SystemExit, match="byte-identical"):
        cross_format.write_built_mda(tmp_path / "d.xyz", spec, None)


def test_scale_r6_refuses_repeated_frames(tmp_path: Path, monkeypatch) -> None:
    def _same_frame(_frame: int, _base) -> str:
        return "same\n"

    monkeypatch.setattr(scale_r6, "_md_frame_text", _same_frame)
    with pytest.raises(SystemExit, match="byte-identical"):
        scale_r6.write_md_extxyz(tmp_path / "water.extxyz", n_frames=2)


def test_camp24_rewrites_a_cached_file_of_copies(tmp_path: Path) -> None:
    one = (ROOT / "resources" / "test" / "cuh2.con").read_text(encoding="utf-8")
    one = one if one.endswith("\n") else one + "\n"
    cached = tmp_path / "cached.con"
    cached.write_text("".join([one, one]), encoding="utf-8")
    camp24_run.repeat_fixture(cached, 2)
    frames = camp24_run._fixture_frames(cached.read_text(encoding="utf-8"), one)
    assert len(frames) == 2
    assert frames[0] != frames[1]


def test_camp24_refuses_repeated_frames(tmp_path: Path, monkeypatch) -> None:
    def _copies(text: str, n: int, seed: int = 1) -> list[str]:
        del seed
        return [text] * n

    monkeypatch.setattr(frames_guard, "distinct_frame_list", _copies)
    with pytest.raises(SystemExit, match="byte-identical"):
        camp24_run.repeat_fixture(tmp_path / "fresh.con", 2)
    assert not (tmp_path / "fresh.con").exists()


def test_payload_series_refuses_repeated_positions() -> None:
    with pytest.raises(SystemExit, match="repeat the positions"):
        make_payloads.distinct({"positions": np.zeros((2, 1, 3))}, "trajectory")


def test_a_cached_input_does_not_skip_the_guard(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(bench_parallel_frames, "WORK", tmp_path)
    for path in bench_parallel_frames.input_paths().values():
        path.write_text("cached\n", encoding="utf-8")
    (tmp_path / "stamp.json").write_text(
        '{"frames": %d, "atoms": %d}'
        % (bench_parallel_frames.N_FRAMES, bench_parallel_frames.N_ATOMS),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="byte-identical"):
        bench_parallel_frames.write_inputs(np.zeros((2, 1, 3)))
    assert (tmp_path / "stamp.json").exists()
