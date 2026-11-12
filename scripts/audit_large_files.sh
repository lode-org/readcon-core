#!/usr/bin/env bash
# Blobs reachable from HEAD must stay under 1 MiB.
#
# Lint used to run HaoZeke/large-file-auditor@v0.1.0. That action
# mirror-clones the checkout and runs git-filter-repo --analyze on every
# ref. actions/checkout with fetch-depth 0 fetches every branch, so the
# mirror included origin/paper/restore. The only blobs at or above 1 MiB
# are two generations of the generated figure
# paper/cpc/src/figures/generated/claisen_wbo.pdf:
#   a2fdc9d456f9773c2688d7c6217437bbb6a35254  1827974 bytes
#   62edd4213e33b0eee95a655161632bc258f16d8d  1794839 bytes
# Neither commit is an ancestor of main. They are absent from v0.21.0
# (7e920fec) and from 7bbee90d. A push to main was failing on a file that
# branch does not contain. This script audits HEAD, the branch the
# workflow checked out.
#
# scripts/large-file-allowlist.txt may list blob SHAs or paths, one per
# line, when a fixture is supposed to be this large. The figure above is
# not listed: it is not part of this branch.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

threshold="${LARGE_FILE_THRESHOLD:-1048576}"
allowfile="${LARGE_FILE_ALLOWLIST:-$root/scripts/large-file-allowlist.txt}"

declare -A allow_sha=()
declare -A allow_path=()
if [[ -f "$allowfile" ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%%#*}"
    # trim surrounding whitespace
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [[ -n "$line" ]] || continue
    if [[ "$line" =~ ^[0-9a-f]{40}$ ]]; then
      allow_sha["$line"]=1
    else
      allow_path["$line"]=1
    fi
  done < "$allowfile"
fi

list="$(mktemp)"
trap 'rm -f "$list"' EXIT
git rev-list --objects HEAD \
  | git cat-file --batch-check='%(objecttype) %(objectname) %(objectsize) %(rest)' \
  > "$list"

fail=0
while read -r type sha size path; do
  [[ "$type" == "blob" ]] || continue
  if [[ -n "${allow_sha[$sha]:-}" ]]; then
    continue
  fi
  if [[ -n "$path" && -n "${allow_path[$path]:-}" ]]; then
    continue
  fi
  if (( size >= threshold )); then
    printf 'large file: %s bytes %s %s\n' "$size" "$sha" "$path" >&2
    fail=1
  fi
done < "$list"

if (( fail != 0 )); then
  printf 'audit: a blob reachable from HEAD is at least %s bytes\n' "$threshold" >&2
  exit 1
fi
printf 'audit: no blob reachable from HEAD is at least %s bytes\n' "$threshold"
