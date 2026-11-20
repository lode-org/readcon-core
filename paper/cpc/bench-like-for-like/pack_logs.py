"""Pack raw logs and asv result JSON. Write a temporary archive, sync, then rename."""

from __future__ import annotations

import hashlib
import os
import sys
import tarfile
from pathlib import Path

BENCH = Path(__file__).resolve().parent
WORK = BENCH / "work"


def members() -> list[Path]:
    found = []
    for path in sorted(WORK.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(WORK).as_posix()
        if rel.startswith("target-") or rel.startswith("prefix-"):
            continue
        if rel.startswith("wheels-") or rel.endswith(".con") or rel.endswith(".whl"):
            continue
        if rel.startswith("asv-results/") or rel.startswith("asv-home/"):
            found.append(path)
            continue
        if path.suffix in {".log", ".json", ".txt"} or path.name.endswith(".stamp"):
            found.append(path)
    return found


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: pack_logs.py DEST.tar.gz")
    dest = Path(sys.argv[1])
    dest.parent.mkdir(parents=True, exist_ok=True)
    temporary = dest.with_name(dest.name + ".tmp")
    if temporary.exists():
        temporary.unlink()
    with tarfile.open(temporary, "w:gz") as archive:
        for path in members():
            archive.add(path, arcname=path.relative_to(BENCH).as_posix())
    fd = os.open(temporary, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temporary, dest)
    dir_fd = os.open(dest.parent, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
    digest = hashlib.sha256()
    with dest.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    print(digest.hexdigest())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
