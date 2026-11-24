#!/usr/bin/env bash
# Rebuild the slim cxx archive and compare it with the recorded pin.
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
# shellcheck source=scripts/scratch.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/scratch.sh"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

mode="${1:---strict}"
case "$mode" in
    --strict | --pull-request) ;;
    *)
        echo "usage: $0 [--strict|--pull-request]" >&2
        exit 2
        ;;
esac

mismatch() {
    local message="$1"
    local annotation="file=packaging/wrapdb/readcon-core.sha256"
    if [[ "$mode" == "--pull-request" ]]; then
        echo "::warning ${annotation}::${message}"
        echo "WARNING: ${message}" >&2
        return 0
    fi
    echo "ERROR: ${message}" >&2
    return 1
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
    if mismatch \
        "recorded cxx pin '${recorded}' is not a 64-character sha256"
    then
        exit 0
    fi
    exit 1
fi
if [[ "$wrap_hash" != "$recorded" ]]; then
    if mismatch \
        "wrap hash ${wrap_hash} and sidecar ${recorded} disagree"
    then
        exit 0
    fi
    exit 1
fi

out="$(scratch_dir)"
trap 'rm -rf "$out"' EXIT
bash scripts/package-cxx.sh "$out" >/dev/null
packaged="$(tr -d '[:space:]' < "${out}/${archive}.sha256")"

if [[ "$packaged" == "$recorded" ]]; then
    echo "OK: cxx wrap pin ${recorded} matches the packaged tree"
    exit 0
fi

message="cxx wrap pin does not match the packaged tree"
if [[ "$mode" == "--pull-request" ]]; then
    annotation="file=packaging/wrapdb/readcon-core.sha256"
    echo "::warning ${annotation}::${message}"
    prefix="WARNING"
else
    prefix="ERROR"
fi
cat >&2 <<EOF
${prefix}: ${message}.
  packaged: ${packaged}
  recorded: ${recorded}
Pull requests do not re-record this generated pin. The develop branch
automation records it after merge. The cxx upload refuses a digest that
differs from the pin.
EOF
if [[ "$mode" == "--pull-request" ]]; then
    exit 0
fi
exit 1
