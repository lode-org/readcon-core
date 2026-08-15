#!/usr/bin/env bash
# Assemble a C/C++ source tarball that CMake FetchContent and Meson wrap
# can consume without cbindgen, Corrosion, or git.
#
# Layout (featomic / metatensor-core-cxx convention):
#   readcon-core-cxx-$VERSION/
#     Cargo.toml Cargo.lock src/ include/ build.rs
#     CMakeLists.txt cmake/ meson.build meson_options.txt
#     scripts/meson_cargo_build.py
#     examples/c_api_sample.c examples/cpp_api_sample.cpp examples/meson.build
#     resources/test/tiny_multi_cuh2.con
#     LICENSE README.cxx.md
#     [.cargo/config.toml + vendor/ when --vendor]
#
# Usage:
#   scripts/package-cxx.sh <output-dir> [--vendor]
set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "usage: $0 OUTPUT_DIR [--vendor]" >&2
    exit 2
fi

OUTPUT_DIR="$1"
shift
VENDOR=0
if [[ "${1:-}" == "--vendor" ]]; then
    VENDOR=1
fi

mkdir -p "$OUTPUT_DIR"
OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd)"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

VERSION="$(sed -n 's/^version = "\([^"]*\)"/\1/p' "$ROOT_DIR/Cargo.toml" | head -1)"
if [[ "$VENDOR" -eq 1 ]]; then
    ARCHIVE_NAME="readcon-core-cxx-${VERSION}-vendor"
else
    ARCHIVE_NAME="readcon-core-cxx-${VERSION}"
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

DEST="${TMP_DIR}/${ARCHIVE_NAME}"
mkdir -p "$DEST"/{cmake,include,src,scripts,examples,resources/test}

# Crate sources: cargo package for a clean, publish-shaped tree, then overlay
# the CMake/Meson install surface cargo package does not treat as crate files.
cd "$ROOT_DIR"
cargo package --allow-dirty --no-verify --package readcon-core
CRATE_TAR="$(ls -1 "$ROOT_DIR"/target/package/readcon-core-"${VERSION}".crate)"
mkdir -p "${TMP_DIR}/crate"
tar -C "${TMP_DIR}/crate" -xf "$CRATE_TAR"
CRATE_DIR="$(find "${TMP_DIR}/crate" -mindepth 1 -maxdepth 1 -type d | head -1)"

cp -a "${CRATE_DIR}/." "$DEST/"

# Overlay the C/C++ distribution files (always, even if cargo package omitted them).
cp -a "$ROOT_DIR/CMakeLists.txt" "$DEST/"
cp -a "$ROOT_DIR/cmake/." "$DEST/cmake/"
cp -a "$ROOT_DIR/meson.build" "$DEST/"
cp -a "$ROOT_DIR/meson_options.txt" "$DEST/"
cp -a "$ROOT_DIR/include/." "$DEST/include/"
cp -a "$ROOT_DIR/scripts/meson_cargo_build.py" "$DEST/scripts/"
cp -a "$ROOT_DIR/examples/c_api_sample.c" "$DEST/examples/"
cp -a "$ROOT_DIR/examples/cpp_api_sample.cpp" "$DEST/examples/"
cp -a "$ROOT_DIR/examples/meson.build" "$DEST/examples/"
cp -a "$ROOT_DIR/resources/test/tiny_multi_cuh2.con" "$DEST/resources/test/"
cp -a "$ROOT_DIR/LICENSE" "$DEST/"
if [[ -f "$ROOT_DIR/Cargo.lock" ]]; then
    cp -a "$ROOT_DIR/Cargo.lock" "$DEST/"
fi

# cargo package extracts a crate, not a workspace. Make cargo rustc happy
# when the tarball is the only tree a FetchContent consumer unpacks.
if ! grep -q '^\[workspace\]' "$DEST/Cargo.toml"; then
    printf '\n[workspace]\n' >> "$DEST/Cargo.toml"
fi

if [[ ! -f "$DEST/Cargo.lock" ]]; then
    cargo generate-lockfile --manifest-path "$DEST/Cargo.toml"
fi

cat > "$DEST/README.cxx.md" <<EOF
# readcon-core ${VERSION} (C/C++ source tarball)

This archive is the CMake FetchContent / Meson wrap source for the
readcon-core C ABI. Headers in \`include/\` are pre-generated. **cbindgen
is not required** and must not be invoked to consume this tarball.

## CMake (FetchContent)

\`\`\`cmake
include(FetchContent)
FetchContent_Declare(
  readcon-core
  URL      https://github.com/lode-org/readcon-core/releases/download/v${VERSION}/readcon-core-cxx-${VERSION}.tar.gz
  URL_HASH SHA256=<sha256 of this file>
)
FetchContent_MakeAvailable(readcon-core)
target_link_libraries(app PRIVATE readcon-core::shared)
\`\`\`

Or as a git subdirectory / \`add_subdirectory\`. After \`cmake --install\`:

\`\`\`cmake
find_package(readcon-core ${VERSION} REQUIRED CONFIG)
pkg_check_modules(READCON REQUIRED IMPORTED_TARGET readcon-core)
\`\`\`

Requires Rustc/cargo (the library is compiled from the vendored or crates.io
sources). It does **not** require cbindgen or Corrosion.

## Meson (wrap)

\`\`\`meson
readcon_dep = dependency('readcon-core')
\`\`\`

with a \`subprojects/readcon-core.wrap\` pointing at this tarball
(\`dependency_names = readcon-core\`). \`meson install\` writes
\`\$prefix/lib/pkgconfig/readcon-core.pc\`.

## pkg-config

\`\`\`
pkg-config --cflags --libs readcon-core
\`\`\`
EOF

if [[ "$VENDOR" -eq 1 ]]; then
    mkdir -p "$DEST/.cargo"
    (
        cd "$DEST"
        cargo vendor --locked vendor
    )
    cat > "$DEST/.cargo/config.toml" <<'EOF'
[source.crates-io]
replace-with = "vendored-sources"

[source.vendored-sources]
directory = "vendor"
EOF
fi

# Drop crate-only trees. Keep CMake/Meson consume tests.
rm -rf "$DEST/tests" "$DEST/benches" "$DEST/benchmarks" "$DEST/julia" \
    "$DEST/fortran" "$DEST/docs" "$DEST/addl" || true
mkdir -p "$DEST/tests"
cp -a "$ROOT_DIR/tests/cmake-project" "$DEST/tests/"
cp -a "$ROOT_DIR/tests/meson-wrap" "$DEST/tests/"

tar -C "$TMP_DIR" -cf "${TMP_DIR}/${ARCHIVE_NAME}.tar" "$ARCHIVE_NAME"
gzip -9 "${TMP_DIR}/${ARCHIVE_NAME}.tar"
cp "${TMP_DIR}/${ARCHIVE_NAME}.tar.gz" "${OUTPUT_DIR}/${ARCHIVE_NAME}.tar.gz"

SHA="$(sha256sum "${OUTPUT_DIR}/${ARCHIVE_NAME}.tar.gz" | awk '{print $1}')"
echo "${OUTPUT_DIR}/${ARCHIVE_NAME}.tar.gz"
echo "sha256:${SHA}"
echo "${SHA}" > "${OUTPUT_DIR}/${ARCHIVE_NAME}.tar.gz.sha256"

if [[ -f "$ROOT_DIR/packaging/wrapdb/readcon-core.wrap.in" ]]; then
    sed -e "s/@VERSION@/${VERSION}/g" -e "s/@SHA256@/${SHA}/g" \
        "$ROOT_DIR/packaging/wrapdb/readcon-core.wrap.in" \
        > "${OUTPUT_DIR}/readcon-core.wrap"
    echo "${OUTPUT_DIR}/readcon-core.wrap"
fi
