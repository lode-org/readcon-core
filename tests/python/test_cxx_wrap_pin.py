"""Structural cxx wrap pin errors are never stale-pin warnings."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PIN = ROOT / "packaging" / "wrapdb" / "readcon-core.sha256"
WRAP = ROOT / "packaging" / "wrapdb" / "readcon-core.wrap"
CHECK = ROOT / "scripts" / "check_cxx_wrap_pin.sh"


def run_check(mode: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(CHECK), mode],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("mode", ["--pull-request", "--strict"])
def test_malformed_pin_fails_before_packaging(mode: str):
    original = PIN.read_text(encoding="utf-8")
    PIN.write_text(original.rstrip() + "0\n", encoding="utf-8")
    try:
        result = run_check(mode)
    finally:
        PIN.write_text(original, encoding="utf-8")

    assert result.returncode == 1
    assert "not a 64-character sha256" in result.stderr
    assert "Packaging readcon-core" not in result.stdout + result.stderr


@pytest.mark.parametrize("mode", ["--pull-request", "--strict"])
def test_wrap_sidecar_mismatch_fails_before_packaging(mode: str):
    original = WRAP.read_text(encoding="utf-8")
    changed, count = re.subn(
        r"(?m)^(source_hash\s*=\s*)(?:sha256:)?[0-9a-f]{64}$",
        rf"\g<1>{'0' * 64}",
        original,
    )
    assert count == 1
    WRAP.write_text(changed, encoding="utf-8")
    try:
        result = run_check(mode)
    finally:
        WRAP.write_text(original, encoding="utf-8")

    assert result.returncode == 1
    assert "wrap hash" in result.stderr
    assert "sidecar" in result.stderr
    assert "Packaging readcon-core" not in result.stdout + result.stderr
