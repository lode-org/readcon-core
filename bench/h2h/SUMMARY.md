# Head to head after the array read and the in place write

The campaign is serial, six repeats, one pinned core, on x86_64 with 8 CPUs.
The median uses the type 7 quantile.
A coordinate check uses an absolute tolerance of 1e-12.
The eon client is the upstream tree 579738a9387e8d0ea55496f45dd057812cfab892.

## Con readers

A fresh Python process reads one million atoms in 0.124 s and peaks at 203 MiB.
The C reader does that file in 0.093 s and peaks at 140 MiB.
Fortran reads it in 0.101 s.
The eon client reads it in 0.307 s.
eon Python loadcons takes 3.326 s and allocates one object for each atom.
ASE with the eon format takes 1.568 s.
Python read beats the eon client and eon Python.
The split on the fresh read is parse 0.085 s, convert 0.017 s, copy 0.000027 s.

Python write of that file takes 0.247 s and the file format step inside it is 0.185 s.
C write takes 0.203 s.
Fortran write takes 0.202 s.
The old Fortran path rebuilt every atom before the format step.
Fortran now writes the parsed atoms and only replaces the header text, and it matches C.

Ten thousand frames of one hundred atoms take 0.074 s in C, 0.100 s in Python and 0.118 s in Fortran.
A ten atom file takes 4.1 us in C, 6.9 us in Python and 7.9 us in Fortran.
That is under the 17 us eon read of the same size.

## Nearest native format

This panel is not a con read.
NumPy loads the coordinate array in 0.005 s with a maximum absolute difference of 0.
ASE traj reads back in 0.030 s with a maximum absolute difference of 0.
OVITO reads extended xyz in 0.162 s with a maximum absolute difference of 0.
Chemfiles reads xyz in 0.282 s with a maximum absolute difference of 0 on the copper grid.
MDAnalysis reads that xyz in 6.024 s with a maximum absolute difference of 0.
pymatgen reads that xyz in 7.992 s with a maximum absolute difference of 0.
On the small copper hydride xyz, chemfiles returns cell lengths of 0.
The coordinates still match within 3.6e-15.
Chemfiles xyz omits the cell.
RCSO is an in memory broadcast blob, and conbin is absent from this version, so neither is in these tables.
