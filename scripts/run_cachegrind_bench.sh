#!/usr/bin/bash
# Cachegrind I-refs for docs. Prefer --features chemfiles when lib builds on the runner.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
OUT_DIR="${OUT_DIR:-$ROOT/docs/source/_generated}"
CG_DIR="${CG_DIR:-$ROOT/target/cachegrind}"
FEATURES="${CACHEGRIND_FEATURES:-chemfiles}"
mkdir -p "$OUT_DIR" "$CG_DIR"

echo "Building release harness (features=${FEATURES})..."
# shellcheck disable=SC2086
cargo build --release --example cachegrind_harness --features ${FEATURES}
BIN="$ROOT/target/release/examples/cachegrind_harness"
test -x "$BIN"

mapfile -t SCENARIOS < <("$BIN" list 2>/dev/null | grep -v '^#' || true)
if [[ ${#SCENARIOS[@]} -eq 0 ]]; then
  echo "harness list failed" >&2
  exit 1
fi
echo "Scenarios: ${SCENARIOS[*]}"

JSON="$OUT_DIR/cachegrind_results.json"
RST="$OUT_DIR/cachegrind_results.rst"
STAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
SHA="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"

run_cg() {
  local name="$1"
  local out="$CG_DIR/${name}.out"
  local log="$CG_DIR/${name}.log"
  valgrind --tool=cachegrind \
    --cachegrind-out-file="$out" \
    --branch-sim=no \
    --error-exitcode=0 \
    "$BIN" "$name" >"$log" 2>&1 || true
  local irefs
  irefs=$(grep -E 'I[[:space:]]+refs:' "$log" | tail -1 | sed -E 's/.*refs:[[:space:]]*([0-9,]+).*/\1/' | tr -d ',' || true)
  if [[ -z "${irefs:-}" || "$irefs" == "0" ]]; then
    if command -v cg_annotate >/dev/null && [[ -f "$out" ]]; then
      irefs=$(cg_annotate "$out" 2>/dev/null | grep -E 'I[[:space:]]+refs' | head -1 | awk '{print $3}' | tr -d ',' || true)
    fi
  fi
  echo "${irefs:-0}"
}

declare -A RESULTS
for s in "${SCENARIOS[@]}"; do
  echo "Cachegrind: $s"
  RESULTS[$s]=$(run_cg "$s")
  echo "  I refs = ${RESULTS[$s]}"
done

{
  echo "{"
  echo "  \"generated_at\": \"$STAMP\","
  echo "  \"git_sha\": \"$SHA\","
  echo "  \"features\": \"$FEATURES\","
  echo "  \"tool\": \"cachegrind\","
  echo "  \"metric\": \"I_refs\","
  echo "  \"scenarios\": {"
  first=1
  for s in "${SCENARIOS[@]}"; do
    [[ $first -eq 1 ]] || echo ","
    first=0
    printf '    "%s": %s' "$s" "${RESULTS[$s]}"
  done
  echo ""
  echo "  }"
  echo "}"
} >"$JSON"

python3 "$ROOT/scripts/render_cachegrind_rst.py"
echo "Wrote $JSON and $RST"
