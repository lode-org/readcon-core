#!/usr/bin/env bash
# Build the library and run the Python and C examples in tests/doc_examples.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export RUSTUP_TOOLCHAIN="${RUSTUP_TOOLCHAIN:-1.88.0}"

cargo build --release --lib
cargo test --release --test doc_release_notes -- --test-threads=1
lib="$ROOT/target/release"
export LD_LIBRARY_PATH="${lib}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

shopt -s nullglob
for src in "$ROOT"/tests/doc_examples/*.c; do
    name="$(basename "$src" .c)"
    gcc -std=c11 -Wall -Wextra -Werror -I"$ROOT/include" "$src" -o "$work/$name" \
        -L"$lib" -lreadcon_core -ldl -lpthread -lm
    "$work/$name" "$work"
    echo "OK: $name"
done

py=()
if python3 -c 'import readcon' >/dev/null 2>&1; then
    py=(python3)
else
    python3 -m venv "$work/venv"
    # maturin develop looks up VIRTUAL_ENV. The venv's bin directory is not enough.
    export VIRTUAL_ENV="$work/venv"
    export PATH="$VIRTUAL_ENV/bin:$PATH"
    pip install --disable-pip-version-check maturin
    maturin develop --release --features python
    py=("$VIRTUAL_ENV/bin/python")
fi
for src in "$ROOT"/tests/doc_examples/*.py; do
    "${py[@]}" "$src"
    echo "OK: $(basename "$src")"
done
