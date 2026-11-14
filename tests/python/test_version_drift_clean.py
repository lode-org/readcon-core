"""version_drift.json is written only from a clean published checkout."""

from __future__ import annotations

import importlib.util
import subprocess
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
