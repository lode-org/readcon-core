#!/usr/bin/env bash
# Pack one directory into a byte-stable gzip tarball.
#
# Usage: reproducible-tar.sh SOURCE_ROOT TAR_DIR ARCHIVE_NAME OUT_TGZ
# ARCHIVE_NAME is a directory inside TAR_DIR. OUT_TGZ ends in .tar.gz.
# Members are sorted by name, owned by uid 0, and dated SOURCE_DATE_EPOCH.
# gzip -n strips the header timestamp and original filename.
#
# The archive writer below does not delegate header or compression choices
# to the installed tar and gzip programs. This keeps bytes stable across
# their versions and implementations.
set -euo pipefail
# shellcheck source=scripts/scratch.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/scratch.sh"

if [[ $# -ne 4 ]]; then
    echo "usage: $0 SOURCE_ROOT TAR_DIR ARCHIVE_NAME OUT_TGZ" >&2
    exit 2
fi

SOURCE_ROOT="$1"
TAR_DIR="$2"
ARCHIVE_NAME="$3"
OUT="$4"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DATE_EPOCH="$(bash "$HERE/source-date-epoch.sh" "$SOURCE_ROOT")"
export SOURCE_DATE_EPOCH
if [[ ! "$SOURCE_DATE_EPOCH" =~ ^[0-9]+$ ]]; then
    echo "reproducible-tar: SOURCE_DATE_EPOCH must be seconds since the epoch" >&2
    exit 1
fi

tar_path="${OUT%.gz}"
if [[ "$tar_path" == "$OUT" ]]; then
    echo "reproducible-tar: $OUT must end in .gz" >&2
    exit 2
fi

archive_root="$TAR_DIR/$ARCHIVE_NAME"
if [[ ! -d "$archive_root" ]]; then
    echo "reproducible-tar: $TAR_DIR/$ARCHIVE_NAME is not a directory" >&2
    exit 1
fi

# Write GNU-format headers in sorted order with fixed ownership, modes, and
# timestamps. Gzip mtime zero and an empty filename are equivalent to -n.
python3 - "$archive_root" "$ARCHIVE_NAME" "$OUT" "$SOURCE_DATE_EPOCH" <<'PY'
import gzip
import sys
import tarfile
from pathlib import Path

root = Path(sys.argv[1])
archive_name = sys.argv[2]
output = Path(sys.argv[3])
epoch = int(sys.argv[4])
shared_suffixes = (".dll", ".dylib", ".so")

paths = [root, *sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix())]
with output.open("wb") as raw:
    with gzip.GzipFile(
        filename="", mode="wb", compresslevel=9, fileobj=raw, mtime=0
    ) as compressed:
        with tarfile.open(
            fileobj=compressed, mode="w|", format=tarfile.GNU_FORMAT
        ) as archive:
            for path in paths:
                relative = path.relative_to(root)
                name = archive_name
                if relative.parts:
                    name += "/" + relative.as_posix()
                info = archive.gettarinfo(str(path), arcname=name)
                info.uid = 0
                info.gid = 0
                info.uname = ""
                info.gname = ""
                info.mtime = epoch
                info.pax_headers = {}
                if info.isdir():
                    info.mode = 0o755
                elif info.issym():
                    info.mode = 0o777
                elif info.isfile():
                    executable = path.name.endswith(shared_suffixes) or ".so." in path.name
                    info.mode = 0o755 if executable else 0o644
                else:
                    raise SystemExit(f"reproducible-tar: unsupported member {name}")
                if info.isfile():
                    with path.open("rb") as stream:
                        archive.addfile(info, stream)
                else:
                    archive.addfile(info)
PY
