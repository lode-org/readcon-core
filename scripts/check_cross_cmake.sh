#!/usr/bin/env bash
# A cross cargo build must configure cmake with the target CC and CXX.
# The host libstdc++ toolchain file must not be selected. Linking the
# aarch64 crate is not required.
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
# shellcheck source=scripts/scratch.sh
source "$root/scripts/scratch.sh"
export RUSTUP_TOOLCHAIN="${RUSTUP_TOOLCHAIN:-stable}"
command -v gcc >/dev/null
command -v g++ >/dev/null
command -v rustup >/dev/null
triple=aarch64-unknown-linux-gnu
rustup target add "$triple" --toolchain "$RUSTUP_TOOLCHAIN"
work="$(scratch_dir)"
trap 'status=$?; if [[ $status -eq 0 ]]; then rm -rf "$work"; else echo "left $work" >&2; fi' EXIT

cat >"$work/cc" <<EOF
#!/bin/sh
printf '%s\n' "cc:\$0" >> "$work/invoked"
exec gcc "\$@"
EOF
cat >"$work/cxx" <<EOF
#!/bin/sh
printf '%s\n' "cxx:\$0" >> "$work/invoked"
exec g++ "\$@"
EOF
chmod +x "$work/cc" "$work/cxx"

set +e
env -u CXX -u CC -u LIBRARY_PATH -u RUSTFLAGS -u CMAKE_TOOLCHAIN_FILE \
    "CC_${triple}=$work/cc" \
    "CXX_${triple}=$work/cxx" \
    CARGO_TARGET_DIR="$work/target" \
    cargo build --manifest-path "$root/Cargo.toml" --locked \
    --features chemfiles --target "$triple" \
    >"$work/build.log" 2>&1
set -e

cache=$(find "$work/target" -name CMakeCache.txt -path '*chemfiles-sys*' | head -n 1)
if [[ -z "$cache" ]]; then
    echo "cmake did not configure" >&2
    tail -n 50 "$work/build.log" >&2
    exit 1
fi
c_compiler=$(sed -n 's/^CMAKE_C_COMPILER:.*=//p' "$cache" | head -n 1)
cxx_compiler=$(sed -n 's/^CMAKE_CXX_COMPILER:.*=//p' "$cache" | head -n 1)
toolchain=$(sed -n 's/^CMAKE_TOOLCHAIN_FILE:.*=//p' "$cache" | head -n 1)
printf 'CMAKE_C_COMPILER=%s\n' "$c_compiler"
printf 'CMAKE_CXX_COMPILER=%s\n' "$cxx_compiler"
printf 'CMAKE_TOOLCHAIN_FILE=%s\n' "${toolchain:-unset}"
[[ "$c_compiler" == "$work/cc" ]]
[[ "$cxx_compiler" == "$work/cxx" ]]
if [[ "$toolchain" == *libstdcxx.cmake* ]]; then
    echo "host toolchain file leaked into the cross configure" >&2
    exit 1
fi
grep -q "cc:$work/cc" "$work/invoked"
grep -q "cxx:$work/cxx" "$work/invoked"
