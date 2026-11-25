"""The final clause coverage chain follows supersedes links, whatever the series."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
LEDGER = Path(__file__).resolve().parents[1] / "data" / "spec"
VERSION = (Path(__file__).resolve().parents[3] / "VERSION").read_text().strip()


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


def _ledger_copy(tmp_path: Path) -> Path:
    """A copy of the stored clause coverage records of this version."""
    spec_dir = tmp_path / "spec"
    spec_dir.mkdir()
    for path in LEDGER.glob(f"clause_coverage-{VERSION}*.json"):
        shutil.copy2(path, spec_dir / path.name)
    return spec_dir


def _supersedes(name: str) -> dict:
    return {"supersedes": f"paper/cpc/data/spec/{name}"}


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


def test_stored_ledger_chain_is_spec_major_then_capi(tmp_path: Path) -> None:
    clause_coverage = _load(
        "clause_coverage_under_test", SCRIPTS / "clause_coverage.py"
    )
    spec_dir = _ledger_copy(tmp_path)
    names = [p.name for p in clause_coverage.final_chain(spec_dir, VERSION)]
    assert names == [
        *(
            f"clause_coverage-{VERSION}-spec-major{'' if n == 1 else f'-{n}'}.json"
            for n in range(1, 11)
        ),
        f"clause_coverage-{VERSION}-capi-r1.json",
    ]
    # -r2 supersedes the legacy record beside spec-major. Its stem names no
    # series, so the walk leaves it as a side record of the legacy record.
    off_chain = spec_dir / f"clause_coverage-{VERSION}-r2.json"
    assert json.loads(off_chain.read_text(encoding="utf-8")) == json.loads(
        (LEDGER / off_chain.name).read_text(encoding="utf-8")
    )
    assert clause_coverage.record_series(off_chain, VERSION) is None
    assert off_chain.name not in names


def test_stored_ledger_never_makes_r2_final(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clause_coverage = _load(
        "clause_coverage_under_test", SCRIPTS / "clause_coverage.py"
    )
    spec_dir = _ledger_copy(tmp_path)
    monkeypatch.setattr(clause_coverage, "RECORD_DIR", spec_dir)
    monkeypatch.setattr(
        clause_coverage, "LEGACY_RECORD", spec_dir / f"clause_coverage-{VERSION}.json"
    )
    monkeypatch.setattr(clause_coverage, "build", lambda: {"totals": {}})
    monkeypatch.setattr(clause_coverage, "rel", lambda path: f"data/{path.name}")
    tip, payload = clause_coverage.record_for_sources()
    assert tip.name == f"clause_coverage-{VERSION}-capi-r1.json"
    assert payload["reason"] == json.loads(tip.read_text(encoding="utf-8"))["reason"]
    for series in (None, "capi", "spec-major"):
        out, payload = clause_coverage.next_record_for_sources(series)
        assert out.name != f"clause_coverage-{VERSION}-r2.json"
        assert payload["supersedes"] == f"data/{tip.name}"


def test_stored_ledger_fork_fails(tmp_path: Path) -> None:
    clause_coverage = _load(
        "clause_coverage_under_test", SCRIPTS / "clause_coverage.py"
    )
    spec_dir = _ledger_copy(tmp_path)
    parent = f"clause_coverage-{VERSION}-spec-major-10.json"
    _write_json(
        spec_dir / f"clause_coverage-{VERSION}-writer-r1.json", _supersedes(parent)
    )
    with pytest.raises(SystemExit, match=f"2 records of data/spec supersede {parent}"):
        clause_coverage.final_chain(spec_dir, VERSION)


def test_stored_ledger_fork_at_the_legacy_record_fails(tmp_path: Path) -> None:
    clause_coverage = _load(
        "clause_coverage_under_test", SCRIPTS / "clause_coverage.py"
    )
    spec_dir = _ledger_copy(tmp_path)
    legacy = f"clause_coverage-{VERSION}.json"
    _write_json(
        spec_dir / f"clause_coverage-{VERSION}-old-r2.json", _supersedes(legacy)
    )
    with pytest.raises(SystemExit, match=f"records of data/spec supersede {legacy}"):
        clause_coverage.final_chain(spec_dir, VERSION)


@pytest.mark.parametrize(
    "payload",
    [
        _supersedes(f"clause_coverage-{VERSION}-capi-r9.json"),
        _supersedes("clause_coverage-0.0.0-spec-major.json"),
        {},
    ],
    ids=["missing-record", "other-version", "no-supersedes"],
)
def test_stored_ledger_dangling_supersedes_fails(tmp_path: Path, payload: dict) -> None:
    clause_coverage = _load(
        "clause_coverage_under_test", SCRIPTS / "clause_coverage.py"
    )
    spec_dir = _ledger_copy(tmp_path)
    _write_json(spec_dir / f"clause_coverage-{VERSION}-capi-r2.json", payload)
    with pytest.raises(SystemExit, match="capi-r2.json does not supersede"):
        clause_coverage.final_chain(spec_dir, VERSION)


def test_stored_ledger_record_superseding_the_tip_off_series_fails(
    tmp_path: Path,
) -> None:
    clause_coverage = _load(
        "clause_coverage_under_test", SCRIPTS / "clause_coverage.py"
    )
    spec_dir = _ledger_copy(tmp_path)
    tip = f"clause_coverage-{VERSION}-capi-r1.json"
    _write_json(
        spec_dir / f"clause_coverage-{VERSION}-after-tip.json", _supersedes(tip)
    )
    with pytest.raises(SystemExit, match=f"1 records of data/spec supersede {tip}"):
        clause_coverage.final_chain(spec_dir, VERSION)
