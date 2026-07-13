#!/usr/bin/env bash
# Instrument src/python.rs via cargo-llvm-cov + maturin + pytest, emit LCOV.
#
# pytest-cov alone only sees a thin pure-Python __init__.py (PyO3 extension),
# which Codecov maps poorly and reports as 0% for the python flag. This path
# drives the real PyO3 surface and attributes hits to src/python.rs.
#
# Critical: cargo-llvm-cov show-env sets RUSTC_WRAPPER=cargo-llvm-cov to inject
# -Cinstrument-coverage. Do NOT clear RUSTC_WRAPPER after sourcing show-env
# (that was the prior bug: maturin built an uninstrumented extension → no
# profraw → empty report).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
OUT="${1:-python_lcov.info}"
FEATURES="${READCON_PY_FEATURES:-python,chemfiles}"

# Drop only real build caches (sccache), not the llvm-cov rustc wrapper.
unset SCCACHE_GHA_ENABLED || true
if [[ "${RUSTC_WRAPPER:-}" == *sccache* ]]; then
  unset RUSTC_WRAPPER || true
fi
export CARGO_INCREMENTAL=0

if [[ -z "${CC:-}" ]] && command -v clang >/dev/null 2>&1; then
  export CC=clang CXX="${CXX:-clang++}"
fi
if [[ -z "${PYO3_PYTHON:-}" ]] && command -v python3 >/dev/null 2>&1; then
  export PYO3_PYTHON="$(command -v python3)"
fi

echo "==> python binding coverage (features=${FEATURES})"
cargo llvm-cov clean --workspace 2>/dev/null || true

# Prefer --sh (export-prefix is a deprecated alias).
# shellcheck disable=SC1090
source <(cargo llvm-cov show-env --sh 2>/dev/null || cargo llvm-cov show-env --export-prefix)

# show-env sets RUSTC_WRAPPER to cargo-llvm-cov; keep it.
if [[ -z "${RUSTC_WRAPPER:-}" ]] || [[ "${RUSTC_WRAPPER}" == *sccache* ]]; then
  echo "ERROR: RUSTC_WRAPPER must be cargo-llvm-cov after show-env (got: ${RUSTC_WRAPPER:-empty})" >&2
  exit 1
fi
echo "    RUSTC_WRAPPER=${RUSTC_WRAPPER}"
echo "    LLVM_PROFILE_FILE=${LLVM_PROFILE_FILE:-unset}"

VENV="${READCON_PY_VENV:-$ROOT/.venv-coverage-python}"
if [[ ! -d "$VENV" ]]; then
  "${PYO3_PYTHON:-python3}" -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"
python -m pip install -U pip -q
# ase exercises ConFrame.to_ase/from_ase (large python.rs surface); without it
# pytest.importorskip skips tests/python/test_ase.py and coverage collapses.
python -m pip install maturin pytest numpy ase -q

# Append linker flag without dropping instrumentation (wrapper owns flags).
# Use CARGO_TARGET_* / RUSTFLAGS only for link args if wrapper is active.
case " ${RUSTFLAGS:-} " in
  *" -C link-arg=-fuse-ld=bfd "*) ;;
  *) export RUSTFLAGS="${RUSTFLAGS:-} -C link-arg=-fuse-ld=bfd" ;;
esac
# Also pass via maturin env; some maturin paths only see RUSTFLAGS.
export MATURIN_PEP517_ARGS="${MATURIN_PEP517_ARGS:-}"

# shellcheck disable=SC2086
maturin develop --features ${FEATURES}

# Optional emacs for tutorial tests — soft-fail if missing
set +e
python -m pytest tests/python/ -q --tb=line
PY_RC=$?
set -e
if [[ "$PY_RC" -ne 0 ]]; then
  echo "WARNING: pytest exit $PY_RC; still collecting llvm-cov for python.rs" >&2
fi

# Ensure shared-lib profiles are flushed (normally on process exit; re-run a
# short python one-shot that imports and exits if no profraw yet).
PROF_GLOB="${CARGO_LLVM_COV_TARGET_DIR:-$ROOT/target}"
if ! compgen -G "${PROF_GLOB}"/*.profraw > /dev/null 2>&1 \
   && ! compgen -G "${ROOT}/target"/*.profraw > /dev/null 2>&1; then
  echo "    no profraw yet; probing import flush" >&2
  python -c 'import readcon; print("readcon", readcon.__file__)'
fi

# Full report then filter to src/python.rs (rustc regex has no lookaround)
TMP_LCOV="$(mktemp)"
cargo llvm-cov report --lcov --output-path "$TMP_LCOV"
python3 - "$TMP_LCOV" "$OUT" <<'PY'
import sys
inp, outp = sys.argv[1], sys.argv[2]
keep = False
buf = []
out = []
for line in open(inp, encoding="utf-8", errors="replace"):
    if line.startswith("SF:"):
        if buf and keep:
            out.extend(buf)
        buf = [line]
        path = line[3:].strip()
        keep = path.endswith("src/python.rs") or path.endswith("/python.rs")
    elif line.startswith("end_of_record"):
        buf.append(line)
        if keep:
            out.extend(buf)
        buf = []
        keep = False
    else:
        if buf is not None:
            buf.append(line)
if buf and keep:
    out.extend(buf)
text = "".join(out)
if "SF:" not in text:
    raise SystemExit("no src/python.rs records in llvm-cov report — was the extension instrumented?")
open(outp, "w", encoding="utf-8").write(text)
hits = tot = 0
for line in text.splitlines():
    if line.startswith("DA:"):
        h = int(line.split(":")[1].split(",")[1])
        tot += 1
        if h > 0:
            hits += 1
print(f"python.rs lcov {100*hits/tot:.1f}% {hits}/{tot}")
if tot == 0:
    raise SystemExit("empty python.rs LCOV")
PY
rm -f "$TMP_LCOV"
test -s "$OUT"
echo "OK wrote $OUT"
