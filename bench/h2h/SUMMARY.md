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
The Atomic Simulation Environment (ASE) row uses the eon format.
The in-process Python read and the fresh-process Python read are separate rows.

| arm | median s | iqr s | correct |
| --- | --- | --- | --- |
| C read, 1000000 atoms | 0.080 | 0.005 | yes |
| Fortran read, 1000000 atoms | 0.100 | 0.003 | yes |
| Python in-process read, 1000000 atoms | 0.089 | 0.010 | yes |
| Python fresh-process read, 1000000 atoms | 0.121 | 0.009 | yes |
| eon C++ read, 1000000 atoms | 0.276 | 0.013 | yes |
| eon Python read, 1000000 atoms | 3.151 | 0.057 | yes |
| ASE eon read, 1000000 atoms | 1.402 | 0.065 | yes |
| C write, 1000000 atoms | 0.198 | 0.009 | yes |
| Fortran write, 1000000 atoms | 0.205 | 0.009 | yes |
| Python write, 1000000 atoms | 0.222 | 0.010 | yes |
| C read, 10000 frames of 100 atoms | 0.080 | 0.004 | yes |
| Fortran read, 10000 frames of 100 atoms | 0.116 | 0.003 | yes |
| Python read, 10000 frames of 100 atoms | 0.088 | 0.017 | yes |
| C read, 10 atoms | 0.0000047 | 0.0000009 | yes |
| Fortran read, 10 atoms | 0.0000049 | 0.0000031 | yes |
| Python read, 10 atoms | 0.0000060 | 0.0000070 | yes |
| eon C++ read, 10 atoms | 0.0000254 | 0.0000025 | yes |

The C reader peaks at 140 MiB on the million atom file.
The fresh Python process peaks at 165 MiB on that file.
The in-process Python peak is 268 MiB because that process has already read the smaller files.
The fresh-process split is parse 0.100 s, convert 0.024 s, copy 0.000189 s.
The Python write split is copy 0.002 s, convert 0.024 s, file format 0.169 s.
Python read of one million atoms is faster than the eon client and faster than eon Python.
The 10 atom C read is 4.7 us.
The eon client takes 25.4 us on that file.

## Nearest native format

This table reads different files.
It is a separate panel from the con table.
NumPy reads an npy coordinate array, which has no cell.
ASE and chemfiles read extended xyz.
`OVITO` reads extended xyz.
pymatgen reads a POSCAR.
MDAnalysis reads a protein data bank file with a crystal record.

| arm | median s | iqr s | atoms | cell | coordinates | correct |
| --- | --- | --- | --- | --- | --- | --- |
| NumPy npy | 0.007 | 0.010 | yes | no, cell is missing | yes, max abs 0 | no |
| ASE extxyz | 1.342 | 0.036 | yes | yes | yes, max abs 0 | yes |
| `OVITO` extxyz | 0.131 | 0.007 | yes | yes | yes, max abs 0 | yes |
| chemfiles extxyz | 0.338 | 0.034 | yes | yes | yes, max abs 0 | yes |
| MDAnalysis crystal record | 7.426 | 0.072 | yes | yes | yes, max abs 0 | yes |
| pymatgen poscar | 14.864 | 3.866 | yes | yes | yes, max abs 7e-15 | yes |

NumPy has no cell, so that row fails the cell check.
The other native rows match the atom count, the cell, and the coordinates.
`RCSO` is an in memory broadcast blob, and conbin is absent from this version, so neither is in these tables.
