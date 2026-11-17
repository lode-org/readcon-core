"""Negative checks from the rerun-driver review."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bench" / "h2h"))
sys.path.insert(0, str(ROOT / "paper" / "cpc" / "bench"))
sys.path.insert(0, str(ROOT / "paper" / "cpc" / "scripts"))

import gil_threadfix_bench
import mpi_from_log
import rerun_helpers
import run_mpi_v2
import sample_protocol
import threadfix_tables


def _after_only() -> dict:
    return {
        "commit": "a" * 40,
        "before_commit": None,
        "after_commit": "a" * 40,
        "rows": [
            {
                "phase": "after",
                "op": "read_con",
                "threads": 1,
                "median_s": 1.0,
            }
        ],
    }


def _both_phases() -> dict:
    return {
        "commit": "a" * 40,
        "before_commit": "b" * 40,
        "after_commit": "a" * 40,
        "cpus": [1, 2],
        "rows": [
            {
                "phase": "before",
                "op": "read_con",
                "threads": 1,
                "median_s": 2.0,
            },
            {
                "phase": "after",
                "op": "read_con",
                "threads": 1,
                "median_s": 1.0,
            },
        ],
    }


def test_after_only_threadfix_record_is_refused(tmp_path: Path) -> None:
    payload = _after_only()
    record = tmp_path / "threadfix-before-after.json"
    record.write_text(__import__("json").dumps(payload), encoding="utf-8")

    with pytest.raises(SystemExit, match="after-only"):
        gil_threadfix_bench.require_threadfix_record(record)
    with pytest.raises(SystemExit, match="after-only"):
        threadfix_tables.table(payload)
    with pytest.raises(SystemExit, match="after-only"):
        threadfix_tables.load(record)

    scaling = tmp_path / "scaling"
    scaling.mkdir()
    (scaling / "threadfix-before-after.json").write_text(
        record.read_text(encoding="utf-8"), encoding="utf-8"
    )
    with pytest.raises(SystemExit, match="after-only"):
        rerun_helpers.write_superseded_markers(
            "c" * 40,
            scaling,
            tmp_path / "formats",
            tmp_path / "million",
            tmp_path / "million-results",
            tmp_path / "cpc",
        )
    assert not (scaling / "SUPERSEDED.OK").exists()

    checked = subprocess.run(
        [
            sys.executable,
            str(ROOT / "bench" / "h2h" / "gil_threadfix_bench.py"),
            "--require-record",
            str(record),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert checked.returncode != 0
    assert "after-only" in (checked.stdout + checked.stderr)

    skipped = subprocess.run(
        [
            sys.executable,
            str(ROOT / "bench" / "h2h" / "gil_threadfix_bench.py"),
            "--out",
            str(tmp_path / "out"),
            "--skip-before",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert skipped.returncode != 0
    assert "skip-before" in (skipped.stdout + skipped.stderr)
    assert not (tmp_path / "out" / "threadfix-before-after.json").exists()


def test_threadfix_table_keeps_both_phases() -> None:
    text = threadfix_tables.table(_both_phases())
    assert "before" in text
    assert "after" in text
    assert "read_con" in text


def test_fake_mpirun_exiting_42_is_not_a_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    launcher = bindir / "mpirun"
    launcher.write_text("#!/bin/sh\nexit 42\n", encoding="utf-8")
    launcher.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(run_mpi_v2, "OUT", tmp_path / "out")
    monkeypatch.setattr(run_mpi_v2, "LOG", tmp_path / "mpi.log")
    # run_mpi_v2.ROOT is paper/, and the launcher cwd is that directory.
    work = ROOT / "paper" / "cpc" / "bench" / "work" / "mpi-fake-test"
    monkeypatch.setattr(run_mpi_v2, "WORK", work)
    try:
        with pytest.raises(SystemExit, match="42"):
            run_mpi_v2.main()
    finally:
        shutil.rmtree(work, ignore_errors=True)
    assert not (tmp_path / "mpi.log").exists()
    assert not (tmp_path / "out" / "mpi.log").exists()


def test_rank_exit_is_refused_even_when_the_launcher_returns_zero() -> None:
    proc = subprocess.CompletedProcess(
        args=["mpirun"],
        returncode=0,
        stdout="ranks 1 frames 1 local 1 ns 10 sum 1.0 exit 7\n",
        stderr="",
    )
    with pytest.raises(SystemExit, match="7"):
        run_mpi_v2.launch_record(proc, repeat=0, mode="shared", ranks=1)


def test_mpi_log_nonzero_status_is_refused() -> None:
    line = "repeat 0 mode shared launch ranks 1 frames 1 local 1 ns 10 sum 1 exit 42\n"
    with pytest.raises(SystemExit, match="42"):
        mpi_from_log.samples(line)
    with pytest.raises(SystemExit, match="42"):
        mpi_from_log.samples("exit_code 42\n")


def test_cpu_override_stays_inside_the_affinity_mask(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sample_protocol.os, "sched_getaffinity", lambda _pid: {1, 2, 4})
    monkeypatch.delenv("READCON_CPU_SET", raising=False)
    sample_protocol._AFFINITY = None
    try:
        assert sample_protocol.resolve_cpus(None) == [1, 2, 4]
        assert sample_protocol.resolve_cpus("2,4") == [2, 4]
        assert sample_protocol.resolve_cpus("1-2") == [1, 2]
        assert sample_protocol.use_cpus("4") == [4]
        assert sample_protocol.cpu_record() == {"cpus": [4], "pinned": 4}
        with pytest.raises(SystemExit, match="outside"):
            sample_protocol.resolve_cpus("0")
    finally:
        sample_protocol._AFFINITY = None
        os.environ.pop("READCON_CPU_SET", None)
