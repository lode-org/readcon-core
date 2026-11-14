"""Cite a commit that exists on the published branch.

A measurement names ``origin/feat/release-0.23.0`` when that commit is an
ancestor of HEAD, and the sha256 of ``git diff <that> HEAD``. A dirty
index or worktree is refused, because that diff would not describe the
bytes that ran.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

ORIGIN = "origin/feat/release-0.23.0"


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


def cite_from(head: str, base: str, on_origin, diff: bytes) -> dict[str, str]:
    """Name ``base`` when it is on origin, plus the sha256 of ``diff``."""
    if not on_origin(base):
        raise SystemExit(f"{base} is not on {ORIGIN}")
    payload = b"" if head == base else diff
    if head == base and on_origin(head):
        payload = b""
    return {
        "commit": base,
        "diff_sha256": hashlib.sha256(payload).hexdigest(),
    }


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


def origin_contains(root: Path, rev: str) -> bool:
    completed = subprocess.run(
        ["git", "-C", str(root), "branch", "-r", "--contains", rev],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return False
    return any(
        line.strip().startswith("origin/") for line in completed.stdout.splitlines()
    )


def measurement(root: Path) -> dict[str, str]:
    """The published commit and the diff that was actually run."""
    porcelain = _git(root, "status", "--porcelain", "--untracked-files=no")
    require_clean(str(porcelain))
    head = str(_git(root, "rev-parse", "HEAD")).strip()
    if origin_contains(root, head):
        base = head
        diff = b""
    else:
        base = str(_git(root, "merge-base", "HEAD", ORIGIN)).strip()
        diff = _git(root, "diff", base, "HEAD", binary=True)
        if not isinstance(diff, bytes):
            diff = diff.encode()
    info = cite_from(head, base, lambda rev: origin_contains(root, rev), diff)
    info["tree"] = str(_git(root, "rev-parse", f"{base}^{{tree}}")).strip()
    return info


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
