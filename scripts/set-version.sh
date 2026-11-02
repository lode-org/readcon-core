#!/usr/bin/env bash
# Compatibility name for scripts/bump-version.sh.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec bash "$ROOT/scripts/bump-version.sh" "$@"
