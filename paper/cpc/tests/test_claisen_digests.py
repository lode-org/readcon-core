"""The Claisen reproduction stops when the model or the export digest differs."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "paper" / "cpc" / "scripts" / "run_claisen_order.py"


def _load():
    spec = importlib.util.spec_from_file_location("run_claisen_order", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_model_or_export_digest_mismatch_stops(tmp_path, monkeypatch) -> None:
    module = _load()
    record = json.loads((module.DATA / "results.json").read_text(encoding="utf-8"))
    assert module.CKPT_SHA256 == record["potential"]["checkpoint_sha256"]
    assert module.PT_SHA256 == record["potential"]["torchscript_sha256"]

    bad_export = tmp_path / "pet.pt"
    bad_export.write_bytes(b"not-the-recorded-export")
    monkeypatch.setenv("CLAISEN_PT", str(bad_export))
    with pytest.raises(SystemExit, match="torchscript sha256"):
        module.ensure_model()

    monkeypatch.delenv("CLAISEN_PT")
    monkeypatch.setenv("CLAISEN_CKPT", str(tmp_path / "checkpoint.ckpt"))
    monkeypatch.setattr(module, "CACHE", tmp_path)
    (tmp_path / "checkpoint.ckpt").write_bytes(b"not-the-recorded-checkpoint")
    with pytest.raises(SystemExit, match="checkpoint sha256"):
        module.ensure_model()
