"""A local clone of a detached HEAD keeps the source's origin refs."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MODULE = ROOT / "tests" / "python" / "test_trace_check_clean_clone.py"


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


def _helper():
    spec = importlib.util.spec_from_file_location("trace_clone", MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._keep_origin_refs


def test_a_detached_local_clone_keeps_origin_refs(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    _git(src, "init", "-q")
    _git(src, "config", "user.name", "origin test")
    _git(src, "config", "user.email", "origin@test.invalid")
    (src / "note").write_text("one\n")
    _git(src, "add", "note")
    _git(src, "commit", "-q", "-m", "one")
    _git(src, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(src, "checkout", "-q", "--detach", "HEAD")
    dst = tmp_path / "dst"
    _git(src, "clone", "-q", "--local", str(src), str(dst))
    before = _git(dst, "for-each-ref", "--format=%(refname)", "refs/remotes/origin")
    assert "refs/remotes/origin/main" not in before.split()
    _helper()(src, dst)
    _git(dst, "checkout", "-q", "--detach", "HEAD")
    copied = _git(dst, "for-each-ref", "--format=%(refname)", "refs/remotes/origin")
    assert "refs/remotes/origin/main" in copied.split()
    assert _git(dst, "rev-parse", "--abbrev-ref", "HEAD").strip() == "HEAD"
