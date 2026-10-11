#!/usr/bin/env bash
# Check conventional commit subjects on one revision range.
# A pull request sets RANGE_START to the base sha and RANGE_END to the head sha.
# A push sets RANGE_START to github.event.before and RANGE_END to github.sha.
# An all-zero RANGE_START means the branch is new, so the range starts at
# the merge-base with origin/main. Merge commits are skipped.
# Git default `Revert "..."` subjects are accepted.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

zeros=0000000000000000000000000000000000000000
start=${RANGE_START:-}
end=${RANGE_END:-HEAD}

if [[ -z "$start" || "$start" == "$zeros" ]]; then
  if [[ "$end" == "$zeros" ]]; then
    echo "ERROR: range end is empty" >&2
    exit 1
  fi
  start=$(git merge-base origin/main "$end")
fi

echo "Checking commits ${start}..${end}"

fail=0
log=$(git log --format='%H%x09%P%x09%s' "${start}..${end}")
while IFS=$'\t' read -r sha parents subject; do
  [[ -n "$sha" ]] || continue
  if [[ "$parents" == *" "* ]]; then
    echo "OK skip merge ${sha} ${subject}"
    continue
  fi
  case "$subject" in
    Merge\ *|fixup!\ *|squash!\ *|amend!\ *)
      echo "OK skip ${sha} ${subject}"
      continue
      ;;
    Revert\ *)
      echo "OK revert ${sha} ${subject}"
      continue
      ;;
  esac
  if [[ "$subject" =~ ^[a-z]+(\([a-z0-9/_-]+\))?!?:\ .+ ]]; then
    echo "OK ${sha} ${subject}"
  else
    echo "ERROR non-conventional ${sha} ${subject}" >&2
    fail=1
  fi
done <<< "$log"

if [[ "$fail" -ne 0 ]]; then
  echo "ERROR: conventional commit check failed for ${start}..${end}" >&2
  exit 1
fi
echo "OK conventional commits for ${start}..${end}"
