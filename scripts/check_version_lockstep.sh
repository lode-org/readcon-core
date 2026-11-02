#!/usr/bin/env bash
# Compatibility name for scripts/check_version_sot.sh.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec bash "$ROOT/scripts/check_version_sot.sh"
