# Head to head on one host

The host is Intel Xeon Processor, x86_64, 8 CPUs, memory_kib 49342768.
Every arm runs under taskset -c 0.
Each arm is one Snakemake rule and one asv class with time and track methods.
The timeout on each class is 600 s.
Samples are serial, six repeats, and the median and interquartile range use the type 7 quantile.
A row is correct only when the atom count, the cell, and the coordinates match within 1e-12.
The eon client is upstream commit 579738a9387e8d0ea55496f45dd057812cfab892.

## Same file

This table reads one con file.
The in-process Python read and the fresh-process Python read are separate rows.

| arm | median s | iqr s | correct |
| --- | --- | --- | --- |
| C read, 1000000 atoms | 0.087 | 0.002 | yes |
| Fortran read, 1000000 atoms | 0.096 | 0.008 | yes |
| Python in-process read, 1000000 atoms | 0.087 | 0.010 | yes |
| Python fresh-process read, 1000000 atoms | 0.115 | 0.005 | yes |
| eon C++ read, 1000000 atoms | 0.261 | 0.004 | yes |
| eon Python read, 1000000 atoms | 3.303 | 0.036 | yes |
| ASE eon read, 1000000 atoms | 1.376 | 0.035 | yes |
| C write, 1000000 atoms | 0.203 | 0.008 | yes |
| Fortran write, 1000000 atoms | 0.203 | 0.006 | yes |
| Python write, 1000000 atoms | 0.222 | 0.008 | yes |
| C read, 10000 frames of 100 atoms | 0.085 | 0.003 | yes |
| Fortran read, 10000 frames of 100 atoms | 0.112 | 0.004 | yes |
| Python read, 10000 frames of 100 atoms | 0.087 | 0.018 | yes |
| C read, 10 atoms | 0.0000049 | 0.0000007 | yes |
| Fortran read, 10 atoms | 0.0000046 | 0.0000025 | yes |
| Python read, 10 atoms | 0.0000063 | 0.0000063 | yes |
| eon C++ read, 10 atoms | 0.0000233 | 0.0000022 | yes |

The C reader peaks at 140 MiB on the million atom file.
The fresh Python process peaks at 165 MiB on that file.
The in-process Python peak is 268 MiB because that process has already read the smaller files.
The fresh-process split is parse 0.092 s, convert 0.019 s, copy 0.000155 s.
The Python write split is copy 0.002 s, convert 0.024 s, file format 0.170 s.
Python read of one million atoms is faster than the eon client and faster than eon Python.
The 10 atom C read is 4.9 us. The eon client takes 23.3 us on that file.

## Nearest native format

This table reads different files.
It is a separate panel from the con table.
NumPy reads an npy array.
ASE reads a traj file.
`OVITO` reads extended xyz.
Chemfiles, MDAnalysis, and pymatgen read xyz.

| arm | median s | iqr s | atoms | cell | coordinates | correct |
| --- | --- | --- | --- | --- | --- | --- |
| NumPy npy | 0.005 | 0.010 | yes | no, cell is missing | yes, max abs 0 | no |
| ASE traj | 0.018 | 0.018 | yes | yes | yes, max abs 0 | yes |
| `OVITO` extxyz | 0.134 | 0.003 | yes | yes | yes, max abs 0 | yes |
| chemfiles xyz | 0.258 | 0.011 | yes | no, cell lengths are 0 | yes, max abs 0 | no |
| MDAnalysis xyz | 5.419 | 0.162 | yes | no, cell is missing | yes, max abs 0 | no |
| pymatgen xyz | 7.504 | 0.492 | yes | no, cell is missing | yes, max abs 0 | no |

Chemfiles returns cell lengths of 0.
The xyz file omits the cell, so that row fails the cell check.
MDAnalysis leaves the cell missing on that xyz file.
pymatgen reads a molecule and has no lattice.
The npy file stores the coordinate array and has no cell.
`RCSO` is an in memory broadcast blob, and conbin is absent from this version, so neither is in these tables.
