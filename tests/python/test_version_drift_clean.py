"""version_drift.json is written only from a clean published checkout."""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "paper" / "cpc" / "scripts" / "spec_version_drift.py"


def _module():
    spec = importlib.util.spec_from_file_location("spec_version_drift", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _crate_version() -> str:
    cargo = (ROOT / "Cargo.toml").read_text(encoding="utf-8")
    found = re.search(r'(?m)^version = "(\d+\.\d+\.\d+)"$', cargo)
    assert found is not None, "Cargo.toml has no package version"
    return found.group(1)


def test_a_dirty_checkout_is_refused(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "rgoswami@ieee.org")
    _git(tmp_path, "config", "user.name", "Rohit Goswami")
    (tmp_path / "note.txt").write_text("one\n", encoding="utf-8")
    _git(tmp_path, "add", "note.txt")
    _git(tmp_path, "commit", "-m", "note")
    (tmp_path / "note.txt").write_text("two\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="dirty"):
        _module().ensure_published_clean(tmp_path)


def test_a_missing_module_is_refused() -> None:
    with pytest.raises(SystemExit, match="not found"):
        _module().require_installed_module(None)


def test_a_stale_module_is_refused() -> None:
    with pytest.raises(SystemExit, match="older than"):
        _module().refuse_stale_module(["src/writer.rs", "src/python.rs"])


def test_seeded_reader_measurement_is_copied_verbatim(tmp_path: Path) -> None:
    module = _module()
    seeded = {
        "version": "0.17.3",
        "commit": "1111111111111111111111111111111111111111",
        "date": "2025-01-01T00:00:00+00:00",
        "module_sha256": "abcd",
    }
    record = {
        "readers": ["0.17.3"],
        "reported_versions": {"0.17.3": "0.17.3"},
        "reader_measurements": {"0.17.3": seeded},
        "sources": {"0.17.3": {"module_sha256": "abcd"}},
        "probe_text": module.PROBES,
        "probes": {
            name: {"0.17.3": {"verdict": "accept", "frames": 1}}
            for name in module.PROBES
        },
    }
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps(record), encoding="utf-8")
    _, _, _, measurements = module.seed_from_record(seed)
    assert measurements["0.17.3"] == seeded


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("version", "9.9.9"),
        ("commit", "2222222222222222222222222222222222222222"),
        ("date", "2035-12-31T00:00:00+00:00"),
        ("module_sha256", "ffff"),
    ],
)
def test_seeded_measurement_fields_are_preserved(
    tmp_path: Path, field: str, value: str
) -> None:
    module = _module()
    seeded = {
        "version": "0.17.3",
        "commit": "1111111111111111111111111111111111111111",
        "date": "2025-01-01T00:00:00+00:00",
        "module_sha256": "abcd",
    }
    record = {
        "readers": ["0.17.3"],
        "reported_versions": {"0.17.3": "0.17.3"},
        "reader_measurements": {"0.17.3": seeded},
        "sources": {"0.17.3": {"module_sha256": "abcd"}},
        "probe_text": module.PROBES,
        "probes": {
            name: {"0.17.3": {"verdict": "accept", "frames": 1}}
            for name in module.PROBES
        },
    }
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps(record), encoding="utf-8")
    _, _, _, measurements = module.seed_from_record(seed)
    assert measurements["0.17.3"][field] != value
    assert measurements["0.17.3"][field] == seeded[field]


def test_reader_dir_without_module_sha_is_refused(tmp_path: Path) -> None:
    crate_version = _crate_version()
    empty = tmp_path / "unpacked-wheel"
    (empty / "readcon").mkdir(parents=True)
    with pytest.raises(SystemExit, match="has no readcon\\*\\.so"):
        _module().reader_module_sha(empty, crate_version)


def test_seed_record_refuses_probe_text_hash_drift(tmp_path: Path) -> None:
    module = _module()
    record = {
        "readers": ["0.17.3"],
        "reported_versions": {"0.17.3": "0.17.3"},
        "reader_measurements": {"0.17.3": {"version": "0.17.3"}},
        "sources": {"0.17.3": {"module_sha256": "abcd"}},
        "probe_text": {**module.PROBES, "one frame, empty line 1": "mutated"},
        "probes": {
            name: {"0.17.3": {"verdict": "accept", "frames": 1}}
            for name in module.PROBES
        },
    }
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(
        SystemExit, match="probe_text\\['one frame, empty line 1'\\] drifted"
    ):
        module.seed_from_record(seed)


def test_seed_record_refuses_probe_name_drift(tmp_path: Path) -> None:
    module = _module()
    probes = {
        name: {"0.17.3": {"verdict": "accept", "frames": 1}}
        for name in module.PROBES
        if name != "one frame, empty line 1"
    }
    record = {
        "readers": ["0.17.3"],
        "reported_versions": {"0.17.3": "0.17.3"},
        "reader_measurements": {"0.17.3": {"version": "0.17.3"}},
        "sources": {"0.17.3": {"module_sha256": "abcd"}},
        "probe_text": module.PROBES,
        "probes": probes,
    }
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(SystemExit, match="probe names drift"):
        module.seed_from_record(seed)


def test_allow_unpublished_tip_flag_is_rejected() -> None:
    run = subprocess.run(
        [sys.executable, str(SCRIPT), "--allow-unpublished-tip"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 2
    assert "unrecognized arguments: --allow-unpublished-tip" in run.stderr
