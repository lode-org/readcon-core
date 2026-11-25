#!/usr/bin/env bash
# Report whether the generated cxx wrap pin files differ from HEAD.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

pin_paths=(
    docs/orgmode/bindings.org
    docs/orgmode/getting-started.org
    docs/source/bindings.rst
    docs/source/getting-started.rst
    packaging/wrapdb/readcon-core.sha256
    packaging/wrapdb/readcon-core.wrap
)

if git diff --quiet -- "${pin_paths[@]}"; then
    echo "cxx wrap pin is current"
    exit 0
fi

echo "cxx wrap pin needs recording"
exit 1
