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
| C read, 1000000 atoms | 0.078 | 0.003 | yes |
| Fortran read, 1000000 atoms | 0.094 | 0.001 | yes |
| Python in-process read, 1000000 atoms | 0.091 | 0.006 | yes |
| Python fresh-process read, 1000000 atoms | 0.129 | 0.002 | yes |
| eon C++ read, 1000000 atoms | 0.301 | 0.002 | yes |
| eon Python read, 1000000 atoms | 3.089 | 0.076 | yes |
| ASE eon read, 1000000 atoms | 1.368 | 0.035 | yes |
| C write, 1000000 atoms | 0.197 | 0.010 | yes |
| Fortran write, 1000000 atoms | 0.200 | 0.008 | yes |
| Python write, 1000000 atoms | 0.241 | 0.002 | yes |
| C read, 10000 frames of 100 atoms | 0.078 | 0.004 | yes |
| Fortran read, 10000 frames of 100 atoms | 0.110 | 0.003 | yes |
| Python read, 10000 frames of 100 atoms | 0.094 | 0.018 | yes |
| C read, 10 atoms | 0.0000052 | 0.0000006 | yes |
| Fortran read, 10 atoms | 0.0000065 | 0.0000290 | yes |
| Python read, 10 atoms | 0.0000065 | 0.0000064 | yes |
| eon C++ read, 10 atoms | 0.0000337 | 0.0000031 | yes |

The C reader peaks at 140 MiB on the million atom file.
The fresh Python process peaks at 165 MiB on that file.
The in-process Python peak is 276 MiB because that process has already read the smaller files.
The fresh-process split is parse 0.102 s, convert 0.026 s, copy 0.000172 s.
The Python write split is copy 0.004 s, convert 0.030 s, file format 0.183 s.
Python read of one million atoms is faster than the eon client and faster than eon Python.
The 10 atom C read is 5.2 us.
The eon client takes 33.7 us on that file.

## Nearest native format

This table reads different files.
It is a separate panel from the con table.
NumPy reads an npy coordinate array, which has no cell.
The Atomic Simulation Environment (ASE) and chemfiles read extended xyz.
`OVITO` reads extended xyz.
pymatgen reads a POSCAR.
MDAnalysis reads a PDB file with a CRYST1 record.

| arm | median s | iqr s | atoms | cell | coordinates | correct |
| --- | --- | --- | --- | --- | --- | --- |
| NumPy npy | 0.005 | 0.009 | yes | no, cell is missing | yes, max abs 0 | no |
| ASE traj | 0.015 | 0.015 | yes | yes | yes, max abs 0 | yes |
| `OVITO` extxyz | 0.130 | 0.010 | yes | yes | yes, max abs 0 | yes |
| chemfiles xyz | 0.255 | 0.014 | yes | no, cell lengths are 0 | yes, max abs 0 | no |
| MDAnalysis xyz | 5.236 | 0.019 | yes | no, cell is missing | yes, max abs 0 | no |
| pymatgen xyz | 7.844 | 0.296 | yes | no, cell is missing | yes, max abs 0 | no |

Chemfiles returns cell lengths of 0.
The xyz file omits the cell, so that row fails the cell check.
MDAnalysis leaves the cell missing on that xyz file.
pymatgen reads a molecule and has no lattice.
The npy file stores the coordinate array and has no cell.
`RCSO` is an in memory broadcast blob, and conbin is absent from this version, so neither is in these tables.
