# Head to head on one host

## What the campaign measures

The campaign takes six serial samples.
The absolute tolerance is 1e-12.
A row passes when the atom count, the cell, and the coordinates match.
The median and the interquartile range use the type 7 quantile.
Every arm runs under taskset -c 0.

## Same file

Every reader opens the same con file.
The Atomic Simulation Environment (ASE) row uses the eon format.
On one million atoms the C read takes 0.080 s.
A fresh Python process takes 0.121 s and peaks at 165 MiB.
The C reader peaks at 140 MiB.
The upstream eon client takes 0.276 s.
SUMMARY.md lists every row.

## Nearest native format

This panel reads cell-carrying files.
ASE and chemfiles read extended xyz.
The Open Visualization Tool reads extended xyz.
pymatgen reads a POSCAR.
MDAnalysis reads a protein data bank file with a crystal record.
NumPy reads an npy coordinate array, which has no cell.
That row fails the cell check.
The other native rows match the atom count, the cell, and the coordinates.

## Reproduce

The rules live in benchmarks/workflow/Snakefile.
The target name is h2h.
Each arm is one rule and one asv class under bench/h2h/asv.
bench/h2h/asv/drive.py locks the arms so they stay serial.
