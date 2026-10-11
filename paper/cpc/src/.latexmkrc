# BibTeX abbreviates Ádám and 't Hoen into invalid UTF-8.
# Repair the bbl after bibtex and before every pdflatex pass.
$pdflatex = 'sh ../scripts/pdflatex-repair.sh %O %S';
