#!/usr/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
FEATURES="${FEATURES:?set FEATURES=...}"
PROFILE="${PROFILE:-release}"
LIB="$ROOT/target/$PROFILE/libreadcon_core.so"
# shellcheck disable=SC2086
cargo build --"$PROFILE" --features ${FEATURES}

has() { nm "$LIB" 2>/dev/null | grep -E "[[:space:]]T[[:space:]]+$1(@@|$)" >/dev/null; }

echo "== matrix check FEATURES=$FEATURES LIB=$LIB =="

for s in create_writer_from_path_c create_writer_gzip_c create_writer_zstd_c \
         rkr_dlpack_delete rkr_frame_builder_positions_dlpack \
         rkr_frame_metatensor_positions_block rkr_mts_block_free; do
  if has "$s"; then
    echo "  ok $s"
  else
    echo "MISSING $s"
    nm "$LIB" | grep -F "$s" | head -3 || true
    exit 1
  fi
done

if [[ "$FEATURES" == *metatensor* ]]; then
  if [[ ! -f "$ROOT/target/$PROFILE/readcon-metatensor.env" ]]; then
    # shellcheck disable=SC2086
    cargo build --"$PROFILE" --features ${FEATURES}
  fi
  test -f "$ROOT/target/$PROFILE/readcon-metatensor.env"
  echo "  ok readcon-metatensor.env"
fi

bash scripts/regen-capi-headers.sh --check
echo "OK matrix $FEATURES"
