# Copyright (c) readcon-core developers
"""Timed build routes select and verify the shipped allocator."""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_documented_criterion_commands_use_the_benchmark_feature() -> None:
    docs = (
        "docs/source/benchmarks.rst",
        "docs/source/contributing.rst",
        "docs/orgmode/benchmarks.org",
        "docs/orgmode/contributing.org",
    )
    bad = []
    for route in docs:
        for line in (ROOT / route).read_text(encoding="utf-8").splitlines():
            if "cargo bench" in line and (
                "--features" not in line
                or "benchmark" not in line
                or "global_mimalloc" in line
            ):
                bad.append(f"{route}: {line.strip()}")
    assert not bad, "stale Criterion commands:\n" + "\n".join(bad)


def test_every_timing_example_requires_the_benchmark_feature() -> None:
    timing_examples = {
        "cachegrind_harness",
        "chemfiles_xyz_time",
        "codec_ceiling",
        "conbin_perf",
        "format_profile",
        "leaf_io_harness",
        "mpi_read_check",
        "mpi_write_check",
        "rcidx_bench",
        "scale_probe",
        "serial_probe",
        "strong_scale_mpi",
        "v31_parse_bench",
        "wall_scale_harness",
        "weak_scale_mpi",
        "weak_scale_threads",
    }
    exemptions = {
        "parse_probe": "functional parser outcome probe; it does not read a clock",
        "stream_triad": (
            "standalone rustc memory-bandwidth probe; it does not link readcon-core"
        ),
    }
    examples_dir = ROOT / "examples"
    clocked = {
        path.stem
        for path in examples_dir.glob("*.rs")
        if "Instant" in path.read_text(encoding="utf-8")
    }
    assert not clocked - timing_examples - exemptions.keys(), (
        "unclassified timing examples: "
        + ", ".join(sorted(clocked - timing_examples - exemptions.keys()))
    )
    assert "Instant" not in (examples_dir / "parse_probe.rs").read_text(encoding="utf-8")
    stream = (examples_dir / "stream_triad.rs").read_text(encoding="utf-8")
    assert "Instant" in stream and "readcon_core" not in stream

    manifest = tomllib.loads((ROOT / "Cargo.toml").read_text(encoding="utf-8"))
    declared = {
        example["name"]: set(example.get("required-features", ()))
        for example in manifest["example"]
    }
    missing = sorted(
        name for name in timing_examples if "benchmark" not in declared.get(name, set())
    )
    assert not missing, f"timing examples without required feature benchmark: {missing}"


def test_symbol_gate_rejects_a_non_mimalloc_binary() -> None:
    done = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "check_mimalloc_symbols.py"),
            "/bin/true",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode != 0
    assert "no defined mi_ symbol" in done.stderr


def test_regen_measure_rejects_a_non_mimalloc_cdylib() -> None:
    done = subprocess.run(
        [sys.executable, "paper/cpc/scripts/regen_paper.py", "--measure"],
        cwd=ROOT,
        env={**os.environ, "READCON_LIB": "/bin/true"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode != 0
    assert "no defined mi_ symbol" in done.stderr
