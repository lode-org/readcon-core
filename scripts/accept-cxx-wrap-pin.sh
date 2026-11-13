#!/usr/bin/env bash
# Accept the slim cxx archive when a committed wrap pin names this build.
#
# Usage: accept-cxx-wrap-pin.sh BUILT_SHA TAG_ROOT
#
# TAG_ROOT is the tree that was packed. A tag push runs this script from
# that tree, so the pin there is the only pin. workflow_dispatch checks
# the tag out separately from the workflow ref that holds this script.
# When the tag pin is not this build, the pin next to this script is
# accepted if both trees name the same VERSION and that pin is the
# archive just built. A retag is not required.
set -euo pipefail

if [[ $# -ne 2 ]]; then
    echo "usage: $0 BUILT_SHA TAG_ROOT" >&2
    exit 2
fi

built="$(printf '%s' "$1" | tr -d '[:space:]')"
ROOT="${2}"
if [[ ! -d "$ROOT" ]]; then
    echo "accept-cxx-wrap-pin: $ROOT is not a directory" >&2
    exit 1
fi

SCRIPT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
ROOT="$(cd "$ROOT" && pwd -P)"

read_version() {
    local file="$1/VERSION"
    if [[ ! -f "$file" ]]; then
        return 1
    fi
    tr -d '[:space:]' < "$file"
}

read_pin() {
    local file="$1/packaging/wrapdb/readcon-core.sha256"
    if [[ ! -f "$file" ]]; then
        return 1
    fi
    tr -d '[:space:]' < "$file"
}

refuse() {
    local pinned="$1"
    echo "refusing upload: built ${built} != wrap pin ${pinned}" >&2
    if [[ -n "${2:-}" ]]; then
        echo "workflow-ref pin ${2} does not match this build either." >&2
    fi
    echo "Run scripts/record-cxx-wrap.sh and commit that pin before tagging." >&2
    exit 1
}

if ! pinned="$(read_pin "$ROOT")"; then
    echo "accept-cxx-wrap-pin: ${ROOT}/packaging/wrapdb/readcon-core.sha256 is missing" >&2
    exit 1
fi

if [[ "$built" == "$pinned" ]]; then
    exit 0
fi

# Same layout as source-date-epoch.sh: a pin that lives next to this
# script counts only when the packed tree and the script tree name one
# VERSION. A tag push has one tree, so this branch does not run.
if [[ "$SCRIPT_ROOT" != "$ROOT" ]]; then
    root_version="$(read_version "$ROOT" || true)"
    script_version="$(read_version "$SCRIPT_ROOT" || true)"
    if [[ -n "$root_version" && "$root_version" == "$script_version" ]]; then
        if script_pin="$(read_pin "$SCRIPT_ROOT")"; then
            if [[ "$built" == "$script_pin" ]]; then
                echo "accept-cxx-wrap-pin: tag pin ${pinned} differs; workflow-ref pin matches this build"
                exit 0
            fi
            refuse "$pinned" "$script_pin"
        fi
    fi
fi

refuse "$pinned"
