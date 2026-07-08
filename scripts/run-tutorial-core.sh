#!/usr/bin/env bash
# Tangle + run docs/orgmode/tutorial.org (One Good Tutorial) via Org Babel.
# Primary CI path: emacs tangle → python docs/notebooks/tutorial_core.py
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
  echo "Building lean Python extension (maturin develop --features python)..."
  if command -v maturin >/dev/null 2>&1; then
    maturin develop --features python
  else
    echo "maturin not on PATH; install maturin or: pixi run -e python python-build" >&2
    exit 1
  fi
  python3 -c "import readcon"
fi

# 1) Tangle named Python blocks → docs/notebooks/tutorial_core.py
"$EMACS_BIN" --batch \
  --eval "(require 'org)" \
  --eval "(setq org-confirm-babel-evaluate nil)" \
  --visit "$ORG" \
  --eval "(org-babel-tangle)"

if [[ ! -f "$TANGLE_PY" ]]; then
  echo "tangle failed: missing $TANGLE_PY" >&2
  exit 1
fi

# 2) Execute the Org buffer (Python session) — authoritative run when Babel works
"$EMACS_BIN" --batch \
  --eval "(require 'org)" \
  --eval "(require 'ob-python)" \
  --eval "(setq org-confirm-babel-evaluate nil)" \
  --eval "(setq org-babel-python-command \"python3\")" \
  --eval "(defun readcon/org-babel-execute-python-blocks ()
            (org-babel-map-src-blocks nil
              (when (org-babel-get-src-block-info)
                (let ((lang (nth 0 (org-babel-get-src-block-info))))
                  (when (string= lang \"python\")
                    (org-babel-execute-src-block))))))" \
  --visit "$ORG" \
  --eval "(let ((default-directory \"$ROOT\"))
            (setq default-directory \"$ROOT\")
            (readcon/org-babel-execute-python-blocks))" \
  || {
    echo "warning: Babel execute failed; falling back to tangled script" >&2
    READCON_TUT_ROOT="$ROOT" READCON_TUT_WORK="$OUT_DIR" python3 "$TANGLE_PY"
  }

if [[ ! -f "$OUT_DIR/summary.json" ]]; then
  echo "summary.json missing after Babel; running tangled script" >&2
  READCON_TUT_ROOT="$ROOT" READCON_TUT_WORK="$OUT_DIR" python3 "$TANGLE_PY"
fi

python3 -c "from pathlib import Path; print(Path('$OUT_DIR/summary.json').read_text())"
echo "OK — tangled and ran Org Babel tutorial: $ORG"
