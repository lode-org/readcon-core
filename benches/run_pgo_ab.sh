#!/usr/bin/env bash
# Build a PGO-optimized profile_train binary (train workload only).
# Does not print wall-clock medians or speedups.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORKDIR="${WORKDIR:-/tmp/readcon-pgo-$$}"
FEATURES="${FEATURES:---features parallel}"
mkdir -p "$WORKDIR"/{raw,merged,tgt-instr,tgt-pgo}
cd "$ROOT"
EXAMPLE=profile_train

echo "Instrumented train build..."
CARGO_TARGET_DIR="$WORKDIR/tgt-instr" \
  RUSTFLAGS="-Cprofile-generate=$WORKDIR/raw" \
  cargo build --release --example "$EXAMPLE" $FEATURES
LLVM_PROFILE_FILE="$WORKDIR/raw/train-%p.profraw" \
  "$WORKDIR/tgt-instr/release/examples/$EXAMPLE" train
LLVM_PROFILE_FILE="$WORKDIR/raw/once-%p.profraw" \
  "$WORKDIR/tgt-instr/release/examples/$EXAMPLE" once
llvm-profdata merge -o "$WORKDIR/merged/default.profdata" "$WORKDIR/raw"

echo "PGO-optimized rebuild..."
CARGO_TARGET_DIR="$WORKDIR/tgt-pgo" \
  RUSTFLAGS="-Cprofile-use=$WORKDIR/merged/default.profdata -Cllvm-args=-pgo-warn-missing-function" \
  cargo build --release --example "$EXAMPLE" $FEATURES
echo "PGO binary: $WORKDIR/tgt-pgo/release/examples/$EXAMPLE"
echo "Default cargo release does not use this profile; this is an opt-in build only."
