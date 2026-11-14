#!/usr/bin/env bash
# Rebuild the slim cxx archive and fail when the recorded wrap pin disagrees.
#
# scripts/record-cxx-wrap.sh packages with scripts/package-cxx.sh, then writes
# the digest into packaging/wrapdb. This check runs that same packager. It
# keeps the saved source-date-epoch. --fresh would replace that epoch with
# the v$VERSION tag date and reject a pin that is already current.
#
# packaging/wrapdb is not a member of the archive, so updating the pin does
# not change the digest. A src or workflow edit does. Catch that before the
# tag upload, which refuses a different digest.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

die() {
    echo "ERROR: $*" >&2
    exit 1
}

ver="$(tr -d '[:space:]' < VERSION)"
archive="readcon-core-cxx-${ver}.tar.gz"
recorded="$(tr -d '[:space:]' < packaging/wrapdb/readcon-core.sha256)"
wrap_hash="$(
    sed -n 's/^source_hash[[:space:]]*=[[:space:]]*//p' packaging/wrapdb/readcon-core.wrap \
        | head -1
)"
wrap_hash="${wrap_hash#sha256:}"

if [[ ! "$recorded" =~ ^[0-9a-f]{64}$ ]]; then
    die "recorded cxx pin '${recorded}' is not a 64-character sha256"
fi
if [[ "$wrap_hash" != "$recorded" ]]; then
    die "wrap source_hash ${wrap_hash} and sha256 sidecar ${recorded} disagree"
fi

out="$(mktemp -d)"
trap 'rm -rf "$out"' EXIT
bash scripts/package-cxx.sh "$out" >/dev/null
packaged="$(tr -d '[:space:]' < "${out}/${archive}.sha256")"

if [[ "$packaged" == "$recorded" ]]; then
    echo "OK: cxx wrap pin ${recorded} matches the packaged tree"
    exit 0
fi

cat >&2 <<EOF
ERROR: cxx wrap pin does not match the packaged tree.
  packaged: ${packaged}
  recorded: ${recorded}
The recorded pin describes a different archive than this checkout. Re-record
it with scripts/record-cxx-wrap.sh before tagging. The cxx upload refuses a
digest that differs from the pin.
EOF
exit 1
