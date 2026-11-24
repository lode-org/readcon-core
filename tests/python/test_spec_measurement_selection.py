"""Specification generation uses only a measurement of the current spec."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "paper" / "cpc" / "scripts" / "gen_spec_supp.py"


def _load():
    spec = importlib.util.spec_from_file_location(
        "gen_spec_supp_measurement_under_test", SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_a_stale_measurement_is_not_a_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load()
    data = tmp_path / "spec"
    data.mkdir()
    version = "9.9.9"
    current_blob = "ab" * 20
    base = data / f"spec-measurement-{version}.json"
    base.write_text(
        json.dumps({"tree": {"spec_blob": "cd" * 20}}), encoding="utf-8"
    )
    legacy = data / "versions.json"
    legacy.write_text(
        json.dumps({"tree": {"spec_blob": current_blob}}), encoding="utf-8"
    )

    monkeypatch.setattr(module, "SPEC_DATA", data)
    monkeypatch.setattr(module, "VERSION", version)
    monkeypatch.setattr(module, "MEASUREMENT", base)
    monkeypatch.setattr(module, "LEGACY_VERSIONS", legacy)
    monkeypatch.setattr(module, "_spec_blob", lambda: current_blob)

    with pytest.raises(SystemExit, match=f"blob {current_blob[:8]}"):
        module.active_versions_file()
