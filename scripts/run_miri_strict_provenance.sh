#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

TOOLCHAIN="${RUSTUP_TOOLCHAIN:-nightly-2026-11-16}"
COMMON_FLAGS="-Zmiri-strict-provenance -Zmiri-disable-isolation"
BASE_FLAGS="${MIRIFLAGS:-}"

run_suite() {
  local model_flags="$1"
  local flags
  flags="${BASE_FLAGS} ${COMMON_FLAGS} ${model_flags}"

  MIRIFLAGS="${flags}" cargo +"${TOOLCHAIN}" miri test --locked \
    --features static_system_alloc \
    --test parseforces -- --test-threads=1

  MIRIFLAGS="${flags}" cargo +"${TOOLCHAIN}" miri test --locked \
    --features static_system_alloc \
    --lib detaching_external_tail_clears_the_arena_pointer -- --test-threads=1

  MIRIFLAGS="${flags}" cargo +"${TOOLCHAIN}" miri test --locked \
    --features static_system_alloc \
    --lib materializing_section_slots_rehomes_external_column_values -- --test-threads=1

  MIRIFLAGS="${flags}" cargo +"${TOOLCHAIN}" miri test --locked \
    --features static_system_alloc \
    --lib detach_then_install_keeps_tail_ownership_valid -- --test-threads=1

  MIRIFLAGS="${flags}" cargo +"${TOOLCHAIN}" miri test --locked \
    --features static_system_alloc \
    --test frame_edit_roundtrip -- --test-threads=1
}

# Stacked Borrows (default model)
run_suite ""
# Tree Borrows
run_suite "-Zmiri-tree-borrows"
