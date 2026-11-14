#!/usr/bin/env bash
# Assemble a C/C++ source tarball that CMake FetchContent and Meson wrap
# can consume without cbindgen, Corrosion, or git.
#
# Layout (featomic / metatensor-core-cxx convention):
#   readcon-core-cxx-$VERSION/
#     Cargo.toml Cargo.lock VERSION src/ include/ build.rs
#     CMakeLists.txt cmake/ meson.build meson_options.txt
#     scripts/meson_cargo_build.py
#     examples/c_api_sample.c examples/cpp_api_sample.cpp examples/meson.build
#     resources/test/tiny_multi_cuh2.con
#     LICENSE README.cxx.md
#     [.cargo/config.toml + vendor/ when --vendor]
#
# Usage:
#   scripts/package-cxx.sh <output-dir> [--vendor] [--source-root DIR]
#
# --source-root packs DIR instead of the repo that contains this script.
# A workflow_dispatch backfill checks the tag out in one directory and
# runs this script from a newer commit.
set -euo pipefail
# shellcheck source=scripts/scratch.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/scratch.sh"

if [[ $# -lt 1 ]]; then
    echo "usage: $0 OUTPUT_DIR [--vendor] [--source-root DIR]" >&2
    exit 2
fi

OUTPUT_DIR="$1"
shift
VENDOR=0
SOURCE_ROOT=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --vendor) VENDOR=1 ;;
        --source-root)
            if [[ $# -lt 2 ]]; then
                echo "usage: $0 OUTPUT_DIR [--vendor] [--source-root DIR]" >&2
                exit 2
            fi
            SOURCE_ROOT="$2"
            shift
            ;;
        *)
            echo "usage: $0 OUTPUT_DIR [--vendor] [--source-root DIR]" >&2
            exit 2
            ;;
    esac
    shift
done

mkdir -p "$OUTPUT_DIR"
OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -n "$SOURCE_ROOT" ]]; then
    ROOT_DIR="$(cd "$SOURCE_ROOT" && pwd)"
else
    ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
fi

# cargo package rewrites [package.metadata] in an order that changed
# after Rust 1.88. That rewrite is inside the cxx archive, so the digest
# follows the cargo that packaged it. The v0.23.0 pin was recorded with
# 1.88.0. Stay on that toolchain.
export RUSTUP_TOOLCHAIN=1.88.0

# Git Bash `pwd` is /d/a/... . Windows pathlib turns that into \d\a\... and
# drops the drive letter. cygpath -w is D:\a\..., which pathlib keeps. The
# path is an argument so those backslashes are not Python string escapes.
version_file="$ROOT_DIR/VERSION"
if command -v cygpath >/dev/null 2>&1; then
    version_file="$(cygpath -w "$version_file")"
fi
VERSION="$(
    python3 -c 'import pathlib, sys; print(pathlib.Path(sys.argv[1]).read_text().strip(), end="")' \
        "$version_file"
)"
if [[ "$VENDOR" -eq 1 ]]; then
    ARCHIVE_NAME="readcon-core-cxx-${VERSION}-vendor"
else
    ARCHIVE_NAME="readcon-core-cxx-${VERSION}"
fi

# Committed source-date-epoch pin when one is present, else the v$VERSION
# tag or HEAD. Exported before cargo package so the crate and the outer
# archive share it. A container bind-mount is marked safe.directory.
SOURCE_DATE_EPOCH="$(bash "$SCRIPT_DIR/source-date-epoch.sh" "$ROOT_DIR")"
export SOURCE_DATE_EPOCH

TMP_DIR="$(scratch_dir)"
trap 'rm -rf "$TMP_DIR"' EXIT

DEST="${TMP_DIR}/${ARCHIVE_NAME}"
mkdir -p "$DEST"/{cmake,include,src,scripts,examples,resources/test}

# Crate sources: cargo package for a clean, publish-shaped tree, then overlay
# the CMake/Meson install surface cargo package does not treat as crate files.
cd "$ROOT_DIR"
# A dirty tree is not the checkout CI packages. --allow-dirty made a local
# pin disagree with that digest.
cargo package --no-verify --package readcon-core
CRATE_TAR="$(ls -1 "$ROOT_DIR"/target/package/readcon-core-"${VERSION}".crate)"
mkdir -p "${TMP_DIR}/crate"
tar -C "${TMP_DIR}/crate" -xf "$CRATE_TAR"
CRATE_DIR="$(find "${TMP_DIR}/crate" -mindepth 1 -maxdepth 1 -type d | head -1)"

cp -a "${CRATE_DIR}/." "$DEST/"
# Maintainer-only; the tarball ships include/ and must not look cbindgen-gated.
rm -f "$DEST/cbindgen.toml"

# Overlay the C/C++ distribution files (always, even if cargo package omitted them).
cp -a "$ROOT_DIR/VERSION" "$DEST/"
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

# cargo package drops [patch]. The lockfile records metatensor-sys as the
# path crate under third_party/, and the CMake build passes --locked.
# Put the patch back or that build cannot resolve the package.
if ! grep -q '^\[patch\.crates-io\]' "$DEST/Cargo.toml"; then
    cat >> "$DEST/Cargo.toml" <<'EOF'

[patch.crates-io]
metatensor-sys = { path = "third_party/metatensor-sys" }
EOF
fi
if [[ ! -d "$DEST/third_party/metatensor-sys" ]]; then
    mkdir -p "$DEST/third_party"
    cp -a "$ROOT_DIR/third_party/metatensor-sys" "$DEST/third_party/"
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
rm -rf "$DEST/tests" "$DEST/bench" "$DEST/benches" "$DEST/benchmarks" "$DEST/fuzz" \
    "$DEST/julia" "$DEST/fortran" "$DEST/docs" "$DEST/addl" || true
# The wrap digest names this archive. Leaving that file inside the archive
# makes the digest change every time the file is updated.
rm -rf "$DEST/packaging/wrapdb" || true
# cargo package records the git commit. That would change the digest of the
# commit that records the digest.
rm -f "$DEST/.cargo_vcs_info.json" || true
# A bytecode cache records the absolute path of the tree that imported it.
find "$DEST" -depth -type d -name '__pycache__' -exec rm -rf {} +
find "$DEST" -type f -name '*.pyc' -delete
mkdir -p "$DEST/tests"
cp -a "$ROOT_DIR/tests/cmake-project" "$DEST/tests/"
cp -a "$ROOT_DIR/tests/meson-wrap" "$DEST/tests/"

# Sorted names, uid 0, SOURCE_DATE_EPOCH, and gzip -n. Two builds of one
# tree share a digest. The wrap pin is not a member of this archive.
bash "$SCRIPT_DIR/reproducible-tar.sh" \
    "$ROOT_DIR" \
    "$TMP_DIR" \
    "$ARCHIVE_NAME" \
    "${TMP_DIR}/${ARCHIVE_NAME}.tar.gz"
cp "${TMP_DIR}/${ARCHIVE_NAME}.tar.gz" "${OUTPUT_DIR}/${ARCHIVE_NAME}.tar.gz"

if command -v sha256sum >/dev/null 2>&1; then
    SHA="$(sha256sum "${OUTPUT_DIR}/${ARCHIVE_NAME}.tar.gz" | awk '{print $1}')"
elif command -v shasum >/dev/null 2>&1; then
    SHA="$(shasum -a 256 "${OUTPUT_DIR}/${ARCHIVE_NAME}.tar.gz" | awk '{print $1}')"
else
    SHA="$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "${OUTPUT_DIR}/${ARCHIVE_NAME}.tar.gz")"
fi
echo "${OUTPUT_DIR}/${ARCHIVE_NAME}.tar.gz"
echo "sha256:${SHA}"
echo "${SHA}" > "${OUTPUT_DIR}/${ARCHIVE_NAME}.tar.gz.sha256"

# A Meson wrap for this archive only. The filename is the archive name, so a
# vendor build cannot replace the slim wrap. These files are build provenance.
# The release directory copied by cxx_tarball.yml does not include them.
if [[ "$VENDOR" -eq 0 && ! -f "$ROOT_DIR/packaging/wrapdb/readcon-core.wrap.in" ]]; then
    echo "missing packaging/wrapdb/readcon-core.wrap.in" >&2
    exit 1
fi
if [[ "$VENDOR" -eq 1 ]]; then
    WRAP_NAME="readcon-core-cxx-${VERSION}-vendor.wrap"
    cat > "${OUTPUT_DIR}/${WRAP_NAME}" <<EOF
# archive = readcon-core-cxx-${VERSION}-vendor.tar.gz
[wrap-file]
directory = readcon-core-cxx-${VERSION}-vendor
source_url = https://github.com/lode-org/readcon-core/releases/download/v${VERSION}/readcon-core-cxx-${VERSION}-vendor.tar.gz
source_filename = readcon-core-cxx-${VERSION}-vendor.tar.gz
source_hash = ${SHA}

[provide]
dependency_names = readcon-core
EOF
else
    WRAP_NAME="readcon-core-cxx-${VERSION}.wrap"
    {
        echo "# archive = readcon-core-cxx-${VERSION}.tar.gz"
        sed -e "s/@VERSION@/${VERSION}/g" -e "s/@SHA256@/${SHA}/g" \
            "$ROOT_DIR/packaging/wrapdb/readcon-core.wrap.in"
    } > "${OUTPUT_DIR}/${WRAP_NAME}"
fi
echo "${OUTPUT_DIR}/${WRAP_NAME}"
