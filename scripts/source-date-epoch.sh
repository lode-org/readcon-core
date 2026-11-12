#!/usr/bin/env bash
# Print the SOURCE_DATE_EPOCH for a reproducible archive of this tree.
#
# Resolution order:
#   1. A caller-supplied SOURCE_DATE_EPOCH (skipped with --fresh).
#   2. packaging/wrapdb/source-date-epoch, the pin from the last
#      record-cxx-wrap.sh run (skipped with --fresh).
#   3. The committer date of the v$VERSION tag, when that tag exists.
#   4. The committer date of HEAD.
#
# --fresh is how a release records a new pin. A later build of that
# commit reads the pin, so a new committer date cannot move the archive.
set -euo pipefail

fresh=0
if [[ "${1:-}" == "--fresh" ]]; then
    fresh=1
    shift
fi

ROOT="${1:-.}"

if [[ "$fresh" -eq 0 && -n "${SOURCE_DATE_EPOCH:-}" ]]; then
    printf '%s\n' "$SOURCE_DATE_EPOCH"
    exit 0
fi

pin="$ROOT/packaging/wrapdb/source-date-epoch"
if [[ "$fresh" -eq 0 && -f "$pin" ]]; then
    val="$(tr -d '[:space:]' < "$pin")"
    if [[ "$val" =~ ^[0-9]+$ ]]; then
        printf '%s\n' "$val"
        exit 0
    fi
    echo "source-date-epoch: $pin is not a unix time" >&2
    exit 1
fi

version=""
if [[ -f "$ROOT/VERSION" ]]; then
    version="$(tr -d '[:space:]' < "$ROOT/VERSION")"
fi

if [[ -n "$version" ]] && git -C "$ROOT" rev-parse --verify -q "refs/tags/v${version}^{}" >/dev/null; then
    git -C "$ROOT" log -1 --format=%ct "v${version}^{}"
    exit 0
fi

if git -C "$ROOT" rev-parse --verify -q HEAD >/dev/null; then
    git -C "$ROOT" log -1 --format=%ct HEAD
    exit 0
fi

echo "source-date-epoch: no pin, tag, or HEAD in $ROOT" >&2
exit 1
