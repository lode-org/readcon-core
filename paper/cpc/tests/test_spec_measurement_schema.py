"""A new spec measurement must name measured_at.commit."""

from __future__ import annotations

import importlib.util
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
