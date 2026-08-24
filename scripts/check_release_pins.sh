#!/usr/bin/env bash
# Structural gate: release.yml actions are immutable SHAs, and the
# cargo-dist / rustup installers are checksum-verified before exec.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WF="$ROOT/.github/workflows/release.yml"
fail=0

die() { echo "ERROR: $*" >&2; fail=1; }
ok() { echo "OK: $*"; }

[[ -f "$WF" ]] || die "missing $WF"

if grep -nE 'uses:[[:space:]]*[^[:space:]]+@(v[0-9]|stable|main|master)' "$WF" \
  | grep -vq '^\s*#'; then
  die "release.yml still pins an action to a mutable tag"
  grep -nE 'uses:[[:space:]]*[^[:space:]]+@(v[0-9]|stable|main|master)' "$WF" || true
else
  ok "release.yml uses: lines are not mutable tags"
fi

# Every uses: must be owner/repo@40-hex
unpinned=0
while IFS= read -r line; do
  if [[ "$line" =~ uses:[[:space:]]*([^[:space:]#]+) ]]; then
    ref="${BASH_REMATCH[1]}"
    if [[ ! "$ref" =~ @[0-9a-fA-F]{40}$ ]]; then
      die "unpinned uses: $ref"
      unpinned=1
    fi
  fi
done < <(grep -E 'uses:' "$WF" | grep -v '^\s*#')
if [[ "$unpinned" -eq 0 ]]; then
  ok "release.yml uses: refs are 40-char SHAs"
fi

if grep -E 'curl .*\|[[:space:]]*sh' "$WF" | grep -vq '^\s*#'; then
  die "release.yml still pipes a download into sh"
else
  ok "release.yml does not pipe curl into sh"
fi

if grep -E 'rustup\.rs|rustup.sh' "$WF" | grep -vqE '^\s*#|sha256|SHA256'; then
  # Allowed only when a checksum is verified on the same job.
  if ! grep -qE 'sha256sum -c|SHA256' "$WF"; then
    die "release.yml fetches rustup without a checksum"
  fi
fi
if grep -qE 'sha256sum -c' "$WF"; then
  ok "release.yml checksum-verifies downloaded installers"
else
  die "release.yml never checksum-verifies an installer"
fi

if [[ "$fail" -ne 0 ]]; then
  echo "check_release_pins: FAILED" >&2
  exit 1
fi
echo "check_release_pins: all checks passed"
