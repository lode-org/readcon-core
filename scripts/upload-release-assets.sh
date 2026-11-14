#!/usr/bin/env bash
# Attach files to an existing GitHub Release.
#
# The only write is `gh release upload --clobber` for assets that are not
# already on the release. An asset whose sha256 matches the published bytes
# is skipped. An asset whose bytes differ is left in place. On a v* tag
# push that mismatch is a hard error. A backfill (--backfill, or
# GITHUB_EVENT_NAME=workflow_dispatch) prints a GitHub ::warning:: and the
# job continues. This script does not create a release, move a tag, publish
# crates, or publish wheels.
#
# Usage:
#   scripts/upload-release-assets.sh --tag vX.Y.Z [--wait] [--backfill] [--dry-run] FILE...
#
# --wait polls until the Release exists. A v* tag push needs that, because
# cargo-dist creates the Release in a different workflow. A backfill omits
# --wait and fails when the release is missing.
set -euo pipefail
# shellcheck source=scripts/scratch.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/scratch.sh"

tag=""
wait_for=0
dry_run=0
backfill=0

usage() {
  echo "usage: $0 --tag vX.Y.Z [--wait] [--backfill] [--dry-run] FILE..." >&2
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
    --backfill)
      backfill=1
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

# workflow_dispatch is the backfill. GITHUB_EVENT_NAME is set by Actions
# even when the workflow forgot --backfill.
if [ "$backfill" -eq 0 ] && [ "${GITHUB_EVENT_NAME:-}" = "workflow_dispatch" ]; then
  backfill=1
fi

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

sha256_file() {
  if command -v sha256sum >/dev/null; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$1"
  fi
}

# Print ABSENT, NODIGEST, or the published digest for one asset name.
# The JSON document is on stdin so a Windows path never reaches python.
asset_record() {
  python3 -c '
import json
import sys

name = sys.argv[1]
try:
    data = json.load(sys.stdin)
except json.JSONDecodeError as exc:
    sys.stderr.write("release asset list is not JSON: %s\n" % exc)
    sys.exit(1)
for item in data.get("assets") or []:
    if item.get("name") == name:
        digest = str(item.get("digest") or "").strip()
        if digest and digest.lower() != "null":
            print(digest)
        else:
            print("NODIGEST")
        raise SystemExit(0)
print("ABSENT")
' "$1"
}

if [ "$dry_run" -eq 1 ]; then
  printf 'would run: gh release upload %q --repo %q --clobber' "$tag" "$repo"
  for asset in "$@"; do
    printf ' %q' "$asset"
  done
  printf '\n'
  if [ "$backfill" -eq 1 ]; then
    echo "would warn and leave an asset whose bytes differ"
  else
    echo "would skip an asset whose release sha256 matches and refuse one that differs"
  fi
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

assets_json="$(gh release view "$tag" --repo "$repo" --json assets)"
pending=()
blocked=0
warned=0
for asset in "$@"; do
  base=$(basename "$asset")
  local_sha=$(sha256_file "$asset")
  state=$(printf '%s' "$assets_json" | asset_record "$base")
  if [ "$state" = "ABSENT" ]; then
    pending[${#pending[@]}]="$asset"
    continue
  fi
  if [ "$state" = "NODIGEST" ]; then
    tmp=$(scratch_dir)
    gh release download "$tag" --repo "$repo" --pattern "$base" --dir "$tmp"
    state="sha256:$(sha256_file "$tmp/$base")"
    rm -rf "$tmp"
  fi
  remote_sha=$(printf '%s' "$state" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')
  remote_sha=${remote_sha#sha256:}
  local_cmp=$(printf '%s' "$local_sha" | tr '[:upper:]' '[:lower:]')
  if [ "$remote_sha" = "$local_cmp" ]; then
    echo "skip $base: existing sha256 matches"
    continue
  fi
  if [ "$backfill" -eq 1 ]; then
    # stdout, one line: Actions turns ::warning:: into an annotation.
    echo "::warning::Published asset ${base} was left unchanged (release ${remote_sha}, local ${local_cmp})"
    warned=1
    continue
  fi
  echo "refusing to overwrite $base" >&2
  echo "  release sha256: $remote_sha" >&2
  echo "  local sha256:   $local_cmp" >&2
  blocked=1
done

if [ "$blocked" -ne 0 ]; then
  echo "refusing to upload; an existing release asset has different bytes" >&2
  exit 1
fi

if [ "${#pending[@]}" -eq 0 ]; then
  if [ "$warned" -ne 0 ]; then
    echo "no asset was uploaded; differing published assets were left untouched"
  else
    echo "every asset already matches the release sha256; nothing to upload"
  fi
  exit 0
fi

before="$(tag_sha)"
gh release upload "$tag" --repo "$repo" --clobber "${pending[@]}"
after="$(tag_sha)"
if [ "$before" != "$after" ]; then
  echo "tag $tag moved during upload (${before} -> ${after})" >&2
  exit 1
fi
