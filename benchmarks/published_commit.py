"""Refuse a result whose commit is not a clean published HEAD.

Tables name the commit that was measured. A dirty worktree, a short id,
or a commit that is not on the upstream remote is not that measurement.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )


def require_published(sha: str, root: Path | None = None) -> str:
    """Return `sha` when it is a full id reachable from an upstream ref."""
    root = root or Path(__file__).resolve().parents[1]
    commit = sha.strip().lower()
    if len(commit) != 40 or any(char not in "0123456789abcdef" for char in commit):
        raise SystemExit(f"refusing {sha}: commit ids are 40 hex characters")
    contained = _git(root, "branch", "-r", "--contains", commit)
    if contained.returncode != 0 or not contained.stdout.strip():
        raise SystemExit(f"refusing {commit}: it is not on the upstream remote")
    head = _git(root, "rev-parse", "HEAD")
    if head.returncode != 0:
        raise SystemExit("refusing to record: HEAD is not a commit")
    if head.stdout.strip() == commit:
        dirty = _git(root, "status", "--porcelain")
        if dirty.stdout.strip():
            raise SystemExit(f"refusing {commit}: the worktree is not clean")
    return commit
