"""Version strings next to a measured number come from that number's record."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CPC = ROOT / "paper" / "cpc"
SCRIPT = CPC / "scripts" / "measured_versions.py"
VERSION = re.compile(r"\d+\.\d+\.\d+")


def _module():
    spec = importlib.util.spec_from_file_location("measured_versions", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _macro(name: str, text: str) -> str:
    found = re.search(rf"\\newcommand\{{\\{name}\}}{{([^}}]+)}}", text)
    assert found, name
    return found.group(1)


def test_generated_macros_match_the_records() -> None:
    module = _module()
    text = (CPC / "src" / "measured_versions.tex").read_text(encoding="utf-8")
    assert text == module.render()
    assert _macro("rcReleaseVersion", text) == module.release_version()
    assert _macro("rcDriftFourth", text) == module.drift_fourth()
    tag, commit = module.latest_tag()
    assert _macro("rcLatestTag", text) == tag
    assert _macro("rcLatestTagCommit", text) == commit
    cargo = _macro(
        "readconCargoVersion",
        (CPC / "src" / "cargo_version.tex").read_text(encoding="utf-8"),
    )
    assert cargo != _macro("rcReleaseVersion", text)
    assert cargo != tag


def test_render_refuses_a_record_with_no_version(tmp_path, monkeypatch) -> None:
    module = _module()
    bad = tmp_path / "latest_release.json"
    bad.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(module, "LATEST", bad)
    with pytest.raises(SystemExit):
        module.render()
    assert "unknown" not in (CPC / "src" / "measured_versions.tex").read_text(
        encoding="utf-8"
    )


def test_measured_sentences_quote_the_record() -> None:
    module = _module()
    drift = module.drift_record()
    assert drift is not None
    readers = list(drift["readers"])
    reported = drift["reported_versions"]
    main = (CPC / "src" / "rg_main.tex").read_text(encoding="utf-8")
    supp = (CPC / "src" / "rg_supp.tex").read_text(encoding="utf-8")
    watched = []
    for path, text in (("rg_main.tex", main), ("rg_supp.tex", supp)):
        for number, line in enumerate(text.splitlines(), 1):
            if any(
                token in line
                for token in (
                    r"\rcDriftFourth",
                    r"\rcReleaseVersion",
                    r"\rcLatestTag",
                    "published wheels",
                    "readcon wheels",
                )
            ):
                watched.append((path, number, line))
    assert watched
    allowed = set(readers) | set(reported.values())
    for path, number, line in watched:
        assert r"\readconCargoVersion" not in line, f"{path}:{number}"
        assert "12ca800b" not in line, f"{path}:{number}"
        for version in VERSION.findall(line):
            assert version in allowed, f"{path}:{number}: {version}"
    assert r"\rcLatestTagCommit" in main
    assert module.drift_fourth() == reported[readers[-1]]
