"""Benchmark scripts must not default a destination to the system temporary directory."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BENCH = ROOT / "bench"
sys.path.insert(0, str(ROOT))
from readcon_bench import bench_file  # noqa: E402


def _string_constants(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.lineno, node.value


def test_bench_scripts_do_not_default_to_the_system_temporary_directory() -> None:
    offenders: list[str] = []
    for path in sorted(BENCH.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for lineno, value in _string_constants(tree):
            if (
                value == "/tmp"
                or value.startswith("/tmp/")
                or value.startswith("/var/tmp")
            ):
                offenders.append(f"{path.relative_to(ROOT)}:{lineno}")
    assert not offenders, (
        "bench script defaults to a temporary directory:\n" + "\n".join(offenders)
    )


def test_bench_file_leaves_no_private_directory() -> None:
    path = bench_file("unit", ".con")
    try:
        assert path.parent.name == "unit"
        assert path.is_file()
    finally:
        path.unlink(missing_ok=True)
    assert not path.exists()
    assert path.parent.is_dir()
