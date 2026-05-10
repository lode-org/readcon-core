#!/usr/bin/env bash
# Regenerate the C API header (include/readcon-core.h) with cbindgen.
#
# The header is shipped pre-generated so downstream packagers (conda-forge,
# distro builds, cargo-c installs) never need cbindgen on the build host.
# Run this script whenever the FFI surface in src/ffi.rs changes, then
# commit the regenerated include/readcon-core.h alongside the source change.
#
# Requires cbindgen on PATH. Install with: cargo install cbindgen
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HEADER_DST="${ROOT_DIR}/include/readcon-core.h"

if ! command -v cbindgen >/dev/null 2>&1; then
    echo "cbindgen not found on PATH. Install with: cargo install cbindgen" >&2
    exit 1
fi

cbindgen \
    --config "${ROOT_DIR}/cbindgen.toml" \
    --crate readcon-core \
    --output "${HEADER_DST}"

echo "Regenerated ${HEADER_DST}"
