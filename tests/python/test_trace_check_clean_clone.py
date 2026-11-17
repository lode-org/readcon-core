"""``trace_numbers.py --check`` on a clean clone.

``paper/cpc/data/trace/`` and the ``src/figures/generated/`` fragments the
manuscript inputs are gitignored, so a fresh checkout has neither. ``--check``
must build the ledger and the missing fragments it needs, write no tracked
file, and fail on a number that the Org source of the manuscript prints
differently from the TeX it exports to.
"""

from __future__ import annotations

import importlib.util
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

BLOCK_ASE = """\
import importlib.abc
import sys


class BlockAse(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name == "ase" or name.startswith("ase."):
            raise ImportError("ase is blocked for this test")


sys.meta_path.insert(0, BlockAse())
"""


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


def _load_trace_numbers():
    spec = importlib.util.spec_from_file_location("trace_numbers_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _edit_first_org_number(clone: Path, name: str) -> int:
    """Change one printed number of ``name`` in the clone, and return its line."""
    trace = _load_trace_numbers()
    org = (clone / CPC / "src" / "rg_main.org").read_text().splitlines()
    start = trace._document_start(org, "rg_main.org")
    printed, _ = trace.scan_lines(name, list(enumerate(org, start=1))[start:])
    first = next(item for item in printed if item.text.isdigit() and len(item.text) > 1)
    path = clone / CPC / "src" / name
    lines = path.read_text().splitlines(keepends=True)
    index = first.line - 1 if name.endswith(".org") else None
    if index is None:
        index = next(i for i, line in enumerate(lines) if first.context in line)
    changed = first.text[:-1] + str((int(first.text[-1]) + 1) % 10)
    assert first.text in lines[index], (first.text, lines[index])
    lines[index] = lines[index].replace(first.text, changed, 1)
    path.write_text("".join(lines))
    return index + 1


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


@pytest.mark.parametrize("name", ["rg_main.org", "rg_main.tex"])
def test_check_fails_on_a_number_edited_in_one_source(clone: Path, name: str) -> None:
    line = _edit_first_org_number(clone, name)
    done = _check(clone)
    assert done.returncode != 0, done.stdout + done.stderr
    assert f"{name}:{line}:" in done.stdout, done.stdout


def test_check_fails_on_an_org_number_without_emacs(
    clone: Path, tmp_path: Path
) -> None:
    first = _check(clone)
    assert first.returncode == 0, first.stdout + first.stderr
    line = _edit_first_org_number(clone, "rg_main.org")
    bare = tmp_path / "bare"
    bare.mkdir()
    done = _check(clone, {"PATH": str(bare)})
    assert shutil.which("emacs", path=str(bare)) is None
    assert done.returncode != 0, done.stdout + done.stderr
    assert f"rg_main.org:{line}:" in done.stdout, done.stdout
    assert "rg_main.tex is not the Org export" not in done.stdout
    assert "emacs is not on PATH" in done.stderr, done.stderr


def test_check_fails_when_the_tex_is_not_the_org_export(clone: Path) -> None:
    assert shutil.which("emacs"), "emacs is required to export rg_main.org"
    tex = clone / CPC / "src" / "rg_main.tex"
    text = tex.read_text()
    assert "geometry checkpoint" in text
    tex.write_text(text.replace("geometry checkpoint", "geometry check-point", 1))
    done = _check(clone)
    assert done.returncode != 0, done.stdout + done.stderr
    assert "rg_main.tex is not the Org export of rg_main.org" in done.stdout


def test_check_needs_no_ase(clone: Path, tmp_path: Path) -> None:
    blocker = tmp_path / "blocker"
    blocker.mkdir()
    (blocker / "sitecustomize.py").write_text(BLOCK_ASE)
    inherited = os.environ.get("PYTHONPATH")
    env = {"PYTHONPATH": os.pathsep.join([p for p in (str(blocker), inherited) if p])}
    probe = subprocess.run(
        [sys.executable, "-c", "import ase"],
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        check=False,
    )
    assert probe.returncode != 0 and "ase is blocked" in probe.stderr, probe.stderr
    done = _check(clone, env)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "0 problems" in done.stdout, done.stdout
    assert "ModuleNotFoundError" not in done.stderr + done.stdout
    for name in ("spec_macros.tex", "versions_table.tex", "sizes_table.tex"):
        assert (clone / GENERATED / name).is_file(), name
    assert _status(clone) == "", _status(clone)
