#!/usr/bin/env python3
"""Write src/release.tex from the commit that src/commit.tex names.

src/commit.tex holds one macro, ``\\readconcommit``, the readcon-core commit
the paper describes; it is the one value to change when the release is
tagged.  Everything else of release.tex follows from that commit, the
version of Cargo.toml and the git history, and the script stops unless

- the repository holds the commit and HEAD has its tree, so every check that
  reads this checkout reads the files of that commit,
- the library files of the commit (``provenance.LIBRARY_PATHS``) are those of
  this working tree and the library that the build record of the timed run,
  ``bench/results/r0174/provenance.json``, names by ``library_digest``;
  check_manuscript.py holds every other record to that library, so a tag of
  other library files stops here instead of printing a digest no record names,
- the commit's Cargo.toml gives the version of this tree's Cargo.toml and its
  CHANGELOG.md has a section for that version,
- commit d0b7d3c7, the head of pull request ``\\readconbasepr`` to main, is an
  ancestor of the commit, and the newest release tag before it, the published
  release ``\\readconpublished`` at commit ``\\readconpublishedcommit``, is of
  another version, and
- no tag of that version names another commit.

``\\readcontagstate`` names the tag of that version, which names the commit
once the release is tagged.
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
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import provenance  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
COMMIT_TEX = ROOT / "src" / "commit.tex"
OUT = ROOT / "src" / "release.tex"
BUILD_RECORD = ROOT / "bench" / "results" / "r0174" / "provenance.json"
COMMIT_MACRO = re.compile(r"^\\newcommand\{\\readconcommit\}\{([0-9a-f]{40})\}$", re.M)
BASE = "d0b7d3c7a5a7e7d7a6a963d515e9524c575c09fd"
BASE_PR = "80"
PBC = "458001db49c8b0f3f3a0c47c2388bad4bf75f68c"
RCIDX = "593f8375303f7fff27a5fc0d823cfefc808289b2"


def git(*args: str) -> str | None:
    out = subprocess.run(["git", "-C", str(provenance.REPO), *args], capture_output=True, text=True, check=False)
    return out.stdout.strip() if out.returncode == 0 else None


def ancestor(older: str, newer: str) -> bool:
    return subprocess.run(["git", "-C", str(provenance.REPO), "merge-base", "--is-ancestor", older, newer],
                          capture_output=True, check=False).returncode == 0


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
        raise SystemExit(f"src/commit.tex defines \\readconcommit {len(found)} times as 40 hexadecimal digits, not once")
    return found[0]


def identity() -> dict:
    """The commit of src/commit.tex with its library digest and tag, after the checks of the module docstring."""
    commit = named_commit()
    if git("cat-file", "-e", f"{commit}^{{commit}}") is None:
        raise SystemExit(f"src/commit.tex names {commit}, which this repository does not hold")
    tree, head = git("rev-parse", f"{commit}^{{tree}}"), git("rev-parse", "HEAD^{tree}")
    if tree != head:
        raise SystemExit(f"HEAD has tree {(head or 'none')[:12]} and commit {commit[:12]} tree {tree[:12]}; "
                         f"build the paper in a checkout of {commit[:12]}")
    digest = provenance.library_digest()
    held = provenance.library_digest_at(commit)
    if held != digest:
        raise SystemExit(f"commit {commit[:12]} holds library {(held or 'none')[:12]}; this tree holds "
                         f"{digest[:12]}")
    recorded = json.loads(BUILD_RECORD.read_text())["build"]["library_digest"] if BUILD_RECORD.is_file() else None
    if recorded != digest:
        raise SystemExit(f"commit {commit[:12]} holds library {digest[:12]}; {BUILD_RECORD.relative_to(ROOT)} "
                         f"names {(recorded or 'none')[:12]}; other library files need a new run of every record")
    version = provenance.library_version()
    cargo = git("show", f"{commit}:Cargo.toml") or ""
    found = re.search(r'^version = "([^"]+)"', cargo, re.M)
    if not found or found.group(1) != version:
        raise SystemExit(f"commit {commit[:12]} is version {found and found.group(1)}; Cargo.toml is {version}")
    if not re.search(rf"^## v{re.escape(version)} ", git("show", f"{commit}:CHANGELOG.md") or "", re.M):
        raise SystemExit(f"CHANGELOG.md of commit {commit[:12]} has no section for v{version}")
    if not ancestor(BASE, commit):
        raise SystemExit(f"commit {BASE[:12]}, the head of pull request {BASE_PR}, is not an ancestor of {commit[:12]}")
    for older in (PBC, RCIDX):
        if not ancestor(older, BASE):
            raise SystemExit(f"commit {older[:12]} is not an ancestor of {BASE[:12]}")
    shipped, shipped_commit = published()
    if shipped == version:
        raise SystemExit(f"tag v{version} is an ancestor of {BASE[:12]}; the candidate needs a new version")
    tag = f"v{version}"
    tagged = git("rev-parse", "-q", "--verify", f"refs/tags/{tag}^{{commit}}")
    if tagged is not None and tagged != commit:
        raise SystemExit(f"tag {tag} names {tagged[:12]}; put that commit in src/commit.tex")
    return {"commit": commit, "digest": digest, "version": version, "tag": tag,
            "published": shipped, "published_commit": shipped_commit}


def render() -> str:
    found = identity()
    commit, version, tag = found["commit"], found["version"], found["tag"]
    values = {
        "readconversion": version,
        "readconcommitshort": commit[:8],
        "readconcommitrole": "release commit",
        "readcontagstate": f"Tag {tag} names this commit.",
        "readcondigest": found["digest"][:12],
        "readconbase": BASE[:8],
        "readconbasepr": BASE_PR,
        "readconpublished": found["published"],
        "readconpublishedcommit": found["published_commit"][:8],
        "readconpbccommit": PBC[:7],
        "readconrcidxcommit": RCIDX[:7],
        "readconrcidxpr": pull_request(git("log", "-1", "--format=%s", RCIDX)),
    }
    return ("% Written by paper/cpc/scripts/gen_release.py from src/commit.tex, Cargo.toml and the git history.\n"
            + "".join(f"\\newcommand{{\\{name}}}{{{value}}}\n" for name, value in values.items()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="exit 1 unless src/release.tex is what this writes")
    parser.add_argument("--commit", action="store_true", help="print the commit of src/commit.tex and check nothing")
    args = parser.parse_args()
    if args.commit:
        print(named_commit())
        return 0
    text = render()
    commit = named_commit()
    if args.check:
        if not OUT.is_file() or OUT.read_text() != text:
            print("src/release.tex differs from src/commit.tex and the tree; run scripts/gen_release.py")
            return 1
        print(f"src/release.tex is current for commit {commit[:12]}, library {provenance.library_digest()[:12]}")
        return 0
    OUT.write_text(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
