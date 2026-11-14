#!/usr/bin/env bash
# Install extxyz-ng 0.0.2 into its own prefix under the bench disk.
# The wheel's import name is extxyz, so a default install would replace
# extxyz 0.4.6. cross_format.py loads it from this prefix instead.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="${READCON_BENCH_DISK:-${here}/../../build/bench}"
prefix="${root}/extxyz-ng-0.0.2"
rm -rf "${prefix}"
mkdir -p "${prefix}"
python3 -m pip install --no-deps --only-binary :all: --require-hashes \
    --target "${prefix}" -r "${here}/extxyz-ng.txt"
