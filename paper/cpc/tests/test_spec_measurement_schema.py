"""A new spec measurement must name measured_at.commit."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "spec_measurement_schema.py"


def _load():
    spec = importlib.util.spec_from_file_location("spec_measurement_schema", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_new_record_missing_measured_at_fails() -> None:
    module = _load()
    record = {
        "generator": "paper/cpc/scripts/gen_spec_supp.py --measure",
        "spec": "docs/orgmode/spec.org",
        "tags": [],
        "tree": {"release": "0.25.0", "tagged": False, "spec_blob": "abc"},
    }
    path = "paper/cpc/data/spec/spec-measurement-0.25.0.json"
    try:
        module.measured_commit(record, path)
    except module.MeasurementSchemaError as exc:
        assert path in str(exc)
        return
    raise AssertionError("a new record without measured_at.commit was accepted")


def test_a_superseding_record_supplies_the_commit() -> None:
    module = _load()
    stale = "paper/cpc/data/spec/spec-measurement-0.24.0.json"
    fresh = "paper/cpc/data/spec/spec-measurement-0.24.0-measured.json"
    records = {
        stale: {"spec": "docs/orgmode/spec.org", "tags": [], "tree": {}},
        fresh: {
            "supersedes": stale,
            "measured_at": {"commit": "a" * 40},
            "spec": "docs/orgmode/spec.org",
        },
    }
    chosen, record = module.resolve_measurement(records, stale)
    assert chosen == fresh
    assert module.measured_commit(record, chosen) == "a" * 40


def test_a_superseding_record_without_measured_at_fails() -> None:
    module = _load()
    stale = "paper/cpc/data/spec/spec-measurement-0.24.0.json"
    fresh = "paper/cpc/data/spec/spec-measurement-0.24.0-measured.json"
    records = {
        stale: {"spec": "docs/orgmode/spec.org"},
        fresh: {"supersedes": stale, "spec": "docs/orgmode/spec.org"},
    }
    chosen, record = module.resolve_measurement(records, stale)
    try:
        module.measured_commit(record, chosen)
    except module.MeasurementSchemaError as exc:
        assert fresh in str(exc)
        return
    raise AssertionError("a successor without measured_at.commit was accepted")


def test_two_successors_are_an_error() -> None:
    module = _load()
    stale = "paper/cpc/data/spec/spec-measurement-0.24.0.json"
    records = {
        stale: {"spec": "docs/orgmode/spec.org"},
        "paper/cpc/data/spec/spec-measurement-0.24.0-a.json": {"supersedes": stale},
        "paper/cpc/data/spec/spec-measurement-0.24.0-b.json": {"supersedes": stale},
    }
    try:
        module.resolve_measurement(records, stale)
    except module.MeasurementSchemaError as exc:
        assert "superseded by" in str(exc)
        return
    raise AssertionError("two successors were accepted")


def test_the_measured_record_supersedes_the_stored_file() -> None:
    module = _load()
    stale = "paper/cpc/data/spec/spec-measurement-0.24.0.json"
    fresh = "paper/cpc/data/spec/spec-measurement-0.24.0-measured.json"
    records = {
        stale: json.loads((ROOT / stale).read_text()),
        fresh: json.loads((ROOT / fresh).read_text()),
    }
    chosen, record = module.resolve_measurement(records, stale)
    assert chosen == fresh
    assert record["supersedes"] == stale
    commit = module.measured_commit(record, chosen)
    assert isinstance(commit, str) and len(commit) == 40


def test_the_legacy_list_does_not_cover_the_current_record() -> None:
    module = _load()
    assert module.LEGACY_WITHOUT_MEASURED_AT == frozenset()
    path = "paper/cpc/data/spec/spec-measurement-0.24.0.json"
    try:
        module.measured_commit({"spec": "docs/orgmode/spec.org"}, path)
    except module.MeasurementSchemaError as exc:
        assert path in str(exc)
        return
    raise AssertionError("the current record was treated as legacy")


def test_the_current_chain_ends_at_an_ancestor_of_head() -> None:
    module = _load()
    version = (ROOT / "VERSION").read_text().strip()
    spec_dir = ROOT / "paper" / "cpc" / "data" / "spec"
    records = {
        path.relative_to(ROOT).as_posix(): json.loads(path.read_text())
        for path in spec_dir.glob(f"spec-measurement-{version}*.json")
    }
    stored = f"paper/cpc/data/spec/spec-measurement-{version}.json"
    chosen, record = module.resolve_measurement(records, stored)
    commit = module.measured_commit(record, chosen)
    module.require_ancestor(ROOT, commit, chosen)
    shown = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{commit}:VERSION"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert shown.stdout.strip() == record["tree"]["release"]


def test_a_commit_off_the_history_fails(tmp_path: Path) -> None:
    module = _load()
    who = ["-c", "user.name=t", "-c", "user.email=t@t"]

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(tmp_path), *who, *args],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    git("init", "-q")
    git("commit", "-q", "--allow-empty", "-m", "base")
    base = git("rev-parse", "HEAD")
    tree = git("rev-parse", "HEAD^{tree}")
    dangling = git("commit-tree", tree, "-p", base, "-m", "rewritten")
    module.require_ancestor(tmp_path, base, "record.json")
    for commit in (dangling, "0" * 40):
        try:
            module.require_ancestor(tmp_path, commit, "record.json")
        except module.MeasurementSchemaError as exc:
            assert commit in str(exc)
            continue
        raise AssertionError(f"{commit} off the history was accepted")


def test_off_chain_records_are_stored_and_replace_nothing() -> None:
    module = _load()
    stale = "paper/cpc/data/spec/spec-measurement-0.24.0.json"
    fresh = "paper/cpc/data/spec/spec-measurement-0.24.0-measured.json"
    (stray,) = module.OFF_CHAIN
    assert (ROOT / stray).is_file()
    assert json.loads((ROOT / stray).read_text())["supersedes"] == stale
    records = {
        stale: {"spec": "docs/orgmode/spec.org"},
        fresh: {"supersedes": stale, "measured_at": {"commit": "a" * 40}},
        stray: {"supersedes": stale, "measured_at": {"commit": "b" * 40}},
    }
    chosen, _ = module.resolve_measurement(records, stale)
    assert chosen == fresh
    records["paper/cpc/data/spec/spec-measurement-0.24.0-other.json"] = {
        "supersedes": stale
    }
    try:
        module.resolve_measurement(records, stale)
    except module.MeasurementSchemaError as exc:
        assert "superseded by" in str(exc)
        assert stray not in str(exc)
        return
    raise AssertionError("two on-chain successors were accepted")
