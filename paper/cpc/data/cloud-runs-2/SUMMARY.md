# Cloud runs 2

`05/` holds campaign 05: the cross-binding, H5MD and ASE trajectory routes of the restart case, measured on
readcon-core 0.17.2 at commit `67a8d95` (`05/build.txt`), whose library and bindings are those of tag v0.17.2
(`5c849d1`); the two commits differ only in the Fortran test `fortran/ReadCon/test/test_add_atom_restart.f90`.
The host is the one `05/host.json` records: Intel Xeon model 173 at 2.7 GHz, 8 CPUs, rustc 1.88.0, g++ 13.3.0,
gfortran 13.3.0, Julia 1.11.6, Python 3.12.3. `cloud-run/run_05.py` exits unless the core it loads is that
release. Neither manuscript takes a number from campaign 05.

## Records

- `05/matrix.csv` and `05/matrix.json`: the survey frame through each writer and reader, the 25 CON 3.1 language
  pairs among Python, C, C++, Fortran and Julia, and the H5MD routes written by MDAnalysis and by h5py.
- `05/restart_formats.csv`, `05/restart_bands.json` and `05/bands/*.npz`: the band of the 28-atom slab of the
  restart case, stopped, written and read back through each route, and resumed.
- `05/tables/` and `05/figures/`: the survey and restart tables and the restart figure that `run_05.py` draws from
  these records with the paper's generators. Neither manuscript inputs them.

## Drivers

`cloud-run/run_05.py` runs the routes of `scripts/failure_matrix.py` and `scripts/restart_formats.py` through each
binding, with `cloud-run/cpp_io.cpp`, `cloud-run/fortran_io.f90` and `cloud-run/julia_io.jl` as the C++, Fortran and
Julia writers and readers. The Fortran writer calls `builder%add_atom`, which 0.17.2 binds in the C argument order.
`scripts/restart_formats.py` imports its h5py H5MD writer and reader for the H5MD route of the restart table.

## Earlier runs

The first run of campaign 05 (readcon-core 0.17.0 at `af8aabb`) and campaign 04, the MPI and store series on
readcon-core 0.17.0 and readcon-db 0.1.8, are not in this tree, and the manuscript uses neither. The records of the
first run of campaign 05 are at commit `dc42253`.
