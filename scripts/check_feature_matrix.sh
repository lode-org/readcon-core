#!/usr/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
FEATURES="${FEATURES:?set FEATURES=...}"
PROFILE="${PROFILE:-release}"
TARGET_DIR="${CARGO_TARGET_DIR:-$ROOT/target}"
LIB="${LIB:-$TARGET_DIR/$PROFILE/libreadcon_core.so}"
MANIFEST="$ROOT/tests/capi_symbols.txt"
HEADER="$ROOT/include/readcon-core.h"
MPI_HEADER="$ROOT/include/readcon-core-mpi.h"

PROFILE_ARGS=()
if [[ "$PROFILE" == "release" ]]; then
  PROFILE_ARGS=(--release)
elif [[ "$PROFILE" != "debug" ]]; then
  PROFILE_ARGS=(--profile "$PROFILE")
fi

has_feature() {
  [[ "$FEATURES" == "all" || "$FEATURES" == "all-features" || ",${FEATURES}," == *",$1,"* ]]
}

if [[ "$FEATURES" == "default" ]]; then
  cargo build "${PROFILE_ARGS[@]}" --lib
elif [[ "$FEATURES" == "all" || "$FEATURES" == "all-features" ]]; then
  cargo build "${PROFILE_ARGS[@]}" --all-features --lib
else
  # shellcheck disable=SC2086
  cargo build "${PROFILE_ARGS[@]}" --features "${FEATURES}" --lib
fi

if [[ ! -f "$LIB" ]]; then
  echo "MISSING library: $LIB" >&2
  exit 1
fi

nm_out=$(nm -D --defined-only "$LIB")
if [[ -n "$nm_out" ]]; then
  actual_syms=$(printf '%s\n' "$nm_out" | awk '{print $NF}' | sed 's/@.*//' | LC_ALL=C sort -u)
  count=$(printf '%s\n' "$actual_syms" | wc -l)
else
  actual_syms=""
  count=0
fi

compare_syms() {
  local expected="$1"
  local actual="$2"
  diff -u \
    <(if [[ -n "$expected" ]]; then printf '%s\n' "$expected"; fi) \
    <(if [[ -n "$actual" ]]; then printf '%s\n' "$actual"; fi)
}

if ! has_feature "capi"; then
  echo "== matrix check FEATURES=$FEATURES (no capi) LIB=$LIB =="
  if has_feature "python"; then
    expected_syms="PyInit_readcon"
  else
    expected_syms=""
  fi
  if ! compare_syms "$expected_syms" "$actual_syms"; then
    echo "UNEXPECTED exported symbols in non-capi build (FEATURES=$FEATURES)" >&2
    exit 1
  fi
  echo "  ok $count expected symbol(s), 0 C ABI symbols"
  echo "OK matrix $FEATURES (no capi, 0 C ABI exports)"
  exit 0
fi

echo "== matrix check FEATURES=$FEATURES LIB=$LIB =="

if [[ ! -f "$MANIFEST" ]]; then
  echo "MISSING expected symbol manifest: $MANIFEST" >&2
  exit 1
fi

# Verify every expected C ABI symbol is declared in the shipped headers.
while IFS= read -r sym; do
  [[ -z "$sym" || "$sym" == \#* ]] && continue
  if [[ "$sym" == "rkr_block_range" ]]; then
    grep -q "$sym" "$MPI_HEADER" || {
      echo "shipped MPI header missing $sym" >&2
      exit 1
    }
  else
    grep -q "$sym" "$HEADER" || {
      echo "shipped header missing $sym" >&2
      exit 1
    }
  fi
done < "$MANIFEST"

expected_syms=$(
  {
    grep -v -E '^[[:space:]]*(#|$)' "$MANIFEST"
    if has_feature "mpi"; then
      printf '%s\n' \
        rkr_mpi_comm_info_f \
        rkr_mpi_read_block_f \
        rkr_mpi_rewrite_block_f \
        rkr_mpi_write_block_f
    fi
    if has_feature "python"; then
      printf '%s\n' PyInit_readcon
    fi
  } | LC_ALL=C sort -u
)

if ! compare_syms "$expected_syms" "$actual_syms"; then
  echo "C ABI export set mismatch for FEATURES=$FEATURES" >&2
  exit 1
fi
echo "  ok exact match: $count exported symbol(s)"

if has_feature "metatensor"; then
  if [[ ! -f "$TARGET_DIR/$PROFILE/readcon-metatensor.env" ]]; then
    # If build.rs ran before metatensor-sys finished installing, rerun it
    # now that build/metatensor-sys/<hash>/out exists.
    touch "$ROOT/build.rs"
    if [[ "$FEATURES" == "all" || "$FEATURES" == "all-features" ]]; then
      cargo build "${PROFILE_ARGS[@]}" --all-features --lib
    else
      cargo build "${PROFILE_ARGS[@]}" --features "${FEATURES}" --lib
    fi
  fi
  test -f "$TARGET_DIR/$PROFILE/readcon-metatensor.env"
  echo "  ok readcon-metatensor.env"
fi

echo "OK matrix $FEATURES (manifest + shipped headers + nm, no cbindgen)"
