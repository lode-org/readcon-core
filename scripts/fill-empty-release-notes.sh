#!/usr/bin/env bash
# Fill a GitHub Release body from CHANGELOG.md when the body is empty.
#
# Usage: fill-empty-release-notes.sh --tag vX.Y.Z --changelog PATH
# Reads GITHUB_REPOSITORY. Does not create a release or move a tag.
set -euo pipefail
# shellcheck source=scripts/scratch.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/scratch.sh"

tag=""
changelog=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --tag)
            tag="$2"
            shift 2
            ;;
        --changelog)
            changelog="$2"
            shift 2
            ;;
        *)
            echo "usage: $0 --tag vX.Y.Z --changelog PATH" >&2
            exit 2
            ;;
    esac
done

if [[ -z "$tag" || -z "$changelog" ]]; then
    echo "usage: $0 --tag vX.Y.Z --changelog PATH" >&2
    exit 2
fi
repo="${GITHUB_REPOSITORY:?}"
if [[ ! "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "tag must be vX.Y.Z" >&2
    exit 1
fi

version="${tag#v}"
body="$(gh release view "$tag" --repo "$repo" --json body --jq .body)"
if [[ -n "${body//[[:space:]]/}" && "$body" != "null" ]]; then
    echo "release $tag already has notes"
    exit 0
fi

notes="$(scratch_file)"
python3 - "$changelog" "$version" "$notes" <<'PY'
import pathlib
import sys

path, version, dest = sys.argv[1:]
text = pathlib.Path(path).read_text(encoding="utf-8")
heading = f"## v{version}"
lines = text.splitlines()
start = None
for index, line in enumerate(lines):
    if line.startswith(heading):
        start = index
        break
if start is None:
    raise SystemExit(f"{path} has no {heading} section")
end = len(lines)
for index in range(start + 1, len(lines)):
    if lines[index].startswith("## "):
        end = index
        break
section = "\n".join(lines[start:end]).strip() + "\n"
pathlib.Path(dest).write_text(section, encoding="utf-8")
PY

gh release edit "$tag" --repo "$repo" --notes-file "$notes"
rm -f "$notes"
echo "filled empty release notes for $tag"
