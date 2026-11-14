"""Measure only a clean ``HEAD`` that the remote already has.

Pushes re-stamp commits, so a local SHA never exists upstream. The guard
asks the remote with ``git ls-remote`` and refuses a readcon module that
was not built from that same commit or tree. Local ``origin/*`` refs are
not the check.
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


def remote_heads(ls_remote: str) -> list[tuple[str, str]]:
    """``git ls-remote --heads`` lines as ``(sha, refs/heads/...)``."""
    found = []
    for line in ls_remote.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        sha, ref = parts[0], parts[1]
        if len(sha) == 40 and ref.startswith("refs/heads/"):
            found.append((sha, ref))
    return found


def require_published(
    head: str,
    ls_remote: str,
    is_ancestor=None,
) -> list[str]:
    """Refs from ``git ls-remote`` whose tip is ``head`` or a descendant.

    ``is_ancestor(head, tip)`` is optional. Without it, only an exact tip
    match counts, so a local commit that is merely in the stale
    remote-tracking ref is refused.
    """
    refs = []
    for sha, ref in remote_heads(ls_remote):
        if sha == head or (is_ancestor is not None and is_ancestor(head, sha)):
            refs.append(ref)
    if not refs:
        raise SystemExit(
            f"{head} is not on a remote branch; git ls-remote did not list it"
        )
    return refs


def source_digest(root: Path) -> str:
    """SHA-256 of ``src/`` plus ``Cargo.lock``, in the order ``build.rs`` uses.

    A new commit that does not change those files is the same build. A module
    whose baked digest differs was not compiled from this tree.
    """
    paths = [path for path in (root / "src").rglob("*") if path.is_file()]
    lock = root / "Cargo.lock"
    if lock.is_file():
        paths.append(lock)
    paths.sort(key=lambda path: path.relative_to(root).as_posix())
    digest = hashlib.sha256()
    for path in paths:
        rel = path.relative_to(root).as_posix().encode()
        digest.update(rel)
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def require_built_from(
    head: str,
    tree: str,
    built_commit: str,
    built_tree: str,
    built_digest: str = "",
    source_digest: str = "",
) -> None:
    """Refuse an installed module that was not built from this tree.

    The source digest matches when ``src/`` and ``Cargo.lock`` match, even
    after a re-stamp that only moves ``HEAD``. The git commit and tree are
    the fallback for a module that has no digest.
    """
    baked = (built_digest or "").strip()
    current = (source_digest or "").strip()
    blank = {"", "unknown"}
    if baked not in blank and current not in blank and baked == current:
        return
    commit = (built_commit or "").strip()
    built = (built_tree or "").strip()
    if (commit not in blank and commit == head) or (
        built not in blank and built == tree
    ):
        return
    raise SystemExit(
        "installed readcon was not built from HEAD "
        f"{head} (module commit {commit or 'missing'}, "
        f"tree {built or 'missing'})"
    )


def refuse_stale_build(root: Path) -> dict[str, str]:
    """``measurement`` plus ``require_built_from`` for the imported module."""
    ident = measurement(root)
    import readcon

    require_built_from(
        ident["commit"],
        ident["tree"],
        str(getattr(readcon, "__commit__", "")),
        str(getattr(readcon, "__tree__", "")),
        str(getattr(readcon, "__source_digest__", "")),
        source_digest(root),
    )
    return ident


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


def _ancestor(root: Path, head: str, tip: str) -> bool:
    if head == tip:
        return True
    completed = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", head, tip],
        check=False,
        capture_output=True,
    )
    return completed.returncode == 0


def measurement(root: Path) -> dict[str, str]:
    """HEAD when ``git ls-remote`` shows it on the remote and the tree is clean."""
    porcelain = _git(root, "status", "--porcelain", "--untracked-files=no")
    require_clean(str(porcelain))
    head = str(_git(root, "rev-parse", "HEAD")).strip()
    tree = str(_git(root, "rev-parse", f"{head}^{{tree}}")).strip()
    listed = _git(root, "ls-remote", "--heads", "origin")
    branches = require_published(
        head,
        str(listed),
        is_ancestor=lambda commit, tip: _ancestor(root, commit, tip),
    )
    return {
        "commit": head,
        "tree": tree,
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
