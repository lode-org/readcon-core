#!/usr/bin/env bash
# CPC Applications vignette: print neb_band.con, lock the TSV, optional
# readcon-db ingest + neb_bead select.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CON="$ROOT/resources/examples/neb_band.con"
TSV="$ROOT/resources/examples/neb_band.tsv"

python3 "$ROOT/scripts/print_neb_band.py" "$CON" | python3 - "$TSV" <<'PY'
import sys
from pathlib import Path

tsv = Path(sys.argv[1]).read_text().splitlines()
got = [ln for ln in sys.stdin.read().splitlines() if ln and not ln.startswith("#")]
if got != tsv:
    print("ERROR: print_neb_band.py does not match", sys.argv[1], file=sys.stderr)
    print("want:", tsv, file=sys.stderr)
    print("got: ", got, file=sys.stderr)
    raise SystemExit(1)
print("OK print matches", sys.argv[1])
for line in got[1:]:
    print(line)
PY

if command -v readcon-db >/dev/null 2>&1; then
  tmp=$(mktemp -d)
  trap 'rm -rf "$tmp"' EXIT
  readcon-db ingest "$tmp" "$CON"
  echo "OK ingest $CON"
  out=$(readcon-db select "$tmp" --neb-bead-min 0 --neb-bead-max 3)
  echo "$out"
  n=$(printf '%s\n' "$out" | grep -c . || true)
  if [[ "$n" -lt 4 ]]; then
    echo "ERROR: expected at least 4 neb_bead keys, got ${n}" >&2
    exit 1
  fi
  echo "OK readcon-db select neb_bead 0-3 -> ${n} keys"
else
  echo "SKIP readcon-db: CLI not on PATH"
fi
