# Copyright (c) readcon-core developers
"""Timed build routes select and verify the shipped allocator."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
NON_TIMING_EXAMPLES = {"rust_usage", "mpi_smoke", "parse_probe", "stream_triad"}


def _logical_lines(text: str) -> list[str]:
    commands: list[str] = []
    pending = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        pending = f"{pending} {line}".strip()
        if pending.endswith("\\"):
            pending = pending[:-1].rstrip()
        else:
            commands.append(pending)
            pending = ""
    if pending:
        commands.append(pending)
    return commands


def _example_guard(root: Path) -> list[str]:
    examples = root / "examples"
    names = {path.stem for path in examples.glob("*.rs")}
    names.update(path.parent.name for path in examples.glob("*/main.rs"))
    manifest = tomllib.loads((root / "Cargo.toml").read_text(encoding="utf-8"))
    declared = {
        example["name"]: set(example.get("required-features", ()))
        for example in manifest.get("example", ())
    }
    return sorted(
        name
        for name in names - NON_TIMING_EXAMPLES
        if "benchmark" not in declared.get(name, set())
    )


def _assigned_literal(path: Path, name: str):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{path} does not assign {name}")


def test_documented_criterion_commands_use_the_benchmark_feature() -> None:
    docs = (
        "docs/source/benchmarks.rst",
        "docs/source/contributing.rst",
        "docs/orgmode/benchmarks.org",
        "docs/orgmode/contributing.org",
    )
    bad = []
    for route in docs:
        for line in _logical_lines((ROOT / route).read_text(encoding="utf-8")):
            if "cargo bench" in line and (
                "--features" not in line
                or "benchmark" not in line
                or "mimalloc-allocator" in line
            ):
                bad.append(f"{route}: {line.strip()}")
            if "cargo bench" in line and "profile-generate" in line:
                if "-Cprofile-generate=$PWD/build/pgo" not in line:
                    bad.append(f"{route}: relative profile path: {line.strip()}")
    assert not bad, "stale Criterion commands:\n" + "\n".join(bad)


def test_every_timing_example_requires_the_benchmark_feature() -> None:
    examples_dir = ROOT / "examples"
    names = {path.stem for path in examples_dir.glob("*.rs")}
    names.update(path.parent.name for path in examples_dir.glob("*/main.rs"))
    assert NON_TIMING_EXAMPLES <= names
    assert "Instant" not in (examples_dir / "parse_probe.rs").read_text(
        encoding="utf-8"
    )
    stream = (examples_dir / "stream_triad.rs").read_text(encoding="utf-8")
    assert "Instant" in stream and "readcon_core" not in stream
    assert not _example_guard(ROOT)


def test_system_time_example_mutation_fails_the_guard(tmp_path: Path) -> None:
    (tmp_path / "examples").mkdir()
    (tmp_path / "examples/system_clock.rs").write_text(
        "fn main() { let _ = std::time::SystemTime::now(); }\n"
    )
    (tmp_path / "Cargo.toml").write_text(
        '[[example]]\nname = "system_clock"\npath = "examples/system_clock.rs"\n'
    )
    assert _example_guard(tmp_path) == ["system_clock"]


def test_nested_example_mutation_fails_the_guard(tmp_path: Path) -> None:
    source = tmp_path / "examples" / "sub_probe"
    source.mkdir(parents=True)
    (source / "main.rs").write_text("fn main() {}\n")
    (tmp_path / "Cargo.toml").write_text("")
    assert _example_guard(tmp_path) == ["sub_probe"]


def test_non_example_timed_build_routes_select_benchmark() -> None:
    asv = json.loads((ROOT / "asv.conf.json").read_text(encoding="utf-8"))
    asv_builds = [
        command for command in asv["build_command"] if "maturin build" in command
    ]
    assert asv_builds and all("benchmark" in command for command in asv_builds)

    pixi = tomllib.loads((ROOT / "pixi.toml").read_text(encoding="utf-8"))
    assert "benchmark" in pixi["tasks"]["bench"]

    bench = ROOT / "paper" / "cpc" / "bench"
    assert "benchmark" in _assigned_literal(bench / "cachegrind.py", "FEATURES")
    assert "benchmark" in _assigned_literal(bench / "cpp_reads.py", "FEATURES")
    assert 'features = ["parallel", "benchmark"]' in (
        bench / "binary_formats.py"
    ).read_text(encoding="utf-8")
    h2h = (bench / "h2h.py").read_text(encoding="utf-8")
    assert h2h.count('"parallel,benchmark"') == 2

    manifests = sorted(bench.glob("*/Cargo.toml"))
    dependencies = []
    for manifest in manifests:
        cargo = tomllib.loads(manifest.read_text(encoding="utf-8"))
        readcon = cargo.get("dependencies", {}).get("readcon-core")
        if isinstance(readcon, dict):
            dependencies.append((manifest, set(readcon.get("features", ()))))
    assert dependencies
    assert not [
        str(manifest.relative_to(ROOT))
        for manifest, features in dependencies
        if "benchmark" not in features
    ]


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
