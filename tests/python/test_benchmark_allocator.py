# Copyright (c) readcon-core developers
"""Timed build routes select and verify the shipped allocator."""

from __future__ import annotations

import os
import subprocess
import sys
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
            if "cargo bench" in line and "--features" in line:
                if "benchmark" not in line or "global_mimalloc" in line:
                    bad.append(f"{route}: {line.strip()}")
    assert not bad, "stale Criterion commands:\n" + "\n".join(bad)


def test_timing_routes_name_the_benchmark_feature() -> None:
    commands = (
        ("asv.conf.json", "--features python,chemfiles-from-sources,benchmark", 1),
        ("pixi.toml", 'bench = "cargo bench --features parallel,benchmark"', 1),
        ("benchmarks/workflow/weak/COMMANDS.txt", "--features mpi,benchmark", 1),
        ("benchmarks/workflow/weak/COMMANDS.txt", "--features parallel,benchmark", 1),
        ("bench/h2h/camp6.py", '"python,zstd,benchmark"', 1),
        ("bench/h2h/mem_r1.py", '"parallel,benchmark"', 1),
        ("bench/h2h/mem_r1.py", '"python,parallel,benchmark"', 1),
        ("bench/h2h/parse_limiter.py", '"benchmark"', 1),
        ("bench/h2h/release_campaign.py", '"python,zstd,benchmark"', 1),
        ("bench/h2h/scale_r6.py", '"parallel,benchmark"', 1),
        ("bench/h2h/scale_r6.py", '"parallel,mpi,benchmark"', 1),
        ("bench/h2h/scale_r6.py", '"parallel,zstd,benchmark"', 1),
        ("bench/h2h/support.py", '"parallel,benchmark"', 1),
        ("paper/cpc/bench/binary_formats.py", 'features = ["parallel", "benchmark"]', 1),
        ("paper/cpc/bench/cachegrind.py", '"chemfiles-from-sources,benchmark"', 1),
        ("paper/cpc/bench/cpp_reads.py", '["parallel", "benchmark"]', 1),
        ("paper/cpc/bench/h2h.py", '"parallel,benchmark"', 2),
        ("paper/cpc/bench/h2h.py", '"cargo_features": ["parallel", "benchmark"]', 1),
        ("paper/cpc/bench/dlpack_cost/Cargo.toml", 'features = ["benchmark"]', 1),
        ("paper/cpc/bench/mpi_cost/Cargo.toml", 'features = ["mpi", "benchmark"]', 1),
        (
            "paper/cpc/bench/readcon-bench/Cargo.toml",
            'features = ["parallel", "benchmark"]',
            1,
        ),
        ("paper/cpc/pixi.toml", "--features python,zstd,benchmark", 1),
        ("paper/cpc/pixi.toml", "--features benchmark", 1),
        ("paper/cpc/pixi.toml", "--features parallel,benchmark", 1),
        ("paper/cpc/pixi.toml", "--features zstd,benchmark", 1),
        ("scripts/run_cachegrind_bench.sh", '},benchmark"', 1),
    )
    missing = [
        f"{route}: {fragment} ({actual}/{count})"
        for route, fragment, count in commands
        if (
            actual := (ROOT / route).read_text(encoding="utf-8").count(fragment)
        )
        < count
    ]
    assert not missing, "timed build commands without benchmark:\n" + "\n".join(missing)


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
