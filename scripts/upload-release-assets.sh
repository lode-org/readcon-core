#!/usr/bin/env bash
# Attach files to an existing GitHub Release.
#
# The only write is `gh release upload --clobber`, which replaces assets of
# the same name. This script does not create a release, move a tag, publish
# crates, or publish wheels.
#
# Usage:
#   scripts/upload-release-assets.sh --tag vX.Y.Z [--wait] [--dry-run] FILE...
#
# --wait polls until the Release exists. A v* tag push needs that, because
# cargo-dist creates the Release in a different workflow. A backfill omits
# --wait and fails when the release is missing.
set -euo pipefail

tag=""
wait_for=0
dry_run=0

usage() {
  echo "usage: $0 --tag vX.Y.Z [--wait] [--dry-run] FILE..." >&2
  exit 2
}

while [ $# -gt 0 ]; do
  case "$1" in
    --tag)
      if [ $# -lt 2 ]; then
        usage
      fi
      tag="$2"
      shift 2
      ;;
    --wait)
      wait_for=1
      shift
      ;;
    --dry-run)
      dry_run=1
      shift
      ;;
    --)
      shift
      break
      ;;
    -*)
      echo "unknown argument: $1" >&2
      usage
      ;;
    *)
      break
      ;;
  esac
done

# A pasted tag can carry a trailing newline from the dispatch form.
tag=$(printf '%s' "$tag" | tr -d '[:space:]')

if ! printf '%s\n' "$tag" | grep -Eq '^v[0-9]+\.[0-9]+\.[0-9]+([-+][0-9A-Za-z.-]+)?$'; then
  echo "tag must look like vX.Y.Z (got: ${tag:-<empty>})" >&2
  exit 1
fi

if [ $# -eq 0 ]; then
  echo "no assets to upload" >&2
  exit 1
fi

for asset in "$@"; do
  if [ ! -f "$asset" ]; then
    echo "missing asset: $asset" >&2
    exit 1
  fi
done

# The clib job checks out into packager/ and src/, so the workspace root is
# not a git repository. Without --repo, gh reports a missing release and the
# real error is the only way to tell that apart from a tag that was never
# published.
repo="${GITHUB_REPOSITORY:-}"
if [ -z "$repo" ]; then
  echo "GITHUB_REPOSITORY is empty; refusing to upload" >&2
  exit 1
fi

if [ "$dry_run" -eq 1 ]; then
  printf 'would run: gh release upload %q --repo %q --clobber' "$tag" "$repo"
  for asset in "$@"; do
    printf ' %q' "$asset"
  done
  printf '\n'
  if [ "$wait_for" -eq 1 ]; then
    echo "would wait for existing release $tag"
  else
    echo "would require existing release $tag"
  fi
  exit 0
fi

if [ -z "${GH_TOKEN:-}${GITHUB_TOKEN:-}" ]; then
  echo "GH_TOKEN is empty; refusing to upload" >&2
  exit 1
fi

poll="${UPLOAD_POLL_SECONDS:-15}"
limit="${UPLOAD_WAIT_TIMEOUT:-2700}"
deadline=$((SECONDS + limit))

# Leave stderr on the terminal. Redirecting it made a missing git remote
# look like "release does not exist".
have_release() {
  gh release view "$tag" --repo "$repo" --json tagName --jq .tagName >/dev/null
}

if [ "$wait_for" -eq 1 ]; then
  while ! have_release; do
    if [ "$SECONDS" -gt "$deadline" ]; then
      echo "release $tag was not created within ${limit}s; not creating one" >&2
      exit 1
    fi
    sleep "$poll"
  done
elif ! have_release; then
  echo "release $tag does not exist; upload does not create a release or move a tag" >&2
  exit 1
fi

tag_sha() {
  gh api "repos/${repo}/git/ref/tags/${tag}" --jq .object.sha
}

before="$(tag_sha)"
gh release upload "$tag" --repo "$repo" --clobber "$@"
after="$(tag_sha)"
if [ "$before" != "$after" ]; then
  echo "tag $tag moved during upload (${before} -> ${after})" >&2
  exit 1
fi
