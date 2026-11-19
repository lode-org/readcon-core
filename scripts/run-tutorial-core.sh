#!/usr/bin/env bash
# Org Babel One Good Tutorial runner (docs/orgmode/tutorial.org).
#
# Authoritative path (no soft-fail theater):
#   1) org-babel-tangle → docs/notebooks/tutorial_core.py
#   2) fail if committed tangle differs from re-tangle (unless READCON_TANGLE_UPDATE=1)
#   3) run the tangled file with the interpreter that imports readcon
#
# Local interactive C-c C-c in Emacs is fine for humans; CI does not use
# session execute as a second success path (session vs tangle can disagree).
set -euo pipefail
# shellcheck source=scripts/scratch.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/scratch.sh"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

resolve_emacs() {
  if [[ -n "${EMACS:-}" && -x "$EMACS" ]]; then
    echo "$EMACS"
    return
  fi
  if command -v emacs >/dev/null 2>&1; then
    command -v emacs
    return
  fi
  for cand in \
    "${ROOT}/.pixi/envs/docs/bin/emacs" \
    "${HOME}/.pixi/envs/docs/bin/emacs"; do
    if [[ -x "$cand" ]]; then
      echo "$cand"
      return
    fi
  done
  return 1
}

EMACS_BIN="$(resolve_emacs)" || {
  echo "emacs required for org-babel-tangle (install emacs-nox or pixi docs env)" >&2
  exit 1
}

ORG="${ROOT}/docs/orgmode/tutorial.org"
TANGLE_PY="${ROOT}/docs/notebooks/tutorial_core.py"
OUT_DIR="${ROOT}/docs/notebooks/out/tutorial_core"
mkdir -p "$OUT_DIR" "$(dirname "$TANGLE_PY")"
export READCON_TUT_ROOT="$ROOT"
export READCON_TUT_WORK="$OUT_DIR"

# $PYTHON wins when the caller names an interpreter (pytest passes
# sys.executable). Otherwise use the active virtualenv, the interpreter
# beside `maturin` on PATH, or a `python` that can run `python -m maturin`.
# A bare python3 is not that interpreter: maturin is often on PATH, or
# installed only as a module, with no sibling named python.
resolve_python() {
  if [[ -n "${PYTHON:-}" ]]; then
    if [[ ! -x "$PYTHON" ]]; then
      echo "PYTHON=$PYTHON is not executable" >&2
      return 1
    fi
    echo "$PYTHON"
    return
  fi
  if [[ -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python" ]]; then
    echo "${VIRTUAL_ENV}/bin/python"
    return
  fi
  if command -v maturin >/dev/null 2>&1; then
    local beside
    beside="$(dirname "$(command -v maturin)")/python"
    if [[ -x "$beside" ]]; then
      echo "$beside"
      return
    fi
  fi
  if command -v python >/dev/null 2>&1; then
    local py
    py="$(command -v python)"
    if [[ -x "$py" ]] && "$py" -m maturin --version >/dev/null 2>&1; then
      echo "$py"
      return
    fi
  fi
  echo "maturin is unavailable; set PYTHON to an interpreter that can run it" >&2
  echo "looked for VIRTUAL_ENV, maturin on PATH, and \`python -m maturin\`" >&2
  return 1
}

# A missing readcon is built as a wheel and installed into a virtualenv in
# the scratch directory. The virtualenv sees the packages of PYTHON_BIN but
# installs into its own prefix, so the caller's interpreter is never changed.
run_maturin() {
  if "$PYTHON_BIN" -m maturin --version >/dev/null 2>&1; then
    env -u VIRTUAL_ENV "$PYTHON_BIN" -m maturin "$@"
  elif command -v maturin >/dev/null 2>&1; then
    env -u VIRTUAL_ENV maturin "$@"
  else
    echo "maturin is unavailable (not on PATH and \`$PYTHON_BIN -m maturin\` failed)" >&2
    echo "install maturin or: pixi run -e python python-build" >&2
    exit 1
  fi
}

ISOLATED=""
cleanup() {
  if [[ -n "$ISOLATED" ]]; then
    rm -rf "$ISOLATED"
  fi
}
trap cleanup EXIT

PYTHON_BIN="$(resolve_python)"

if ! "$PYTHON_BIN" -c "import readcon" 2>/dev/null; then
  ISOLATED="$(scratch_dir)"
  echo "Building readcon into the virtualenv $ISOLATED/venv; $PYTHON_BIN is left as it is" >&2
  "$PYTHON_BIN" -m venv --system-site-packages "$ISOLATED/venv"
  run_maturin build --features python --interpreter "$ISOLATED/venv/bin/python" --out "$ISOLATED/wheels"
  "$ISOLATED/venv/bin/python" -m pip install --quiet --no-deps --no-index "$ISOLATED"/wheels/readcon-*.whl
  PYTHON_BIN="$ISOLATED/venv/bin/python"
  "$PYTHON_BIN" -c "import readcon"
fi

# Snapshot committed (or pre-tangle) bytes for drift check.
BEFORE="$(scratch_file)"
if [[ -f "$TANGLE_PY" ]]; then
  cp "$TANGLE_PY" "$BEFORE"
else
  : >"$BEFORE"
fi

echo "tangle: $ORG → $TANGLE_PY"
"$EMACS_BIN" --batch \
  --eval "(require 'org)" \
  --eval "(setq org-confirm-babel-evaluate nil)" \
  --visit "$ORG" \
  --eval "(org-babel-tangle)"

if [[ ! -f "$TANGLE_PY" ]]; then
  echo "tangle failed: missing $TANGLE_PY" >&2
  rm -f "$BEFORE"
  exit 1
fi

if ! cmp -s "$BEFORE" "$TANGLE_PY"; then
  if [[ "${READCON_TANGLE_UPDATE:-0}" == "1" ]]; then
    echo "tangle drift: updated $TANGLE_PY (READCON_TANGLE_UPDATE=1)" >&2
  else
    echo "tangle drift: $TANGLE_PY did not match the re-tangle from $ORG" >&2
    echo "The working tree now has the Org-produced tangle. Commit it, or fix the Org source." >&2
    if command -v git >/dev/null 2>&1 && git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
      git -C "$ROOT" --no-pager diff --no-index -- "$BEFORE" "$TANGLE_PY" || true
    fi
    rm -f "$BEFORE"
    exit 1
  fi
fi
rm -f "$BEFORE"

echo "run: $PYTHON_BIN $TANGLE_PY"
READCON_TUT_ROOT="$ROOT" READCON_TUT_WORK="$OUT_DIR" "$PYTHON_BIN" "$TANGLE_PY"

if [[ ! -f "$OUT_DIR/summary.json" ]]; then
  echo "FAIL: $OUT_DIR/summary.json missing after tutorial run" >&2
  exit 1
fi

"$PYTHON_BIN" -c "from pathlib import Path; p=Path(r'''$OUT_DIR/summary.json'''); t=p.read_text(); assert 'built_energy' in t and 'multi_frames' in t, t; print(t)"
echo "OK — tangled, drift-checked, and ran: $ORG"
