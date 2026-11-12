#!/usr/bin/env bash
# Pack one directory into a byte-stable gzip tarball.
#
# Usage: reproducible-tar.sh SOURCE_ROOT TAR_DIR ARCHIVE_NAME OUT_TGZ
# ARCHIVE_NAME is a directory inside TAR_DIR. OUT_TGZ ends in .tar.gz.
# Members are sorted by name, owned by uid 0, and dated SOURCE_DATE_EPOCH.
# gzip -n strips the header timestamp and original filename.
#
# gtar, or a GNU tar, uses --sort=name. BSD tar rejects that flag, so the
# member list is sorted here and passed with --files-from. Two runs on the
# same tar produce the same bytes.
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

if [[ ! -d "$TAR_DIR/$ARCHIVE_NAME" ]]; then
    echo "reproducible-tar: $TAR_DIR/$ARCHIVE_NAME is not a directory" >&2
    exit 1
fi

# Stamp the staging tree. Some bsdtar builds have no --mtime flag; the
# header time is then the file mtime, which has to already be the epoch.
python3 - "$SOURCE_DATE_EPOCH" "$TAR_DIR/$ARCHIVE_NAME" <<'PY'
import os
import sys

epoch = int(sys.argv[1])
root = sys.argv[2]


def stamp(path):
    try:
        os.utime(path, (epoch, epoch), follow_symlinks=False)
    except NotImplementedError:
        if not os.path.islink(path):
            os.utime(path, (epoch, epoch))


for dirpath, dirnames, filenames in os.walk(root, topdown=False, followlinks=False):
    for name in dirnames + filenames:
        stamp(os.path.join(dirpath, name))
    stamp(dirpath)
PY

is_gnu() {
    # grep -q can SIGPIPE tar and, with pipefail, hide a GNU tar.
    "$1" --version 2>&1 | grep 'GNU tar' >/dev/null
}

TAR_BIN=""
if command -v gtar >/dev/null 2>&1 && is_gnu gtar; then
    TAR_BIN="gtar"
elif is_gnu tar; then
    TAR_BIN="tar"
fi

if [[ -n "$TAR_BIN" ]]; then
    "$TAR_BIN" -C "$TAR_DIR" \
        --sort=name \
        --mtime="@${SOURCE_DATE_EPOCH}" \
        --owner=0 --group=0 --numeric-owner \
        -cf "$tar_path" \
        "$ARCHIVE_NAME"
else
    list="$(mktemp)"
    (
        cd "$TAR_DIR"
        find "$ARCHIVE_NAME" -print | LC_ALL=C sort
    ) > "$list"
    # macOS bsdtar accepts --mtime. The libarchive build in some Linux
    # packages does not; the tree was stamped above either way.
    mtime_args=()
    if tar --mtime "@${SOURCE_DATE_EPOCH}" -cf /dev/null --files-from /dev/null >/dev/null 2>&1; then
        mtime_args=(--mtime "@${SOURCE_DATE_EPOCH}")
    fi
    # gnutar format keeps long vendor paths. ustar cannot.
    # An empty "${mtime_args[@]}" is an unbound variable on bash 3.2.
    if [[ ${#mtime_args[@]} -gt 0 ]]; then
        tar -C "$TAR_DIR" \
            --format gnutar \
            --no-recursion \
            "${mtime_args[@]}" \
            --uid 0 --gid 0 \
            --uname root --gname root \
            -cf "$tar_path" \
            --files-from "$list"
    else
        tar -C "$TAR_DIR" \
            --format gnutar \
            --no-recursion \
            --uid 0 --gid 0 \
            --uname root --gname root \
            -cf "$tar_path" \
            --files-from "$list"
    fi
    rm -f "$list"
fi

gzip -n -9 "$tar_path"
