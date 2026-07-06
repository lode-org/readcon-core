#!/usr/bin/env bash
# LLVM profile-guided optimization A/B for multi-frame CON parse.
# Run on a capable host (e.g. rgam5terra). Requires llvm-profdata + perf optional.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${OUT:-$ROOT/benches/results}"
WORKDIR="${WORKDIR:-/tmp/readcon-pgo-$$}"
FEATURES="${FEATURES:---features parallel}"
mkdir -p "$OUT" "$WORKDIR"/{raw,merged,tgt-nopgo,tgt-instr,tgt-pgo}
cd "$ROOT"
EXAMPLE=profile_train

echo "Non-PGO release..."
CARGO_TARGET_DIR="$WORKDIR/tgt-nopgo" cargo build --release --example "$EXAMPLE" $FEATURES
"$WORKDIR/tgt-nopgo/release/examples/$EXAMPLE" measure NOPGO "$OUT/pgo_nopgo.json"

echo "Instrumented train..."
CARGO_TARGET_DIR="$WORKDIR/tgt-instr" \
  RUSTFLAGS="-Cprofile-generate=$WORKDIR/raw" \
  cargo build --release --example "$EXAMPLE" $FEATURES
LLVM_PROFILE_FILE="$WORKDIR/raw/train-%p.profraw" \
  "$WORKDIR/tgt-instr/release/examples/$EXAMPLE" train
LLVM_PROFILE_FILE="$WORKDIR/raw/once-%p.profraw" \
  "$WORKDIR/tgt-instr/release/examples/$EXAMPLE" once
llvm-profdata merge -o "$WORKDIR/merged/default.profdata" "$WORKDIR/raw"

echo "PGO rebuild..."
CARGO_TARGET_DIR="$WORKDIR/tgt-pgo" \
  RUSTFLAGS="-Cprofile-use=$WORKDIR/merged/default.profdata -Cllvm-args=-pgo-warn-missing-function" \
  cargo build --release --example "$EXAMPLE" $FEATURES
"$WORKDIR/tgt-pgo/release/examples/$EXAMPLE" measure PGO "$OUT/pgo_pgo.json"

python3 - <<PY
import json, math
from pathlib import Path
out = Path("$OUT")
a = json.loads((out/"pgo_nopgo.json").read_text())
b = json.loads((out/"pgo_pgo.json").read_text())
rows = []
for x, y in zip(a["cases"], b["cases"]):
    sp = x["median_s"] / max(y["median_s"], 1e-15)
    rows.append({"case": x["case"], "nopgo_ms": x["median_s"]*1e3, "pgo_ms": y["median_s"]*1e3, "speedup": sp})
    print(f"{rows[-1]['case']}: {rows[-1]['nopgo_ms']:.3f} -> {rows[-1]['pgo_ms']:.3f} ms ({sp:.3f}x)")
sps = [r["speedup"] for r in rows]
g = math.exp(sum(math.log(s) for s in sps)/len(sps))
print(f"geomean {g:.3f}x")
(out/"pgo_ab_cmp.json").write_text(json.dumps({"cases": rows, "geomean": g}, indent=2)+"\n")
PY
