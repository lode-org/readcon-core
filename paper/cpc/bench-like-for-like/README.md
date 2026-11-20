# Like-for-like CON reader benchmark

The head-to-head in `paper/cpc/scripts/bench_readers.py` times `read_positions` on the tip, which returns coordinates only and lets Rayon use every core, against release, ASE, and eOn arms that build a full frame on one thread. This directory times the same full-frame work on every arm, and keeps the coordinate-only reads in a separate column.

## Arms

Full-frame, one thread (`RAYON_NUM_THREADS=1`, `n_threads=1`, OpenMP/MKL/OpenBLAS threads 1, `taskset -c 0`):

- `readcon_tip_a` and `readcon_tip_b`: two separate release builds of this tree's Python bindings. The ratio of the two is the A/A noise band.
- `readcon_release`: the PyPI wheel recorded in `pins.json`.
- `ase`: `ase.io.read(path, index=':', format='eon')`.
- `eon`: `loadcons` from eOn's own reader at the commit in `pins.json`, before that module called the readcon package.

Each full-frame arm builds positions, cell, symbols, masses, and fixed flags for every frame.

Coordinate-only, not used in the ratio column:

- `readcon_positions_1`: `read_positions` at one thread on cpu 0, using the tip-a build.
- `readcon_positions_all`: `read_positions` at `nproc` Rayon threads, BLAS libraries still at one thread, no cpu pin.

## Inputs

`synthetic` is the modulo pattern from `paper/cpc/scripts/bench_readers.py` (`reference`), 100000 frames of 32 Cu atoms. `cuh2_band` is `resources/examples/cuh2_band.con`. Its sha256 is in `pins.json`.

Before the timed repeats, one equal-work pass compares frame count, atom count, and the sha256 of the little-endian float64 positions. A mismatch aborts the run. That pass is not a timed repeat and is not dropped from the six repeats.

## Protocol

Six repeats per arm per input. The arm/input list is rotated and reversed in ABBA order (forward, reversed, reversed, forward). The clock starts after the import, in a fresh process. No repeat is discarded. The median and IQR are type-7 linear percentiles. Ratios are full-frame median over `readcon_tip_a` for the same work, thread count, and input, reported next to the A/A ratio. `paper/cpc/scripts/host_from_log.py` refuses a ratio when those fields are missing or different.

Rows record arm, work, threads, input name, synthetic or real, sha256, n, median, IQR, revision or version, and the sha256 of `/etc/machine-id`.

## Run

From this directory:

```
snakemake -c1
```

The Snakemake file runs `run_bench.py` and then `run_asv.py`. `asv run` uses `benchmarks/` with warmup time 0, six repeats, and one iteration per sample. The one-thread asv process is pinned to cpu 0. The all-core coordinate benchmark is a second `asv run`.
