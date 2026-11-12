#!/usr/bin/env bash
# Print the SOURCE_DATE_EPOCH for a reproducible archive of this tree.
#
# Resolution order:
#   1. A caller-supplied SOURCE_DATE_EPOCH (skipped with --fresh).
#   2. packaging/wrapdb/source-date-epoch in ROOT, the pin from the last
#      record-cxx-wrap.sh run (skipped with --fresh).
#   3. That same pin next to this script, when ROOT has no pin and both
#      trees name the same VERSION. A clib backfill checks the tag out
#      separately from the workflow ref that holds the pin.
#   4. The committer date of the v$VERSION tag, when that tag exists.
#   5. The committer date of HEAD.
#
# Git lookups mark ROOT as a safe.directory first. A manylinux container
# mounts the checkout as another user, and git otherwise refuses it.
# --fresh is how a release records a new pin. A later build of that
# commit reads the pin, so a new committer date cannot move the archive.
set -euo pipefail

fresh=0
if [[ "${1:-}" == "--fresh" ]]; then
    fresh=1
    shift
fi

ROOT="${1:-.}"
if [[ ! -d "$ROOT" ]]; then
    echo "source-date-epoch: $ROOT is not a directory" >&2
    exit 1
fi

SCRIPT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
ROOT="$(cd "$ROOT" && pwd -P)"

if [[ "$fresh" -eq 0 && -n "${SOURCE_DATE_EPOCH:-}" ]]; then
    printf '%s\n' "$SOURCE_DATE_EPOCH"
    exit 0
fi

# Missing pin: keep looking. A pin that is not a unix time is a hard error.
consider_pin() {
    local pin="$1"
    local val
    if [[ ! -f "$pin" ]]; then
        return 0
    fi
    val="$(tr -d '[:space:]' < "$pin")"
    if [[ ! "$val" =~ ^[0-9]+$ ]]; then
        echo "source-date-epoch: $pin is not a unix time" >&2
        exit 1
    fi
    printf '%s\n' "$val"
    exit 0
}

read_version() {
    local file="$1/VERSION"
    if [[ ! -f "$file" ]]; then
        return 1
    fi
    tr -d '[:space:]' < "$file"
}

if [[ "$fresh" -eq 0 ]]; then
    consider_pin "$ROOT/packaging/wrapdb/source-date-epoch"
    if [[ "$SCRIPT_ROOT" != "$ROOT" ]]; then
        root_version="$(read_version "$ROOT" || true)"
        script_version="$(read_version "$SCRIPT_ROOT" || true)"
        if [[ -n "$root_version" && "$root_version" == "$script_version" ]]; then
            consider_pin "$SCRIPT_ROOT/packaging/wrapdb/source-date-epoch"
        fi
    fi
fi

add_safe() {
    local path="$1"
    if git config --global --get-all safe.directory 2>/dev/null | grep -Fx -- "$path" >/dev/null; then
        return 0
    fi
    git config --global --add safe.directory "$path"
}

mark_safe() {
    local dir="$1"
    local logical physical
    if ! command -v git >/dev/null 2>&1; then
        return 0
    fi
    if [[ ! -d "$dir" ]]; then
        return 0
    fi
    logical="$(cd "$dir" && pwd -L)"
    physical="$(cd "$dir" && pwd -P)"
    add_safe "$logical"
    if [[ "$physical" != "$logical" ]]; then
        add_safe "$physical"
    fi
}

mark_safe "$ROOT"

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
