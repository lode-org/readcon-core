#!/usr/bin/env bash
# pdfTeX build of the manuscript and the supplement.
# The two documents import each other's labels through xr-hyper, so they are typeset in turns.
set -euo pipefail
cd "$(dirname "$0")/../src"
# \today and the dates of both PDFs are the SOURCE_DATE_EPOCH of regen_paper.py, so every build gives the same bytes.
SOURCE_DATE_EPOCH=$(sed -n 's/^SOURCE_DATE_EPOCH = "\([0-9]*\)"$/\1/p' ../scripts/regen_paper.py)
[ -n "$SOURCE_DATE_EPOCH" ] || { echo "scripts/regen_paper.py sets no SOURCE_DATE_EPOCH" >&2; exit 1; }
export SOURCE_DATE_EPOCH FORCE_SOURCE_DATE=1
for doc in rg_supp rg_main; do
  pdflatex -interaction=nonstopmode -halt-on-error "$doc.tex" >/dev/null
done
bibtex rg_supp >/dev/null
bibtex rg_main >/dev/null
for pass in 1 2 3; do
  for doc in rg_supp rg_main; do
    pdflatex -interaction=nonstopmode -halt-on-error "$doc.tex" >/dev/null
  done
done
for doc in rg_main rg_supp; do
  if grep -E "undefined|Overfull|Rerun to get|Float too large" "$doc.log"; then
    echo "$doc.log: unresolved references, overfull boxes or oversized floats" >&2
    exit 1
  fi
  grep "Output written" "$doc.log"
done
