#!/bin/sh
# Repair BibTeX's broken initials, then run pdflatex.
# latexmk invokes this with the working directory set to paper/cpc/src.
python3 ../scripts/repair_bbl.py rg_main.bbl
exec pdflatex "$@"
