#!/usr/bin/env bash
# Pack one directory into a byte-stable gzip tarball.
#
# Usage: reproducible-tar.sh SOURCE_ROOT TAR_DIR ARCHIVE_NAME OUT_TGZ
# ARCHIVE_NAME is a directory inside TAR_DIR. OUT_TGZ ends in .tar.gz.
# Members are sorted by name, owned by uid 0, and dated SOURCE_DATE_EPOCH.
# gzip -n strips the header timestamp and original filename.
set -euo pipefail

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

tar -C "$TAR_DIR" \
    --sort=name \
    --mtime="@${SOURCE_DATE_EPOCH}" \
    --owner=0 --group=0 --numeric-owner \
    -cf "$tar_path" \
    "$ARCHIVE_NAME"
gzip -n -9 "$tar_path"
