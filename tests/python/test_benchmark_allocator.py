# Copyright (c) readcon-core developers
"""Timed build routes select and verify the shipped allocator."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_timing_routes_name_the_benchmark_feature() -> None:
    routes = (
        "asv.conf.json",
        "pixi.toml",
        "benchmarks/workflow/weak/COMMANDS.txt",
        "bench/h2h/camp6.py",
        "bench/h2h/mem_r1.py",
        "bench/h2h/parse_limiter.py",
        "bench/h2h/release_campaign.py",
        "bench/h2h/scale_r6.py",
        "bench/h2h/support.py",
        "paper/cpc/bench/binary_formats.py",
        "paper/cpc/bench/cachegrind.py",
        "paper/cpc/bench/cpp_reads.py",
        "paper/cpc/bench/h2h.py",
        "paper/cpc/bench/dlpack_cost/Cargo.toml",
        "paper/cpc/bench/mpi_cost/Cargo.toml",
        "paper/cpc/bench/readcon-bench/Cargo.toml",
        "paper/cpc/pixi.toml",
        "scripts/run_cachegrind_bench.sh",
    )
    missing = [
        route
        for route in routes
        if "benchmark" not in (ROOT / route).read_text(encoding="utf-8")
    ]
    assert not missing, f"timing routes without the benchmark feature: {missing}"


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
