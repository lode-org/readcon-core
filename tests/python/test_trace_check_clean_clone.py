"""``trace_numbers.py --check`` on a clean clone.

``paper/cpc/data/trace/`` and the ``src/figures/generated/`` fragments the
manuscript inputs are gitignored, so a fresh checkout has neither. ``--check``
must build the ledger and the missing fragments it needs, and write no tracked
file.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "paper" / "cpc" / "scripts" / "trace_numbers.py"
LEDGER = ROOT / "paper" / "cpc" / "data" / "trace" / "numbers.csv"

CPC = Path("paper") / "cpc"
GENERATED = CPC / "src" / "figures" / "generated"
IDENTITY = ("-c", "user.name=trace test", "-c", "user.email=trace@test.invalid")


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


def _listed(*flags: str) -> list[str]:
    out = _git(ROOT, "ls-files", "-z", *flags)
    return [name for name in out.split("\0") if name]


@pytest.fixture
def clone(tmp_path: Path) -> Path:
    """A clone of this checkout's commit, with the uncommitted changes of the working tree committed on top."""
    dst = tmp_path / "clone"
    _git(ROOT, "clone", "-q", "--local", str(ROOT), str(dst))
    _git(dst, "checkout", "-q", "--detach", _git(ROOT, "rev-parse", "HEAD").strip())
    changed = _listed("--modified", "--others", "--exclude-standard")
    removed = _listed("--deleted")
    for name in changed:
        if (ROOT / name).is_file():
            (dst / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, dst / name)
    for name in removed:
        (dst / name).unlink(missing_ok=True)
    if changed or removed:
        _git(dst, "add", "-A")
        _git(
            dst,
            *IDENTITY,
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.hooksPath=/dev/null",
            "commit",
            "-q",
            "-m",
            "working tree",
        )
    assert _git(dst, "status", "--porcelain") == ""
    return dst


def _check(
    clone: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(clone / CPC / "scripts" / "trace_numbers.py"), "--check"],
        cwd=clone,
        env={**os.environ, **(env or {})},
        capture_output=True,
        text=True,
        check=False,
    )


def _status(clone: Path) -> str:
    return _git(clone, "status", "--porcelain")


def test_check_builds_the_ledger_on_a_clean_tree() -> None:
    had_ledger = LEDGER.is_file()
    backup = LEDGER.read_bytes() if had_ledger else None
    if had_ledger:
        LEDGER.unlink()
    try:
        done = subprocess.run(
            [sys.executable, str(SCRIPT), "--check"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert done.returncode == 0, done.stdout + done.stderr
        assert "0 problems" in done.stdout, done.stdout
        assert LEDGER.is_file(), "--check did not build the missing ledger"
    finally:
        if backup is not None:
            LEDGER.write_bytes(backup)


def test_check_on_a_clean_clone_writes_no_tracked_file(clone: Path) -> None:
    done = _check(clone)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "0 problems" in done.stdout, done.stdout
    assert (clone / CPC / "data" / "trace" / "numbers.csv").is_file()
    for name in ("sizes_macros.tex", "sizes_table.tex"):
        assert (clone / GENERATED / name).is_file(), name
    assert _status(clone) == "", _status(clone)


def test_check_writes_only_the_missing_fragments(clone: Path) -> None:
    first = _check(clone)
    assert first.returncode == 0, first.stdout + first.stderr
    generated = clone / GENERATED
    gone = ("sizes_macros.tex", "sizes_table.tex")
    for name in gone:
        (generated / name).unlink()
    before = {
        path.name: path.stat().st_mtime_ns
        for path in generated.iterdir()
        if path.is_file()
    }
    done = _check(clone)
    assert done.returncode == 0, done.stdout + done.stderr
    for name in gone:
        assert (generated / name).is_file(), name
    after = {
        path.name: path.stat().st_mtime_ns
        for path in generated.iterdir()
        if path.is_file()
    }
    assert {k: v for k, v in after.items() if k not in gone} == before
    assert _status(clone) == "", _status(clone)
