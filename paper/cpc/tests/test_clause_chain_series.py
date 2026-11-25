"""The final clause coverage chain follows supersedes links, whatever the series."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name: str, path: Path):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")


def _final_fixture(spec_dir: Path, version: str, names: list[tuple[str, str]]) -> None:
    """Write the legacy record and each (name, superseded name) pair."""
    _write_json(spec_dir / f"clause_coverage-{version}.json", {})
    for name, prior in names:
        _write_json(
            spec_dir / f"clause_coverage-{version}-{name}.json",
            {
                "supersedes": f"paper/cpc/data/spec/clause_coverage-{version}-{prior}.json"
            }
            if prior
            else {"supersedes": f"paper/cpc/data/spec/clause_coverage-{version}.json"},
        )


@pytest.mark.parametrize(
    "order",
    [("writer-r1", "capi-r1"), ("capi-r1", "writer-r1")],
)
def test_final_chain_is_linear_in_either_landing_order(
    tmp_path: Path, order: tuple[str, str]
) -> None:
    clause_coverage = _load(
        "clause_coverage_under_test", SCRIPTS / "clause_coverage.py"
    )
    spec_dir = tmp_path / "spec"
    version = "0.99.0"
    first, second = order
    _final_fixture(
        spec_dir,
        version,
        [
            ("spec-major", ""),
            ("spec-major-2", "spec-major"),
            (first, "spec-major-2"),
            (second, first),
        ],
    )
    names = [p.name for p in clause_coverage.final_chain(spec_dir, version)]
    assert names == [
        f"clause_coverage-{version}-{stem}.json"
        for stem in ("spec-major", "spec-major-2", first, second)
    ]


def test_final_chain_rejects_two_series_that_supersede_one_record(
    tmp_path: Path,
) -> None:
    clause_coverage = _load(
        "clause_coverage_under_test", SCRIPTS / "clause_coverage.py"
    )
    spec_dir = tmp_path / "spec"
    version = "0.99.0"
    _final_fixture(
        spec_dir,
        version,
        [
            ("spec-major", ""),
            ("writer-r1", "spec-major"),
            ("capi-r1", "spec-major"),
        ],
    )
    with pytest.raises(SystemExit, match="2 records of data/spec supersede"):
        clause_coverage.final_chain(spec_dir, version)


def test_final_chain_rejects_a_final_record_off_the_chain(tmp_path: Path) -> None:
    clause_coverage = _load(
        "clause_coverage_under_test", SCRIPTS / "clause_coverage.py"
    )
    spec_dir = tmp_path / "spec"
    version = "0.99.0"
    _final_fixture(
        spec_dir,
        version,
        [("spec-major", ""), ("writer-r1", "spec-major")],
    )
    _write_json(
        spec_dir / f"clause_coverage-{version}-capi-r1.json",
        {"supersedes": "paper/cpc/data/spec/elsewhere.json"},
    )
    with pytest.raises(SystemExit, match="capi-r1.json does not supersede"):
        clause_coverage.final_chain(spec_dir, version)


def test_record_appends_to_the_series_of_the_newest_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clause_coverage = _load(
        "clause_coverage_under_test", SCRIPTS / "clause_coverage.py"
    )
    spec_dir = tmp_path / "spec"
    version = "0.99.0"
    _final_fixture(
        spec_dir,
        version,
        [("spec-major", ""), ("writer-r1", "spec-major")],
    )
    monkeypatch.setattr(clause_coverage, "RECORD_DIR", spec_dir)
    monkeypatch.setattr(clause_coverage, "VERSION", version)
    monkeypatch.setattr(
        clause_coverage, "LEGACY_RECORD", spec_dir / f"clause_coverage-{version}.json"
    )
    monkeypatch.setattr(clause_coverage, "build", lambda: {"totals": {}})
    monkeypatch.setattr(clause_coverage, "rel", lambda path: f"data/{path.name}")

    out, payload = clause_coverage.next_record_for_sources()
    assert out.name == f"clause_coverage-{version}-writer-r2.json"
    assert payload["supersedes"] == f"data/clause_coverage-{version}-writer-r1.json"
    out, payload = clause_coverage.next_record_for_sources("capi")
    assert out.name == f"clause_coverage-{version}-capi-r1.json"
    assert payload["supersedes"] == f"data/clause_coverage-{version}-writer-r1.json"
    assert payload["reason"].startswith("Capi-series recount")
    out, _ = clause_coverage.next_record_for_sources("spec-major")
    assert out.name == f"clause_coverage-{version}-spec-major-2.json"
    with pytest.raises(SystemExit, match="not a series name"):
        clause_coverage.next_record_for_sources("Bad_Series")
