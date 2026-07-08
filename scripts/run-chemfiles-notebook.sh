#!/usr/bin/env bash
# Execute docs/orgmode/chemfiles-notebook.org via Org Babel (source of truth).
# Optional: tangle Python and run papermill on the *generated* script only.
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
  echo "Building chemfiles-linked extension (maturin develop --features python,chemfiles)..."
  if command -v maturin >/dev/null 2>&1; then
    maturin develop --features python,chemfiles
  else
    echo "maturin not on PATH; install maturin or: pixi run -e python python-build-chemfiles" >&2
    exit 1
  fi
  python3 -c "import readcon; assert readcon.has_chemfiles_support(), 'chemfiles still missing'"
}

ensure_chemfiles_python

# 1) Tangle named blocks from Org → docs/notebooks/chemfiles_ingress.py (generated)
"$EMACS_BIN" --batch \
  --eval "(require 'org)" \
  --eval "(setq org-confirm-babel-evaluate nil)" \
  --visit "$ORG" \
  --eval "(org-babel-tangle)" 

# 2) Execute the Org buffer (Python session) — this is the authoritative run
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
            (readcon/org-babel-execute-python-blocks))"

if [[ ! -f "$WORK/summary.json" ]]; then
  echo "warning: summary.json missing after babel; trying tangled script as fallback" >&2
  READCON_NB_WORK="$WORK" python3 "$TANGLE_PY"
fi

python3 -c "from pathlib import Path; print(Path('$WORK/summary.json').read_text())"
echo "OK — executed Org Babel notebook: $ORG"

# 3) Optional Papermill on *tangled* percent-less script (not a committed ipynb)
if [[ "${READCON_NB_PAPERMILL:-0}" == "1" ]]; then
  python3 -m pip install -q 'papermill>=2.4' jupytext ipykernel 2>/dev/null || true
  if python3 -c "import papermill, jupytext" 2>/dev/null; then
    # Wrap tangled py as a minimal notebook for papermill without maintaining ipynb in git
    python3 -m jupytext --to ipynb -o "$OUT_DIR/chemfiles_ingress.tangled.ipynb" "$TANGLE_PY"
    python3 -m papermill \
      "$OUT_DIR/chemfiles_ingress.tangled.ipynb" \
      "$OUT_DIR/chemfiles_ingress.papermill.ipynb" \
      -p work_dir "$WORK" \
      --cwd "$ROOT" || true
    echo "OK — optional papermill on tangled output (READCON_NB_PAPERMILL=1)"
  fi
fi
