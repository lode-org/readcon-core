#!/usr/bin/env bash
# Conventional-commit gate from the latest version tag.
# Git default `Revert "..."` subjects are accepted: those commits already
# sit on main after v0.14.7 and git-revert writes that subject.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

latest=$(git describe --tags --abbrev=0 --match 'v[0-9]*')
echo "Checking commits from ${latest}"

fail=0
while IFS=$'\t' read -r sha subject; do
  [[ -n "$sha" ]] || continue
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
done < <(git log --format='%H%x09%s' "${latest}..HEAD")

if [[ "$fail" -ne 0 ]]; then
  echo "ERROR: conventional commit check failed from ${latest}" >&2
  exit 1
fi
echo "OK conventional commits from ${latest}"
