"""Unit tests for the same-format harness rows."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import samefmt

ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_SHA = "68dfb7c307e0923044d4a9f41159b7a2ed2dd605"


@pytest.fixture(autouse=True)
def _reset_caches():
    saved = (samefmt._GEOM, samefmt._MF, samefmt._ALLOY, samefmt._CC, dict(samefmt._CACHE))
    samefmt._GEOM = None
    samefmt._MF = None
    samefmt._ALLOY = None
    samefmt._CC = None
    samefmt._CACHE = {}
    yield
    samefmt._GEOM, samefmt._MF, samefmt._ALLOY, samefmt._CC, samefmt._CACHE = saved


def _asv():
    path = Path(__file__).resolve().parent / "asv" / "bench_samefmt.py"
    spec = importlib.util.spec_from_file_location("bench_samefmt_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _row(arm: str) -> dict:
    tool, fmt, op, _multi, variant = samefmt.split_arm(arm)
    return {
        "arm": arm,
        "variant": variant,
        "tool": tool,
        "format": fmt,
        "operation": op,
        "n_atoms": 4,
        "n_frames": 1,
        "n": 1,
        "median_s": 0.1,
        "iqr_s": 0.0,
        "q25_s": 0.1,
        "q75_s": 0.1,
        "correct": True,
        "reordered": False,
        "id_map_ok": True,
        "fields": {"positions": "ok"},
        "convel_fidelity": "",
        "readcon_sha": "",
        "reason": "ok",
    }


def test_extxyz_without_properties_is_unsupported(tmp_path, monkeypatch):
    monkeypatch.setattr(samefmt, "N_ATOMS", 4)
    dest = tmp_path / "out.xyz"
    dest.write_text("2\nplain xyz\nCu 0 0 0\nCu 1 0 0\n", encoding="utf-8")
    row = samefmt._check("eon-cpp-extxyz-write", dest)
    assert str(row["reason"]).startswith("unsupported:")
    assert "Properties" in row["reason"]
    assert row["correct"] is None


def test_rejected_extxyz_is_still_a_row(tmp_path, monkeypatch):
    monkeypatch.setattr(samefmt, "N_ATOMS", 4)
    dest = tmp_path / "out.xyz"
    dest.write_text(
        '1\nLattice="1 0 0 0 1 0 0 0 1" Properties=species:S:1:pos:R:3\nCu 0 0 0\n',
        encoding="utf-8",
    )

    def fail(_fmt, _path):
        raise ValueError("not a frame")

    monkeypatch.setattr(samefmt, "read_file_with_readcon", fail)
    row = samefmt._check("eon-cpp-extxyz-write", dest)
    assert str(row["reason"]).startswith("unsupported:")
    assert "not a frame" in row["reason"]
    assert row["correct"] is None


def test_properties_header_is_judged(tmp_path, monkeypatch):
    monkeypatch.setattr(samefmt, "N_ATOMS", 4)
    geom = samefmt.geometry()
    dest = tmp_path / "out.xyz"
    dest.write_text(
        '1\nLattice="1 0 0 0 1 0 0 0 1" Properties=species:S:1:pos:R:3\nCu 0 0 0\n',
        encoding="utf-8",
    )
    packed = samefmt._pack(
        geom["positions"],
        geom["cell"],
        geom["masses"],
        geom["ids"],
        geom["fixed"],
        geom["velocities"],
    )
    monkeypatch.setattr(samefmt, "read_file_with_readcon", lambda _fmt, _path: packed)
    row = samefmt._check("eon-cpp-extxyz-write", dest)
    assert not str(row["reason"]).startswith("unsupported:")
    assert row["correct"] is True
    assert row["fields"]["positions"] == "ok"


def test_convel_dump_stays_a_mismatch_and_is_known_lossy(monkeypatch):
    monkeypatch.setattr(samefmt, "N_ATOMS", 4)
    geom = samefmt.geometry()
    got = samefmt._pack(
        geom["positions"],
        geom["cell"],
        geom["masses"],
        geom["ids"],
        geom["fixed"],
        geom["velocities"].copy(),
    )
    flags = geom["fixed"]
    for axis, bit in ((0, 1), (1, 2), (2, 4)):
        got["velocities"][flags & bit != 0, axis] = 0.0
    monkeypatch.setattr(samefmt, "_load_eon_dump", lambda _path: got)
    row = samefmt._check("eon-cpp-convel-read", Path("dump"))
    assert row["convel_fidelity"] == "known-lossy"
    assert row["correct"] is False
    assert row["fields"]["velocities"] != "ok"
    assert "known-lossy" in row["reason"]


def test_stock_eon_patch_is_not_part_of_the_harness():
    bench = Path(__file__).resolve().parent
    assert not (bench / "eon-convel-velocity.patch").exists()
    text = (bench / "samefmt.py").read_text(encoding="utf-8")
    assert "stock eOn" in text
    cpp = (bench / "eon_samefmt.cpp").read_text(encoding="utf-8")
    assert "known-lossy" in cpp
    assert "getVelocities()" in cpp


def test_eigen_flags_come_from_pkg_config(monkeypatch):
    def fake_run(cmd, **_kwargs):
        assert cmd[:3] == ["pkg-config", "--cflags", "eigen3"]

        class Result:
            returncode = 0
            stdout = "-I/from-pkg-config\n"
            stderr = ""

        return Result()

    monkeypatch.setattr(samefmt.subprocess, "run", fake_run)
    assert samefmt._eigen_cflags() == ["-I/from-pkg-config"]


def test_missing_eigen_names_pkg_config(monkeypatch):
    def fake_run(_cmd, **_kwargs):
        class Result:
            returncode = 1
            stdout = ""
            stderr = "Package eigen3 was not found"

        return Result()

    monkeypatch.setattr(samefmt.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="pkg-config eigen3"):
        samefmt._eigen_cflags()


def test_link_line_has_no_hardcoded_eigen_include(monkeypatch):
    monkeypatch.setattr(samefmt, "_eigen_cflags", lambda: ["-I/from-pkg-config"])
    command = samefmt._eon_link_command(Path("eon_samefmt"), Path("libeonclib.so"))
    assert "-I/from-pkg-config" in command
    assert "-I/usr/include/eigen3" not in command
    assert not any("/usr/include/eigen3" in token for token in command)


def test_csv_key_keeps_alloy_and_copper(tmp_path, monkeypatch):
    monkeypatch.setenv("READCON_SHA", "abc123")
    rows = [_row("readcon-extxyz-read"), _row("alloy-readcon-extxyz-read")]
    dest = tmp_path / "table.csv"
    samefmt._write_csv(rows, dest)
    text = dest.read_text(encoding="utf-8")
    header = next(line for line in text.splitlines() if line.startswith("arm,"))
    assert header.startswith("arm,variant,tool,format,operation,")
    assert "readcon-extxyz-read,single,readcon,extxyz,read," in text
    assert "alloy-readcon-extxyz-read,alloy,readcon,extxyz,read," in text
    assert FORBIDDEN_SHA not in text
    assert "abc123" in text


def test_empty_sha_is_head(monkeypatch):
    monkeypatch.delenv("READCON_SHA", raising=False)
    head = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
    ).strip()
    assert samefmt._readcon_sha() == head
    assert head != FORBIDDEN_SHA


def test_sha_failure_is_loud(monkeypatch):
    monkeypatch.setenv("READCON_SHA", "  ")

    def fail(*_args, **_kwargs):
        raise subprocess.CalledProcessError(1, ["git"], output="no head")

    monkeypatch.setattr(samefmt.subprocess, "check_output", fail)
    with pytest.raises(RuntimeError, match="rev-parse"):
        samefmt._readcon_sha()


def test_csv_empty_sha_uses_head_not_the_stand_in(tmp_path, monkeypatch):
    monkeypatch.delenv("READCON_SHA", raising=False)
    head = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
    ).strip()
    dest = tmp_path / "table.csv"
    samefmt._write_csv([_row("readcon-con-read")], dest)
    text = dest.read_text(encoding="utf-8")
    assert head in text
    assert FORBIDDEN_SHA not in text


def test_setup_passes_variant_and_does_not_source_eon(monkeypatch):
    calls = []
    monkeypatch.setattr(samefmt, "prepare", lambda: None)
    monkeypatch.setattr(
        samefmt,
        "_source",
        lambda tool, fmt, variant="single": calls.append((tool, fmt, variant)),
    )
    monkeypatch.setattr(
        samefmt,
        "_ensure_eon_binary",
        lambda: calls.append(("binary",)) or Path("eon_samefmt"),
    )
    module = _asv()
    module.Same_alloy_ase_cextxyz_write().setup()
    assert ("ase", "cextxyz", "alloy") in calls
    calls.clear()
    module.Same_eon_cpp_con_write().setup()
    assert calls == [("binary",)]
    calls.clear()
    module.Same_readcon_con_read().setup()
    assert calls == []


def test_eon_cpp_sample_uses_the_python_clock(tmp_path, monkeypatch):
    monkeypatch.setattr(samefmt, "REPEATS", 1)
    monkeypatch.setattr(samefmt, "prepare", lambda: None)
    monkeypatch.setattr(samefmt, "_ensure_eon_binary", lambda: tmp_path / "eon_samefmt")
    monkeypatch.setattr(
        samefmt,
        "_check",
        lambda _arm, _result: {
            "n_atoms": 4,
            "n_frames": 1,
            "fields": {"positions": "ok"},
            "id_map_ok": True,
            "reordered": False,
            "correct": True,
            "reason": "ok",
        },
    )
    monkeypatch.setattr(samefmt, "RESULTS", tmp_path)
    ticks = iter([10.0, 10.25])
    monkeypatch.setattr(samefmt.time, "perf_counter", lambda: next(ticks))

    def inner_wall(*_args, **_kwargs):
        raise AssertionError("inner wall")

    monkeypatch.setattr(samefmt, "_eon_cpp_timed", inner_wall, raising=False)
    monkeypatch.setattr(samefmt, "once", lambda _arm: "called")
    row = samefmt.run("eon-cpp-con-read")
    assert row["median_s"] == pytest.approx(0.25)
    assert row["arm"] == "eon-cpp-con-read"
    assert row["variant"] == "single"
    assert (tmp_path / "eon-cpp-con-read.stdout").is_file()


def test_multiframe_ase_con_reads_fixatoms():
    pytest.importorskip("ase")
    from ase import Atoms
    from ase.constraints import FixAtoms

    def image():
        atoms = Atoms("Cu2", positions=[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], cell=[2.0, 2.0, 2.0], pbc=True)
        atoms.set_constraint(FixAtoms(indices=[1]))
        return atoms

    one = samefmt._got_from_ase(image(), "con")
    many = samefmt._got_from_ase([image(), image()], "con")
    assert list(one["fixed"]) == [0, 7]
    assert many["fixed"] is not None
    assert many["fixed"].shape == (2, 2)
    assert list(many["fixed"][0]) == [0, 7]
    assert list(many["fixed"][1]) == [0, 7]
    assert many["velocities"] is None


def test_a_failed_arm_is_stored(tmp_path, monkeypatch):
    monkeypatch.setattr(samefmt, "REPEATS", 1)
    monkeypatch.setattr(samefmt, "prepare", lambda: None)
    monkeypatch.setattr(samefmt, "RESULTS", tmp_path)

    def fail(_arm):
        raise RuntimeError("no readcon")

    monkeypatch.setattr(samefmt, "once", fail)
    row = samefmt.run("readcon-con-read")
    assert row["reason"].startswith("unsupported:")
    assert "no readcon" in row["reason"]
    assert row["arm"] == "readcon-con-read"
    assert row["variant"] == "single"
    assert row["correct"] is None
    assert FORBIDDEN_SHA not in (row.get("readcon_sha") or "")
    assert (tmp_path / "readcon-con-read.stdout").is_file()
