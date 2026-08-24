#!/usr/bin/env bash
# Regenerate or check the C API header (include/readcon-core.h) with cbindgen.
#
# Optional maintainer draft of include/readcon-core.h. The committed header
# is the C ABI (metatensor/metatomic model). CI and consumers do not run
# this script. Edit the shipped header, or use this to sketch declarations
# and then review/commit the file.
#
# Usage:
#   scripts/regen-capi-headers.sh           Write a cbindgen draft in place.
#   scripts/regen-capi-headers.sh --check   Diff the shipped header against
#                                           a cbindgen draft (maintainer only).
#
# Requires cbindgen on PATH. Install with: cargo install cbindgen
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HEADER_DST="${ROOT_DIR}/include/readcon-core.h"
CHECK_ONLY=0

if [[ "${1:-}" == "--check" ]]; then
    CHECK_ONLY=1
fi

if ! command -v cbindgen >/dev/null 2>&1; then
    echo "cbindgen not found on PATH. Install with: cargo install cbindgen" >&2
    exit 1
fi

if [[ "${CHECK_ONLY}" -eq 1 ]]; then
    tmp="$(mktemp)"
    trap 'rm -f "${tmp}"' EXIT
    cbindgen \
        --config "${ROOT_DIR}/cbindgen.toml" \
        --crate readcon-core \
        --output "${tmp}" >/dev/null
    if ! diff -u "${HEADER_DST}" "${tmp}"; then
        echo "drift detected: include/readcon-core.h is out of sync with cbindgen output" >&2
        echo "run: scripts/regen-capi-headers.sh" >&2
        exit 1
    fi
    echo "include/readcon-core.h is in sync with cbindgen output"
else
    cbindgen \
        --config "${ROOT_DIR}/cbindgen.toml" \
        --crate readcon-core \
        --output "${HEADER_DST}"
    echo "Regenerated ${HEADER_DST}"
fi
