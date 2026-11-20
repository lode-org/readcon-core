#!/usr/bin/env bash
# ThreadSanitizer stress for the free-threaded Python extension.
#
# Builds readcon with an instrumented std and an instrumented rayon
# (`-Zbuild-std=std,panic_abort` and `-Zsanitizer=thread`), installs it
# into the selected free-threaded interpreter, and runs
# tests/python/tsan_writer_stress.py. That script calls
# read_con(..., n_threads=2), which parses through parse_into_slots_timed.
#
# rustc's TSan runtime is a static archive with local-exec TLS, so it
# cannot be a shared object and cannot be preloaded. The extension's
# __tsan_* calls are undefined in the cdylib. This script links that
# archive, from the same rustc that built the extension, into
# scripts/tsan_python_launcher.c with --export-dynamic. The launcher
# dlopens libpython and calls Py_BytesMain, and the extension binds its
# instrumentation to the symbols the launcher exports.
#
# The canary in src/tsan_canary.rs is compiled only for this build. The
# script links the launcher twice. The first link has no TSan archive.
# That process must fail, and its log must not contain a stack frame
# whose symbol is exactly rkr_tsan_canary_race. System libtsan still
# reports the canary, so the control is the missing archive, not a
# different runtime. The second link has the archive. Its log must
# contain the frame `#0 rkr_tsan_canary_race`. A closure frame
# `rkr_tsan_canary_race::...` does not match. The canary run does not
# load tests/tsan.supp.
#
# tests/tsan.supp holds the CPython-only rules. The stress run loads
# that file. The rules name CPython frames. A stack that does not name
# those frames is not suppressed.
#
# Usage:
#   scripts/run_tsan_python_stress.sh /path/to/python3.13t
#   PYTHON=/path/to/python3.14t scripts/run_tsan_python_stress.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ $# -ge 1 ]]; then
  PYTHON="$1"
  shift
fi
PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "run_tsan_python_stress: python not found: $PYTHON" >&2
  exit 1
fi

TARGET_DIR="${CARGO_TARGET_DIR:-${ROOT}/target/tsan-python}"
mkdir -p "$TARGET_DIR"

# rustc must not itself run under a sanitizer runtime.
unset LD_PRELOAD || true
unset TSAN_OPTIONS || true

export RUSTUP_TOOLCHAIN="${RUSTUP_TOOLCHAIN:-nightly}"
export CARGO_TARGET_DIR="$TARGET_DIR"
export CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_RUSTFLAGS="${CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_RUSTFLAGS:--Zsanitizer=thread --cfg tsan_run -Cunsafe-allow-abi-mismatch=sanitizer}"

VENV="${READCON_TSAN_VENV:-${TARGET_DIR}/venv}"
if [[ ! -x "$VENV/bin/python" ]]; then
  "$PYTHON" -m venv "$VENV"
  "$VENV/bin/python" -m pip install -U pip maturin numpy
fi

VIRTUAL_ENV="$VENV" "$VENV/bin/maturin" develop --release \
  --target x86_64-unknown-linux-gnu \
  --features python,zstd \
  -Z build-std=std,panic_abort

SYSROOT="$(rustc --print sysroot)"
RT="$(find "$SYSROOT/lib/rustlib" -name 'librustc*_rt.tsan.a' -print -quit)"
if [[ -z "$RT" || ! -f "$RT" ]]; then
  echo "run_tsan_python_stress: rustc TSan runtime not found under $SYSROOT" >&2
  exit 1
fi

real_python="$(readlink -f "$VENV/bin/python")"
prefix="$(cd "$(dirname "$real_python")/.." && pwd)"
shopt -s nullglob
libpython_candidates=("$prefix"/lib/libpython3.*t.so)
libpython_static_candidates=("$prefix"/lib/libpython3.*t.a)
shopt -u nullglob
launcher_mode="dynamic"
if [[ ${#libpython_candidates[@]} -eq 0 ]]; then
  if [[ ${#libpython_static_candidates[@]} -eq 0 ]]; then
    echo "run_tsan_python_stress: libpython not found under $prefix/lib" >&2
    exit 1
  fi
  launcher_mode="static"
  LIBPYTHON_STATIC="${libpython_static_candidates[0]}"
else
  LIBPYTHON="${libpython_candidates[0]}"
fi

LAUNCHER="$TARGET_DIR/tsan_python_launcher"
NORUNTIME="$TARGET_DIR/tsan_python_launcher_noruntime"
LAUNCHER_OBJ="$TARGET_DIR/tsan_python_launcher.o"
if [[ "$launcher_mode" == "static" ]]; then
  py_config="${PYTHON}-config"
  if [[ ! -x "$py_config" ]]; then
    py_config="$prefix/bin/$(basename "$PYTHON")-config"
  fi
  if [[ ! -x "$py_config" ]]; then
    echo "run_tsan_python_stress: python-config not found for $PYTHON" >&2
    exit 1
  fi
  mapfile -t PY_EMBED_LDFLAGS < <("$py_config" --embed --ldflags)
  gcc -DTSAN_PY_STATIC -c -o "$LAUNCHER_OBJ" "$ROOT/scripts/tsan_python_launcher.c"
  g++ -o "$LAUNCHER" "$LAUNCHER_OBJ" "$LIBPYTHON_STATIC" \
    -Wl,--export-dynamic \
    -Wl,--whole-archive "$RT" -Wl,--no-whole-archive \
    "${PY_EMBED_LDFLAGS[@]}" \
    -ldl -pthread
else
  gcc -c -o "$LAUNCHER_OBJ" "$ROOT/scripts/tsan_python_launcher.c"
  # The control is this link: the same object file, no TSan archive.
  # __tsan_func_entry stays undefined, so the extension does not load.
  g++ -o "$NORUNTIME" "$LAUNCHER_OBJ" \
    -Wl,--export-dynamic \
    -ldl -pthread
  g++ -o "$LAUNCHER" "$LAUNCHER_OBJ" \
    -Wl,--export-dynamic \
    -Wl,--whole-archive "$RT" -Wl,--no-whole-archive \
    -ldl -pthread
fi

export PYTHON_GIL=0

if [[ "$launcher_mode" == "static" ]]; then
  "$LAUNCHER" "$VENV/bin/python" - <<'PY'
import sys
probe = getattr(sys, "_is_gil_enabled", None)
if probe is None or probe():
    raise SystemExit(f"GIL is enabled at runtime: {probe}")
print(sys.version)
PY
else
  "$LAUNCHER" "$LIBPYTHON" "$VENV/bin/python" - <<'PY'
import sys
probe = getattr(sys, "_is_gil_enabled", None)
if probe is None or probe():
    raise SystemExit(f"GIL is enabled at runtime: {probe}")
print(sys.version)
PY
fi

# Exact stack frame. The space (or the end of the line) after the symbol
# rejects rkr_tsan_canary_race:: and any other longer name.
canary_frame='^[[:space:]]*#0 rkr_tsan_canary_race([[:space:]]|$)'

NORUN_LOG="$TARGET_DIR/tsan-canary-noruntime.log"
export TSAN_OPTIONS="halt_on_error=0"
set +e
if [[ "$launcher_mode" == "static" ]]; then
  echo "no-runtime control skipped in static-libpython mode" >"$NORUN_LOG"
  norun_status=2
else
  "$NORUNTIME" "$LIBPYTHON" "$VENV/bin/python" "$ROOT/scripts/tsan_canary.py" >"$NORUN_LOG" 2>&1
  norun_status=$?
fi
set -e
echo "no-runtime canary status: $norun_status"
if [[ "$norun_status" -ne 2 ]]; then
  echo "run_tsan_python_stress: no-runtime launcher exited $norun_status, expected 2" >&2
  cat "$NORUN_LOG" >&2
  exit 1
fi
if grep -Eq "$canary_frame" "$NORUN_LOG"; then
  echo "run_tsan_python_stress: no-runtime launcher reported rkr_tsan_canary_race" >&2
  cat "$NORUN_LOG" >&2
  exit 1
fi
echo "no-runtime control failed closed"

CANARY_LOG="$TARGET_DIR/tsan-canary.log"
# Do not halt on the first report. A CPython race during import must
# not swallow the canary stack. No suppressions on this run.
export TSAN_OPTIONS="halt_on_error=0"
set +e
if [[ "$launcher_mode" == "static" ]]; then
  "$LAUNCHER" "$VENV/bin/python" "$ROOT/scripts/tsan_canary.py" >"$CANARY_LOG" 2>&1
else
  "$LAUNCHER" "$LIBPYTHON" "$VENV/bin/python" "$ROOT/scripts/tsan_canary.py" >"$CANARY_LOG" 2>&1
fi
canary_status=$?
set -e
echo "canary process status: $canary_status"
if [[ "$canary_status" -ne 66 ]]; then
  echo "run_tsan_python_stress: canary exited $canary_status, expected 66" >&2
  cat "$CANARY_LOG" >&2
  exit 1
fi
if ! grep -q 'ThreadSanitizer' "$CANARY_LOG" || ! grep -Eq "$canary_frame" "$CANARY_LOG"; then
  echo "run_tsan_python_stress: ThreadSanitizer did not report frame #0 rkr_tsan_canary_race" >&2
  cat "$CANARY_LOG" >&2
  exit 1
fi
echo "canary race reported"

STRESS_LOG="$TARGET_DIR/tsan-stress.log"
export TSAN_OPTIONS="halt_on_error=1 suppressions=${ROOT}/tests/tsan.supp"
set +e
if [[ "$launcher_mode" == "static" ]]; then
  "$LAUNCHER" "$VENV/bin/python" "$ROOT/tests/python/tsan_writer_stress.py" >"$STRESS_LOG" 2>&1
else
  "$LAUNCHER" "$LIBPYTHON" "$VENV/bin/python" "$ROOT/tests/python/tsan_writer_stress.py" >"$STRESS_LOG" 2>&1
fi
stress_status=$?
set -e
cat "$STRESS_LOG"
if [[ "$stress_status" -ne 0 ]]; then
  echo "run_tsan_python_stress: stress exited $stress_status" >&2
  exit "$stress_status"
fi
if grep -q 'WARNING: ThreadSanitizer' "$STRESS_LOG"; then
  echo "run_tsan_python_stress: stress printed a ThreadSanitizer warning" >&2
  exit 1
fi
echo "stress clean"

# Publish-kill tests live behind test-hooks so a release build does not
# carry them. Logs stay under the repo target directory. The extension
# build leaves sanitizer rustflags set, and a proc-macro crate refuses
# those flags, so the hook build clears them and uses its own target.
run_hook() {
  local label="$1"
  shift
  local log="$TARGET_DIR/tsan-${label}.log"
  rm -f "$log"
  set +e
  (
    unset CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_RUSTFLAGS
    unset RUSTFLAGS
    export CARGO_TARGET_DIR="$TARGET_DIR/hooks"
    msrv="$(sed -n 's/^rust-version = "\(.*\)"/\1/p' "$ROOT/Cargo.toml")"
    toolchain="$(rustup toolchain list | awk -v v="$msrv" 'index($1, v) == 1 { print $1; exit }')"
    if [[ -z "$toolchain" ]]; then
      echo "run_tsan_python_stress: no installed toolchain for rust-version ${msrv}" >&2
      exit 1
    fi
    export RUSTUP_TOOLCHAIN="$toolchain"
    "$@"
  ) >"$log" 2>&1
  local status=$?
  set -e
  cat "$log"
  if [[ "$status" -ne 0 ]]; then
    echo "run_tsan_python_stress: ${label} exited $status" >&2
    exit "$status"
  fi
  if grep -q 'running 0 tests' "$log"; then
    echo "run_tsan_python_stress: ${label} ran zero tests" >&2
    exit 1
  fi
}

run_hook hook-write \
  cargo test --locked --features test-hooks --test writer_publish_hooks -- \
  a_killed_write_keeps_the_previous_file_or_a_complete_one --exact --test-threads=1
run_hook hook-rewrite \
  cargo test --locked --features test-hooks --test writer_publish_hooks -- \
  a_killed_rewrite_leaves_the_published_file_whole --exact --test-threads=1
