"""``bench_dlpack.py`` never writes the tracked ``dlpack_macros.tex``.

``paper/cpc/src/figures/generated/dlpack_macros.tex`` is written by
``gen_dlpack_macros.py`` from ``data/dlpack_cost.txt``. The bench times a new
run at other sizes and repeats, so a bench run that wrote that file would
replace the paper's DLPack numbers with a different measurement.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "paper" / "cpc" / "scripts"
TRACKED = ROOT / "paper" / "cpc" / "src" / "figures" / "generated" / "dlpack_macros.tex"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"{name}_under_test", SCRIPTS / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def bench():
    return _load("bench_dlpack")


def _tracked() -> set[str]:
    out = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    )
    return set(out.stdout.splitlines())


def test_the_fragment_of_the_paper_is_the_one_the_generator_writes(bench) -> None:
    generator = _load("gen_dlpack_macros")
    assert generator.OUT == TRACKED
    assert TRACKED.relative_to(ROOT).as_posix() in _tracked()


def test_no_output_path_of_the_bench_is_the_tracked_fragment(bench) -> None:
    written = [bench.MACROS, bench.TABLE, bench.FIGURE, bench.LOG]
    assert TRACKED not in written, written
    assert bench.MACROS.name != TRACKED.name
    generated = [p.relative_to(ROOT).as_posix() for p in written[:3]]
    assert not set(generated) & _tracked(), generated


def test_the_bench_source_does_not_name_the_tracked_fragment(bench) -> None:
    code = "\n".join(
        line
        for line in (SCRIPTS / "bench_dlpack.py").read_text().splitlines()
        if not line.lstrip().startswith("#")
    )
    body = code.split('"""', 2)[2]
    assert "dlpack_macros" not in body


def test_writing_the_tables_leaves_the_tracked_macros_alone(
    bench, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "generated"
    out.mkdir()
    monkeypatch.setattr(bench, "OUT", out)
    monkeypatch.setattr(bench, "MACROS", out / bench.MACROS.name)
    monkeypatch.setattr(bench, "TABLE", out / bench.TABLE.name)
    rows = [(n, 4.0e-6 * (i + 1), 3.0e-6, 5.0e-6) for i, n in enumerate(bench.SIZES)]
    exchange = {"numpy": rows}
    copies = [(n, 3.0e-5 * (i + 1), 2.0e-5, 4.0e-5) for i, n in enumerate(bench.SIZES)]
    before = TRACKED.read_bytes()
    bench.write_tex(exchange, copies, [4.0e-6] * 8, [3.0e-5] * 8, "0" * 40)
    assert TRACKED.read_bytes() == before
    assert sorted(p.name for p in out.iterdir()) == [
        "dlpack_exchange_values.tex",
        "dlpack_table.tex",
    ]
    names = re.findall(
        r"\\newcommand\{\\(\w+)\}", (out / "dlpack_exchange_values.tex").read_text()
    )
    assert names and all(name.startswith("dlpackBench") for name in names), names
    tracked_names = set(re.findall(r"\\newcommand\{\\(\w+)\}", before.decode()))
    assert not tracked_names & set(names)
