#!/usr/bin/env bash
# Org Babel chemfiles conversion runner (docs/orgmode/chemfiles-notebook.org).
#
# Authoritative path (no soft-fail theater):
#   1) org-babel-tangle → docs/notebooks/chemfiles_ingress.py
#   2) fail if committed tangle differs from re-tangle (unless READCON_TANGLE_UPDATE=1)
#   3) python3 the tangled file (asserts + summary.json)
#
# Requires chemfiles-linked readcon. Optional papermill (READCON_NB_PAPERMILL=1)
# fails hard if enabled and papermill fails.
set -euo pipefail
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

ORG="${ROOT}/docs/orgmode/chemfiles-notebook.org"
OUT_DIR="${ROOT}/docs/notebooks/out"
WORK="${OUT_DIR}/work"
TANGLE_PY="${ROOT}/docs/notebooks/chemfiles_ingress.py"
mkdir -p "$OUT_DIR" "$WORK"
export READCON_NB_WORK="$WORK"

ensure_chemfiles_python() {
  if python3 -c "import readcon; import sys; sys.exit(0 if readcon.has_chemfiles_support() else 1)" 2>/dev/null; then
    return 0
  fi
  echo "Building chemfiles-linked extension (maturin develop --features python,chemfiles)..." >&2
  if command -v maturin >/dev/null 2>&1; then
    maturin develop --features python,chemfiles
  else
    echo "maturin not on PATH; install maturin or: pixi run -e python python-build-chemfiles" >&2
    exit 1
  fi
  python3 -c "import readcon; assert readcon.has_chemfiles_support(), 'chemfiles still missing'"
}

ensure_chemfiles_python

BEFORE="$(mktemp)"
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

echo "run: python3 $TANGLE_PY"
READCON_NB_WORK="$WORK" python3 "$TANGLE_PY"

if [[ ! -f "$WORK/summary.json" ]]; then
  echo "FAIL: $WORK/summary.json missing after chemfiles notebook run" >&2
  exit 1
fi

python3 -c "from pathlib import Path; p=Path(r'''$WORK/summary.json'''); t=p.read_text(); assert 'n_atoms' in t and 'has_chemfiles_support' in t, t; print(t)"
echo "OK — tangled, drift-checked, and ran: $ORG"

if [[ "${READCON_NB_PAPERMILL:-0}" == "1" ]]; then
  python3 -m pip install -q 'papermill>=2.4' jupytext ipykernel
  python3 -c "import papermill, jupytext"
  python3 -m jupytext --to ipynb -o "$OUT_DIR/chemfiles_ingress.tangled.ipynb" "$TANGLE_PY"
  python3 -m papermill \
    "$OUT_DIR/chemfiles_ingress.tangled.ipynb" \
    "$OUT_DIR/chemfiles_ingress.papermill.ipynb" \
    -p work_dir "$WORK" \
    --cwd "$ROOT"
  echo "OK — papermill on tangled output"
fi
