#!/usr/bin/env bash
# Write one release version into every file that records it. cog.toml runs
# this as a pre-bump hook, so the tag and the published packages agree.
set -euo pipefail
v=${1:?usage: set-version.sh VERSION}
root=$(cd "$(dirname "$0")/.." && pwd)
cd "$root"
# First version key only: the package's own, not a dependency's.
sed -i -E "0,/^version = \"[^\"]*\"/s//version = \"$v\"/" Cargo.toml pyproject.toml
# The lock entry of the crate itself sits on the line after its name.
sed -i -E "/^name = \"readcon-core\"$/{n;s/^version = \"[^\"]*\"/version = \"$v\"/}" Cargo.lock
sed -i -E "0,/^    version: '[^']*',/s//    version: '$v',/" meson.build
sed -i -E "s/^version: .*/version: $v/" CITATION.cff
sed -i -E "0,/\"version\": \"[^\"]*\"/s//\"version\": \"$v\"/" codemeta.json .zenodo.json
sed -i -E "s|readcon-core/tree/v[0-9][0-9.]*|readcon-core/tree/v$v|; s/Deposit the v[0-9][0-9.]* software tag/Deposit the v$v software tag/" .zenodo.json
