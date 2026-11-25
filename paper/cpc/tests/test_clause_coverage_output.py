"""clause_coverage.py appends a superseding final record and never rewrites a stored one."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load():
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(
        "clause_coverage", SCRIPTS / "clause_coverage.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _configure(
    module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, count: int = 10
):
    repo = tmp_path / "repo"
    root = repo / "paper" / "cpc"
    spec_dir = root / "data" / "spec"
    macros = root / "src" / "figures" / "generated" / "clauses_macros.tex"
    spec_dir.mkdir(parents=True, exist_ok=True)
    macros.parent.mkdir(parents=True, exist_ok=True)
    (repo / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    base = spec_dir / "clause_coverage-0.1.0.json"
    base.write_text('{"clauses": []}\n', encoding="utf-8")

    monkeypatch.setattr(module, "REPO", repo)
    monkeypatch.setattr(module, "ROOT", root)
    monkeypatch.setattr(module, "VERSION", "0.1.0")
    monkeypatch.setattr(module, "MACROS", macros)
    monkeypatch.setattr(module, "RECORD_DIR", spec_dir)
    monkeypatch.setattr(module, "LEGACY_RECORD", base)

    state = {"rust_tests": count}

    def fake_build(supersedes: Path | None = None) -> dict:
        assert supersedes is None
        return {
            "sources": {
                "tests": {
                    "roots": ["tests", "src"],
                    "files": 1,
                    "rust_tests": state["rust_tests"],
                    "python_tests": 0,
                    "naming": 1,
                    "clause_ids": 1,
                    "unknown_ids": [],
                }
            },
            "totals": {
                "clauses": 1,
                "covered": 1,
                "corpus": 0,
                "corpus31": 0,
                "conformance": 0,
                "probes": 0,
                "tests": 1,
                "indep_reader": 0,
                "uncovered": 0,
            },
            "uncovered": [],
            "clauses": [{"id": "CON-file.1", "keyword": "MUST"}],
        }

    monkeypatch.setattr(module, "build", fake_build)
    return repo, root, spec_dir, macros, state


def test_clause_coverage_appends_superseding_records_without_rewriting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load()
    repo, root, spec_dir, macros, state = _configure(module, tmp_path, monkeypatch, 10)

    def run(*args: str) -> int:
        monkeypatch.setattr("sys.argv", ["clause_coverage.py", *args])
        return module.main()

    def paths() -> tuple[Path, Path]:
        return module.default_paths(root=root, repo=repo, version="0.1.0")

    # Without --record only the TeX is written.
    assert run() == 0
    assert macros.is_file()
    assert not list(spec_dir.glob("clause_coverage-0.1.0-spec-major*.json"))

    assert run("--record") == 0
    first = spec_dir / "clause_coverage-0.1.0-spec-major.json"
    assert first.is_file()
    first_bytes = first.read_bytes()
    assert json.loads(first.read_text(encoding="utf-8"))["supersedes"] == (
        "paper/cpc/data/spec/clause_coverage-0.1.0.json"
    )
    assert "from the live tree." in macros.read_text(encoding="utf-8")

    # Recording again with identical sources adds no new record.
    assert run("--record") == 0
    assert first.read_bytes() == first_bytes
    assert not (spec_dir / "clause_coverage-0.1.0-spec-major-2.json").exists()

    # When sources change, --check fails on the stale final record, and
    # --record appends spec-major-2.json while leaving spec-major.json untouched.
    state["rust_tests"] = 12
    assert run("--check") == 1
    assert run("--record") == 0
    second = spec_dir / "clause_coverage-0.1.0-spec-major-2.json"
    assert second.is_file()
    assert first.read_bytes() == first_bytes
    second_bytes = second.read_bytes()
    assert json.loads(second.read_text(encoding="utf-8"))["supersedes"] == (
        "paper/cpc/data/spec/clause_coverage-0.1.0-spec-major.json"
    )
    assert paths() == (first, second)
    assert run("--check") == 0

    # A third change appends spec-major-3.json superseding spec-major-2.json.
    state["rust_tests"] = 15
    assert run("--record") == 0
    third = spec_dir / "clause_coverage-0.1.0-spec-major-3.json"
    assert third.is_file()
    assert first.read_bytes() == first_bytes
    assert second.read_bytes() == second_bytes
    assert json.loads(third.read_text(encoding="utf-8"))["supersedes"] == (
        "paper/cpc/data/spec/clause_coverage-0.1.0-spec-major-2.json"
    )
    assert paths() == (second, third)
    assert [p.name for p in module.final_chain()] == [
        first.name,
        second.name,
        third.name,
    ]

    # An explicit --out that names a stored record with other bytes is refused.
    state["rust_tests"] = 16
    with pytest.raises(SystemExit, match="refusing to overwrite committed record"):
        run("--record", "--out", str(second))
    assert second.read_bytes() == second_bytes


def test_default_paths_rejects_broken_supersedes_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load()
    repo, root, spec_dir, _, _ = _configure(module, tmp_path, monkeypatch, 10)
    (spec_dir / "clause_coverage-0.1.0-spec-major.json").write_text(
        json.dumps({"supersedes": "paper/cpc/data/spec/clause_coverage-0.1.0.json"})
        + "\n",
        encoding="utf-8",
    )
    for n in (2, 3):
        (spec_dir / f"clause_coverage-0.1.0-spec-major-{n}.json").write_text(
            json.dumps(
                {
                    "supersedes": "paper/cpc/data/spec/clause_coverage-0.1.0-spec-major.json"
                }
            )
            + "\n",
            encoding="utf-8",
        )
    with pytest.raises(SystemExit, match="must form one chain"):
        module.default_paths(root=root, repo=repo, version="0.1.0")
