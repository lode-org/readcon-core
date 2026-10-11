# readcon-core

`readcon-core` is the reference reader and writer for versioned `.con` and
`.convel` checkpoints. Rare-event codes already checkpoint on CON. This
library is the spec and the hourglass `rkr_*` API so Fortran, C, C++,
Python, Julia, and Rust read and write the same file everywhere.

One frame carries the cell, type-grouped coordinates, per-direction fixed
masks, column-5 `atom_id`, and optional per-atom sections (velocities,
forces, energies, charges, spins, magmoms, displacements, spreads).
The on-disk rules are [docs/orgmode/spec.org](docs/orgmode/spec.org).

DLPack and metatensor export the same arrays. Chemfiles is the optional
ingress path from XYZ, PDB, and GRO. Corpora use
[readcon-db](https://lode-org.github.io/readcon-db/docs/).

## Install

| Language | Command |
| --- | --- |
| Python | `pip install 'readcon==0.16.2'` |
| Python + chemfiles | `pip install 'readcon-chemfiles==0.16.2'` |
| Rust | `cargo add readcon-core@0.16.2` |

The full matrix is
[docs/orgmode/tutorials/getting-started.org](docs/orgmode/tutorials/getting-started.org).

## Tutorial

```python
import readcon

for frame in readcon.iter_con("resources/test/tiny_multi_cuh2.con"):
    print(frame.cell, len(frame), frame.energy)
```

Steps: [docs/orgmode/tutorials/tutorial.org](docs/orgmode/tutorials/tutorial.org).
Migrate a stack onto CON, including `convert structure.xyz structure.con`:
[docs/orgmode/howto/migrate.org](docs/orgmode/howto/migrate.org).
Other languages: [docs/orgmode/howto/howto.org](docs/orgmode/howto/howto.org).

## Measurements

Cachegrind I-refs (`examples/cachegrind_harness.rs`), Python ASV and
spyglass on pull requests (`benchmarks/`), and peer scripts under
`benches/` including `benches/compare_readers.py`.
See [docs/orgmode/explanation/benchmarks.org](docs/orgmode/explanation/benchmarks.org).

## Citation

Cite the software with concept DOI
[10.5281/zenodo.18753567](https://doi.org/10.5281/zenodo.18753567).
Paper order and the Chill 2014 eOn citation are in
[docs/orgmode/reference/citations.org](docs/orgmode/reference/citations.org).

## License

MIT.
