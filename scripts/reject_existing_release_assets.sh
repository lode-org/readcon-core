#!/usr/bin/env bash
# Stop a release upload when any of the named files is already an asset.
# softprops/action-gh-release replaces an asset of the same name.
set -euo pipefail

if [[ $# -lt 2 ]]; then
    echo "usage: $0 TAG FILE..." >&2
    exit 2
fi

tag="$1"
shift

if ! command -v gh >/dev/null 2>&1; then
    echo "gh is required to read release assets" >&2
    exit 1
fi

have="$(gh release view "$tag" --json assets --jq '.assets[].name')"
fail=0
for path in "$@"; do
    name="$(basename "$path")"
    if printf '%s\n' "$have" | grep -Fxq "$name"; then
        echo "release asset already exists: ${name} on ${tag}" >&2
        fail=1
    fi
done

if [[ "$fail" -ne 0 ]]; then
    exit 1
fi
echo "release ${tag} has none of the assets about to be uploaded"
