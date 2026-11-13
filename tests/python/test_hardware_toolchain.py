"""A fresh hardware.json names the kernel and the compilers that built it."""

from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bench" / "h2h"))

import scale_r6  # noqa: E402


def _first_line(argv: list[str]) -> str:
    text = subprocess.check_output(argv, text=True, stderr=subprocess.STDOUT)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[0] if lines else ""


def test_toolchain_versions_match_this_machine():
    got = scale_r6.toolchain_versions()
    assert got["kernel"] == platform.release()
    assert (
        got["rustc"]
        == subprocess.check_output(["rustc", "--version"], text=True).strip()
    )
    assert got["gxx"] == _first_line(["g++", "--version"])
    assert got["gfortran"] == _first_line(["gfortran", "--version"])
    assert got["python"] == platform.python_version()


def test_both_hardware_writers_record_the_toolchain():
    scale = (ROOT / "bench" / "h2h" / "scale_r6.py").read_text(encoding="utf-8")
    campaign = (ROOT / "bench" / "h2h" / "final_campaign.py").read_text(
        encoding="utf-8"
    )
    assert "info.update(toolchain_versions())" in scale
    assert "**scale.toolchain_versions()" in campaign
