"""Every tag and commit the paper names is an object in this repository.

A shallow checkout has no tags. The assertions that call git skip then.
A job that fetches the full history and the tags runs them.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
from pathlib import Path

import pytest

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


def _tags() -> list[str]:
    listed = _git("tag", "-l", "v[0-9]*")
    return [line.strip() for line in listed.stdout.splitlines() if line.strip()]


def test_named_commits_and_tags_exist() -> None:
    macros = _macros()
    assert macros["readconversion"] == r"\readconCargoVersion"
    assert "v0.17.4" not in (CPC / "release.tex").read_text(encoding="utf-8")
    if not _tags():
        pytest.skip("this clone has no release tags")
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


def test_shipped_spec_blob_is_this_tree() -> None:
    macros = _macros()
    blob = _git("hash-object", "docs/orgmode/spec.org")
    assert blob.returncode == 0
    assert blob.stdout.strip().startswith(macros["rcReleaseSpecBlob"])
    supp = (CPC / "rg_supp.tex").read_text(encoding="utf-8")
    assert r"\rcReleaseSpecBlob" in supp
    assert r"\rcMeasuredSpecBlob" in supp


def test_measured_commit_matches_its_cargo_and_spec() -> None:
    macros = _macros()
    commit = macros["readconcommit"]
    if _git("cat-file", "-e", f"{commit}^{{commit}}").returncode != 0:
        pytest.skip("the named commit is not in this clone")
    show = _git("show", f"{commit}:Cargo.toml")
    found = re.search(r'^version = "([^"]+)"', show.stdout, re.M)
    assert found is not None
    assert found.group(1) == macros["rcMeasuredVersion"]
    spec = _git("rev-parse", f"{commit}:docs/orgmode/spec.org")
    assert spec.returncode == 0
    assert spec.stdout.strip().startswith(macros["rcMeasuredSpecBlob"])
    assert macros["rcMeasuredSpecBlob"] != macros["rcReleaseSpecBlob"]


def test_recorded_tags_match_git() -> None:
    if not _tags():
        pytest.skip("this clone has no release tags")
    spec = importlib.util.spec_from_file_location(
        "measured_versions",
        ROOT / "paper" / "cpc" / "scripts" / "measured_versions.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    version, commit = module.latest_tag()
    newest = ""
    listed = _git("tag", "-l", "v[0-9]*", "--sort=-v:refname")
    for line in listed.stdout.splitlines():
        if re.fullmatch(r"v\d+\.\d+\.\d+", line.strip()):
            newest = line.strip()
            break
    assert newest == f"v{version}"
    peeled = _git("rev-parse", f"refs/tags/v{version}^{{}}")
    assert peeled.returncode == 0
    assert peeled.stdout.strip() == commit
    release = module.release_version()
    tagged = _git("rev-parse", f"refs/tags/v{release}^{{}}")
    assert tagged.returncode == 0
    log = (ROOT / "paper" / "cpc" / "logs" / "reader-exchange.log").read_text(
        encoding="utf-8"
    )
    named = next(
        line.split()[1]
        for line in log.splitlines()
        if line.startswith("release_commit ")
    )
    assert tagged.stdout.strip() == named
