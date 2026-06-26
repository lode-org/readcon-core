#!/usr/bin/env bash
# Execute docs/notebooks/chemfiles_ingress.py via papermill (rgoswami.me-style:
# literate source in git; notebooks are *functions* parameterized on the fly).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SRC="${ROOT}/docs/notebooks/chemfiles_ingress.py"
OUT_DIR="${ROOT}/docs/notebooks/out"
OUT_NB="${OUT_DIR}/chemfiles_ingress.ipynb"
WORK="${OUT_DIR}/work"
mkdir -p "$OUT_DIR" "$WORK"

if ! python3 -c "import readcon, readcon.has_chemfiles_support as h; import sys; sys.exit(0 if h() else 1)" 2>/dev/null; then
  echo "Building chemfiles-linked extension (maturin develop --features python,chemfiles)..."
  if command -v maturin >/dev/null 2>&1; then
    maturin develop --features python,chemfiles
  else
    echo "maturin not found; pip install maturin or use pixi -e python, then re-run." >&2
    exit 1
  fi
fi

if ! python3 -c "import papermill" 2>/dev/null; then
  python3 -m pip install -q 'papermill>=2.4' jupytext ipykernel
fi

# Ensure percent script is a valid notebook for papermill
python3 -m jupytext --to ipynb -o "${OUT_DIR}/chemfiles_ingress.in.ipynb" "$SRC"

python3 -m papermill \
  "${OUT_DIR}/chemfiles_ingress.in.ipynb" \
  "$OUT_NB" \
  -p work_dir "$WORK" \
  -p require_chemfiles true \
  --cwd "$ROOT"

python3 -c "import json; from pathlib import Path; p=Path('$WORK')/'summary.json'; print(p.read_text())"
echo "OK papermill -> $OUT_NB"
