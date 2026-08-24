#!/usr/bin/env bash
# rpc feature must stay free of UCX/libfabric. Those fabrics are optional
# later adapters when a campaign consumer exists (not a hard dep).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TOML="$ROOT/Cargo.toml"

# The rpc feature list and [dependencies] must not name a UCX crate.
if awk '
  /^\[features\]/ {f=1; next}
  f && /^\[/ {f=0}
  f && /^rpc[[:space:]]*=/ {print}
' "$TOML" | grep -qiE 'ucx|libfabric|ucx-sys'; then
  echo "ERROR: Cargo.toml rpc feature lists a UCX crate" >&2
  exit 1
fi

if awk '
  /^\[dependencies\]/ {d=1; next}
  d && /^\[/ {d=0}
  d {print}
' "$TOML" | grep -qiE '^ucx|^ucx-sys|^libfabric'; then
  echo "ERROR: Cargo.toml [dependencies] names a UCX crate" >&2
  exit 1
fi

# Endpoint dispatch is TCP and Unix only.
if grep -nE 'Endpoint::Ucx|unix::ucx|libucx' "$ROOT/src/rpc"/*.rs "$ROOT/src/rpc"/**/*.rs 2>/dev/null \
  | grep -v 'UCX/libfabric/ADIOS are not transports'; then
  echo "ERROR: rpc sources name a UCX endpoint" >&2
  exit 1
fi

echo "OK: rpc feature has no UCX dependency"
