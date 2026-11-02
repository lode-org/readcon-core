"""Heading capture keeps a pre-release suffix."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from version_sot import VERSION_PATTERN, accept_version, changelog_headings, heading_re


def test_prerelease_suffix_survives_the_heading_check():
    accept_version("1.0.0-rc1")
    text = "## v1.0.0-rc1 - 2026-11-02\n## v9.9.9 - 2026-10-31\n"
    assert changelog_headings(text) == ["v1.0.0-rc1", "v9.9.9"]
    assert heading_re().pattern == rf"(?m)^## (v{VERSION_PATTERN})\b"
