#!/usr/bin/env python3
"""Refuse a tag publish whose tree or filenames are a different version.

The v0.18.0 GitHub Release received wheels named 0.17.3 because the tag
moved onto a tree whose package version was still 0.17.3, and the upload
step attached every downloaded artifact. This check fails unless VERSION,
the git tag, and every wheel, sdist, and cxx archive name are one version.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

VERSION_RE = re.compile(r"\d+\.\d+\.\d+")
PREFIXES = ("readcon-core-cxx-", "readcon_chemfiles-", "readcon-")


def tag_version(tag: str) -> str:
    if tag.startswith("refs/tags/"):
        tag = tag[len("refs/tags/") :]
    if not tag.startswith("v") or VERSION_RE.fullmatch(tag[1:]) is None:
        raise SystemExit(f"tag {tag!r} is not vX.Y.Z")
    return tag[1:]


def artifact_version(name: str) -> str:
    for prefix in PREFIXES:
        if not name.startswith(prefix):
            continue
        rest = name[len(prefix) :]
        match = VERSION_RE.match(rest)
        if match is None:
            break
        nxt = rest[match.end() : match.end() + 1]
        if nxt in {"", "-", "."}:
            return match.group(0)
    raise SystemExit(f"unrecognized release artifact name {name}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True)
    parser.add_argument("--version-file", default="VERSION")
    parser.add_argument("--dist", action="append", default=[])
    args = parser.parse_args()
    want = tag_version(args.tag)
    got = Path(args.version_file).read_text(encoding="utf-8").strip()
    if got != want:
        raise SystemExit(f"VERSION is {got}, tag asks for {want}")
    files: list[Path] = []
    for directory in args.dist:
        root = Path(directory)
        if not root.is_dir():
            raise SystemExit(f"missing artifact directory {directory}")
        files.extend(
            path
            for path in sorted(root.iterdir())
            if path.is_file() and path.suffix in {".whl", ".gz", ".sha256"}
        )
    if args.dist and not files:
        raise SystemExit("no release artifacts found")
    for path in files:
        found = artifact_version(path.name)
        if found != want:
            raise SystemExit(f"{path.name} is version {found}, tag asks for {want}")
        print(f"OK {path.name}")
    print(f"OK VERSION {got} tag v{want} files {len(files)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
