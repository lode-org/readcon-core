#!/usr/bin/env python3
"""Write src/release.tex from the commit that src/commit.tex names.

src/commit.tex holds one macro, ``\\readconcommit``, the measured
readcon-core commit the logs name.  Everything else of release.tex follows
from that commit's own Cargo.toml and the git history.  This checkout may be
a later tree.  The script stops unless

- the repository holds the commit,
- that commit's Cargo.toml names a dotted version, and
- the commit's ``docs/orgmode/spec.org`` blob can be hashed.

When a tag of that version names the commit, the role is a release commit
and the tag sentence names the tag.  Otherwise the role is a candidate
commit and the tag sentence says this commit is not a release tag.
``\\rcMeasuredVersion`` is that Cargo.toml version.  ``\\rcMeasuredSpecBlob``
is the commit's spec.org blob.
``\\readconpbccommit`` (per-axis periodic flags in the Python binding) and
``\\readconrcidxcommit`` (the ``.rcidx`` sidecar, pull request
``\\readconrcidxpr``) are commits of main before d0b7d3c7; their pull request
numbers are read from the commit subjects, and that of d0b7d3c7, whose subject
names none, is ``BASE_PR``.

    python paper/cpc/scripts/gen_release.py           # write src/release.tex
    python paper/cpc/scripts/gen_release.py --check   # exit 1 unless src/release.tex is current
    python paper/cpc/scripts/gen_release.py --commit  # print the commit of src/commit.tex, check nothing
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import provenance  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
COMMIT_TEX = ROOT / "src" / "commit.tex"
OUT = ROOT / "src" / "release.tex"
COMMIT_MACRO = re.compile(r"^\\newcommand\{\\readconcommit\}\{([0-9a-f]{40})\}$", re.M)
BASE = "d0b7d3c7a5a7e7d7a6a963d515e9524c575c09fd"
BASE_PR = "80"
PBC = "458001db49c8b0f3f3a0c47c2388bad4bf75f68c"
RCIDX = "593f8375303f7fff27a5fc0d823cfefc808289b2"


def git(*args: str) -> str | None:
    out = subprocess.run(
        ["git", "-C", str(provenance.REPO), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return out.stdout.strip() if out.returncode == 0 else None


def pull_request(subject: str) -> str:
    found = re.search(r"\(#(\d+)\)$", subject or "")
    if not found:
        raise SystemExit(f"the subject {subject!r} names no pull request")
    return found.group(1)


def published() -> tuple[str, str]:
    """The version and commit of the newest release tag of main before BASE."""
    tag = git("describe", "--tags", "--abbrev=0", "--match", "v[0-9]*", BASE)
    commit = tag and git("rev-parse", f"refs/tags/{tag}^{{commit}}")
    if not commit:
        raise SystemExit(f"no release tag is an ancestor of {BASE[:12]}")
    return tag.removeprefix("v"), commit


def named_commit() -> str:
    """The one commit src/commit.tex names."""
    found = COMMIT_MACRO.findall(COMMIT_TEX.read_text()) if COMMIT_TEX.is_file() else []
    if len(found) != 1:
        raise SystemExit(
            f"src/commit.tex defines \\readconcommit {len(found)} times as 40 hexadecimal digits, not once"
        )
    return found[0]


def identity() -> dict:
    """The commit of src/commit.tex with the version and spec blob of that commit."""
    commit = named_commit()
    if git("cat-file", "-e", f"{commit}^{{commit}}") is None:
        raise SystemExit(
            f"src/commit.tex names {commit}, which this repository does not hold"
        )
    cargo = git("show", f"{commit}:Cargo.toml") or ""
    found = re.search(r'^version = "([^"]+)"', cargo, re.M)
    if not found:
        raise SystemExit(f"Cargo.toml of commit {commit[:12]} names no version")
    version = found.group(1)
    digest = provenance.library_digest_at(commit)
    if not digest:
        raise SystemExit(f"commit {commit[:12]} has no library digest")
    spec = git("rev-parse", f"{commit}:docs/orgmode/spec.org")
    if not spec:
        raise SystemExit(f"commit {commit[:12]} has no docs/orgmode/spec.org")
    shipped, shipped_commit = published()
    tag = f"v{version}"
    tagged = git("rev-parse", "-q", "--verify", f"refs/tags/{tag}^{{commit}}")
    if tagged == commit:
        role = "release commit"
        tagstate = f"Tag {tag} names this commit."
    else:
        role = "candidate commit"
        tagstate = "This commit is not a release tag."
    return {
        "commit": commit,
        "digest": digest,
        "version": version,
        "role": role,
        "tagstate": tagstate,
        "spec_blob": spec[:8],
        "published": shipped,
        "published_commit": shipped_commit,
    }


def render() -> str:
    found = identity()
    commit, version = found["commit"], found["version"]
    values = {
        "readconversion": version,
        "rcMeasuredVersion": version,
        "rcMeasuredSpecBlob": found["spec_blob"],
        "readconcommitshort": commit[:8],
        "readconcommitrole": found["role"],
        "readcontagstate": found["tagstate"],
        "readcondigest": found["digest"][:12],
        "readconbase": BASE[:8],
        "readconbasepr": BASE_PR,
        "readconpublished": found["published"],
        "readconpublishedcommit": found["published_commit"][:8],
        "readconpbccommit": PBC[:7],
        "readconrcidxcommit": RCIDX[:7],
        "readconrcidxpr": pull_request(git("log", "-1", "--format=%s", RCIDX)),
    }
    return (
        "% Written by paper/cpc/scripts/gen_release.py from src/commit.tex, Cargo.toml and the git history.\n"
        + "".join(
            f"\\newcommand{{\\{name}}}{{{value}}}\n" for name, value in values.items()
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 unless src/release.tex is what this writes",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="print the commit of src/commit.tex and check nothing",
    )
    args = parser.parse_args()
    if args.commit:
        print(named_commit())
        return 0
    text = render()
    commit = named_commit()
    if args.check:
        if not OUT.is_file() or OUT.read_text() != text:
            print(
                "src/release.tex differs from src/commit.tex and the tree; run scripts/gen_release.py"
            )
            return 1
        print(
            f"src/release.tex is current for commit {commit[:12]}, library {provenance.library_digest()[:12]}"
        )
        return 0
    OUT.write_text(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
