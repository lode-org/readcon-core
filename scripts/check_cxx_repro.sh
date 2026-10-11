#!/usr/bin/env bash
# Two C++ source tarballs from the same tree must share one sha256.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
epoch="${SOURCE_DATE_EPOCH:-$(git -C "$ROOT" log -1 --format=%ct HEAD)}"
export SOURCE_DATE_EPOCH="$epoch"

a="$(mktemp -d)"
b="$(mktemp -d)"
trap 'rm -rf "$a" "$b"' EXIT

bash "$ROOT/scripts/package-cxx.sh" "$a"
bash "$ROOT/scripts/package-cxx.sh" "$b"

sha_a="$(sha256sum "$a"/readcon-core-cxx-*.tar.gz | awk '{print $1}')"
sha_b="$(sha256sum "$b"/readcon-core-cxx-*.tar.gz | awk '{print $1}')"

if [[ "$sha_a" != "$sha_b" ]]; then
    echo "cxx tarball is not reproducible" >&2
    echo "first  ${sha_a}" >&2
    echo "second ${sha_b}" >&2
    exit 1
fi
echo "cxx tarball reproducible sha256:${sha_a}"
