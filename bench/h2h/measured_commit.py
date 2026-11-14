"""Measure only a clean ``HEAD`` that a remote branch already contains.

Pushes re-stamp commits, so a local SHA never exists upstream. The guard
is ``git branch -r --contains HEAD`` plus a clean index and worktree.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path


def tracked_changes(porcelain: str) -> list[str]:
    """Tracked modifications. Untracked files are not part of ``git diff``."""
    found = []
    for line in porcelain.splitlines():
        if len(line) < 4 or line.startswith("??"):
            continue
        found.append(line)
    return found


def require_clean(porcelain: str) -> None:
    dirty = tracked_changes(porcelain)
    if dirty:
        raise SystemExit(
            "dirty tree; commit tracked changes before measuring:\n" + "\n".join(dirty)
        )


def require_published(head: str, remote_contains: str) -> list[str]:
    """Branches from ``git branch -r --contains HEAD``. Empty means refuse."""
    branches = [
        line.strip()
        for line in remote_contains.splitlines()
        if line.strip().startswith("origin/")
    ]
    if not branches:
        raise SystemExit(
            f"{head} is not on a remote branch; git branch -r --contains HEAD is empty"
        )
    return branches


def _git(root: Path, *args: str, binary: bool = False) -> str | bytes:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise SystemExit(completed.stderr.decode() or f"git {' '.join(args)} failed")
    if binary:
        return completed.stdout
    return completed.stdout.decode()


def measurement(root: Path) -> dict[str, str]:
    """HEAD when a remote branch contains it and the tree is clean."""
    porcelain = _git(root, "status", "--porcelain", "--untracked-files=no")
    require_clean(str(porcelain))
    head = str(_git(root, "rev-parse", "HEAD")).strip()
    listed = _git(root, "branch", "-r", "--contains", head)
    branches = require_published(head, str(listed))
    return {
        "commit": head,
        "tree": str(_git(root, "rev-parse", f"{head}^{{tree}}")).strip(),
        "diff_sha256": hashlib.sha256(b"").hexdigest(),
        "remote": branches[0],
    }


def record_path(path: Path, root: Path) -> str:
    """A repo-relative path, or ``shm/...`` for a memory file."""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        pass
    memory = Path("/dev/shm")
    try:
        return "shm/" + path.resolve().relative_to(memory.resolve()).as_posix()
    except ValueError:
        return path.name
