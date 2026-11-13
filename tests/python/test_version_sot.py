"""Heading capture keeps a pre-release suffix."""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from version_sot import (
    ROOT,
    VERSION_PATTERN,
    accept_version,
    changelog_headings,
    generated_targets,
    heading_re,
    read_version,
    render_wrap,
)


def test_prerelease_suffix_survives_the_heading_check():
    accept_version("1.0.0-rc1")
    text = "## v1.0.0-rc1 - 2026-11-02\n## v9.9.9 - 2026-10-31\n"
    assert changelog_headings(text) == ["v1.0.0-rc1", "v9.9.9"]
    assert heading_re().pattern == rf"(?m)^## (v{VERSION_PATTERN})\b"


def test_version_stamp_does_not_retarget_the_wrap():
    outs = [path for path, _src in generated_targets()]
    assert "packaging/wrapdb/readcon-core.wrap" not in outs


def test_render_wrap_matches_the_sidecar():
    wrap = ROOT / "packaging" / "wrapdb" / "readcon-core.wrap"
    assert render_wrap() == wrap.read_text(encoding="utf-8")


def test_render_wrap_refuses_to_keep_the_previous_digest():
    wrap = ROOT / "packaging" / "wrapdb" / "readcon-core.wrap"
    original = wrap.read_text(encoding="utf-8")
    current = read_version()
    major, minor, patch = current.split(".", 2)
    patch_num = re.match(r"\d+", patch)
    assert patch_num is not None
    other = f"{major}.{minor}.{int(patch_num.group(0)) + 1}"
    stale = original.replace(current, other)
    assert stale != original
    wrap.write_text(stale, encoding="utf-8")
    try:
        try:
            render_wrap()
        except SystemExit as exc:
            message = str(exc)
            assert other in message
            assert "record-cxx-wrap.sh" in message
        else:
            raise AssertionError("stale wrap was retargeted")
    finally:
        wrap.write_text(original, encoding="utf-8")


def test_version_sot_tests_do_not_embed_the_package_version():
    source = Path(__file__).read_text(encoding="utf-8")
    assert read_version() not in source
