"""Every tag and commit the paper names is an object in this repository."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CPC = ROOT / "paper" / "cpc" / "src"
HEX = re.compile(r"(?<![0-9A-Za-z])[0-9a-f]{7,40}(?![0-9A-Za-z])")
TAG = re.compile(r"\bv(\d+\.\d+\.\d+)\b")
COMMAND = re.compile(r"\\newcommand\{\\([A-Za-z]+)\}\{([^{}]+)\}")
COMMIT_NAMES = (
    "readconcommit",
    "readconcommitshort",
    "readconpublishedcommit",
    "readconpbccommit",
    "readconrcidxcommit",
    "readconbase",
    "rcLatestTagCommit",
)


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _macros() -> dict[str, str]:
    found: dict[str, str] = {}
    for path in CPC.rglob("*.tex"):
        for name, value in COMMAND.findall(path.read_text(encoding="utf-8")):
            found[name] = value
    return found


def test_named_commits_and_tags_exist() -> None:
    macros = _macros()
    assert macros["readconversion"] == r"\readconCargoVersion"
    assert "v0.17.4" not in (CPC / "release.tex").read_text(encoding="utf-8")
    missing: list[str] = []
    for name in COMMIT_NAMES:
        value = macros[name]
        if _git("rev-parse", "--verify", f"{value}^{{commit}}").returncode != 0:
            missing.append(f"{name} {value}")
    full = HEX.findall((CPC / "rg_main.tex").read_text(encoding="utf-8"))
    full += HEX.findall((CPC / "commit.tex").read_text(encoding="utf-8"))
    for value in full:
        if len(value) < 40:
            continue
        if _git("cat-file", "-e", f"{value}^{{commit}}").returncode != 0:
            missing.append(value)
    tag = macros["rcLatestTag"]
    if _git("rev-parse", "--verify", f"refs/tags/v{tag}^{{}}").returncode != 0:
        missing.append(f"v{tag}")
    for text in (
        (CPC / "release.tex").read_text(encoding="utf-8"),
        (CPC / "rg_main.tex").read_text(encoding="utf-8"),
    ):
        for version in TAG.findall(text):
            if (
                _git("rev-parse", "--verify", f"refs/tags/v{version}^{{}}").returncode
                != 0
            ):
                missing.append(f"v{version}")
    assert not missing, missing
