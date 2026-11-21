"""The weak-scaling figure reads the limiter-r15 record and no other file."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "paper" / "cpc" / "scripts" / "plot_restored.py"


def _load():
    spec = importlib.util.spec_from_file_location("plot_restored", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_missing_weak_record_stops_the_build(tmp_path, monkeypatch) -> None:
    module = _load()
    monkeypatch.setattr(module, "LIMITER", tmp_path / "limiter-r15")
    with pytest.raises(SystemExit, match="no other record"):
        module.weak_figure()


def test_open_only_is_not_drawn_without_touch(tmp_path, monkeypatch) -> None:
    module = _load()
    record = tmp_path / "limiter-r15"
    record.mkdir()
    (record / "limiter-r15.json").write_text("{}\n")
    (record / "measure.txt").write_text("before open-only workers=1 sample_s=1\n")
    provenance = {
        "workers": [1, 2, 4, 8],
        "files": {
            "limiter-r15.json": module._sha256(record / "limiter-r15.json"),
            "measure.txt": module._sha256(record / "measure.txt"),
        },
    }
    (record / "provenance.json").write_text(json.dumps(provenance))
    monkeypatch.setattr(module, "LIMITER", record)
    monkeypatch.setattr(module, "save", lambda *_args: pytest.fail("save was called"))
    with pytest.raises(SystemExit, match="no touch samples"):
        module.weak_figure()


def test_a_missing_reads_record_stops_the_build(tmp_path, monkeypatch) -> None:
    module = _load()
    monkeypatch.delenv("READS_JSON", raising=False)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    with pytest.raises(SystemExit, match="no other reads record"):
        module._reads_path()
