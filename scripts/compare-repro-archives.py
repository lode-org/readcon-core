#!/usr/bin/env python3
"""Fail when two archives of one commit do not have the same bytes.

A mismatch prints each sha256 and, for gzip tarballs, the member list
(mode, owner, mtime, size, content sha256) so a linker timestamp or a
tar header is visible in the log.
"""

from __future__ import annotations

import hashlib
import sys
import tarfile
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def members(path: Path) -> list[str]:
    lines: list[str] = []
    with tarfile.open(path, "r:gz") as archive:
        for info in archive.getmembers():
            content = "-"
            if info.isfile():
                extracted = archive.extractfile(info)
                payload = b"" if extracted is None else extracted.read()
                content = hashlib.sha256(payload).hexdigest()
            lines.append(
                f"{info.name} mode={oct(info.mode)} uid={info.uid} gid={info.gid} "
                f"uname={info.uname!r} gname={info.gname!r} mtime={info.mtime} "
                f"size={info.size} sha256={content} pax={info.pax_headers}"
            )
    return lines


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: compare-repro-archives.py FIRST SECOND", file=sys.stderr)
        return 2
    first = Path(argv[1])
    second = Path(argv[2])
    if not first.is_file() or not second.is_file():
        print(f"missing archive: {first} or {second}", file=sys.stderr)
        return 2
    left = sha256(first)
    right = sha256(second)
    print(f"{left}  {first}")
    print(f"{right}  {second}")
    if left == right:
        print("reproducible sha256 matches")
        return 0
    print("clib tarball sha256 differs across builds", file=sys.stderr)
    for path, digest in ((first, left), (second, right)):
        print(f"--- {path} {digest}", file=sys.stderr)
        try:
            for line in members(path):
                print(line, file=sys.stderr)
        except (tarfile.TarError, OSError) as exc:
            print(f"(not a gzip tarball: {exc})", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
