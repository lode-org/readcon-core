#!/usr/bin/env bash
# Org Babel One Good Tutorial runner (docs/orgmode/tutorial.org).
#
# Authoritative path (no soft-fail theater):
#   1) org-babel-tangle → docs/notebooks/tutorial_core.py
#   2) fail if committed tangle differs from re-tangle (unless READCON_TANGLE_UPDATE=1)
#   3) python3 the tangled file (asserts + summary.json)
#
# Local interactive C-c C-c in Emacs is fine for humans; CI does not use
# session execute as a second success path (session vs tangle can disagree).
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

ORG="${ROOT}/docs/orgmode/tutorial.org"
TANGLE_PY="${ROOT}/docs/notebooks/tutorial_core.py"
OUT_DIR="${ROOT}/docs/notebooks/out/tutorial_core"
mkdir -p "$OUT_DIR" "$(dirname "$TANGLE_PY")"
export READCON_TUT_ROOT="$ROOT"
export READCON_TUT_WORK="$OUT_DIR"

if ! python3 -c "import readcon" 2>/dev/null; then
  echo "Building lean Python extension (maturin develop --features python)..." >&2
  if command -v maturin >/dev/null 2>&1; then
    maturin develop --features python
  else
    echo "maturin not on PATH; install maturin or: pixi run -e python python-build" >&2
    exit 1
  fi
  python3 -c "import readcon"
fi

# Snapshot committed (or pre-tangle) bytes for drift check.
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
READCON_TUT_ROOT="$ROOT" READCON_TUT_WORK="$OUT_DIR" python3 "$TANGLE_PY"

if [[ ! -f "$OUT_DIR/summary.json" ]]; then
  echo "FAIL: $OUT_DIR/summary.json missing after tutorial run" >&2
  exit 1
fi

python3 -c "from pathlib import Path; p=Path(r'''$OUT_DIR/summary.json'''); t=p.read_text(); assert 'built_energy' in t and 'multi_frames' in t, t; print(t)"
echo "OK — tangled, drift-checked, and ran: $ORG"
