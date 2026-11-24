"""The spec measurement names a commit whose VERSION and spec.org it measured.

A release bump that leaves ``docs/orgmode/spec.org`` alone still moves the
measured commit, so ``check_branch_green_history.sh`` finds the recorded
release in ``<commit>:VERSION``.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IDENTITY = (
    "-c",
    "user.name=spec test",
    "-c",
    "user.email=spec@test.invalid",
    "-c",
    "commit.gpgsign=false",
    "-c",
    "core.hooksPath=/dev/null",
)


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(cwd), *IDENTITY, *args],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


def test_a_release_bump_without_a_spec_edit_measures_the_bump(tmp_path: Path) -> None:
    clone = tmp_path / "clone"
    _git(ROOT, "clone", "-q", "--local", str(ROOT), str(clone))
    _git(clone, "checkout", "-q", "--detach", _git(ROOT, "rev-parse", "HEAD").strip())
    changed = _git(
        ROOT, "ls-files", "-z", "--modified", "--others", "--exclude-standard"
    )
    for name in filter(None, changed.split("\0")):
        if (ROOT / name).is_file():
            (clone / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, clone / name)
    if _git(clone, "status", "--porcelain"):
        _git(clone, "add", "-A")
        _git(clone, "commit", "-q", "-m", "working tree")

    old = (clone / "VERSION").read_text().strip()
    major, minor, patch = map(int, old.split("."))
    new = f"{major}.{minor}.{patch + 1}"
    (clone / "VERSION").write_text(new + "\n")
    cargo = clone / "Cargo.toml"
    cargo.write_text(
        re.sub(
            r'^version = "[^"]+"',
            f'version = "{new}"',
            cargo.read_text(),
            count=1,
            flags=re.MULTILINE,
        )
    )
    _git(clone, "commit", "-q", "-am", "bump the release")

    measured = subprocess.run(
        [sys.executable, "paper/cpc/scripts/gen_spec_supp.py", "--measure"],
        cwd=clone,
        capture_output=True,
        text=True,
        check=False,
    )
    assert measured.returncode == 0, measured.stdout + measured.stderr
    _git(clone, "add", "paper/cpc/data/spec")
    _git(clone, "commit", "-q", "-m", "measure the release")

    checked = subprocess.run(
        ["bash", "scripts/check_branch_green_history.sh", "HEAD~2", "HEAD"],
        cwd=clone,
        env={**os.environ, "READCON_HISTORY_RECORDS_ONLY": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert f"spec-measurement-{new}" in checked.stdout, checked.stdout
