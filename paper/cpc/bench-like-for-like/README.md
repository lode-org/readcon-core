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

The Snakemake file runs `run_bench.py` and then `run_asv.py`. `asv run` uses `benchmarks/` with warmup time 0, six repeats, and one iteration per sample. The one-thread asv process is pinned to cpu 0. The all-core coordinate benchmark is a second `asv run`. The asv suite times the tip build, ASE, eOn, and the coordinate-only calls in-process. It does not load the release wheel or the second tip build, and it does not interleave arms. The medians below are from `run_bench.py`.

## Results

Measured at revision `ec3108430b3c25323545080639e7fff6b8e05618`. Machine hash `9eb296774121518feb1b187b0f6a109a42de7a5dd39e62ccd37d6e7d329604b8`, `nproc` 8. Every arm on an input agreed on frame count, atom count, and the position checksum (`synthetic` `e0961fc8f22fa99a124453d179521d210e50232ffa936cc3882b96060a87cd54`, `cuh2_band` `0cf5f99ad74425f793c0209c6d1c3a39787efa78a375c889470821c467dda9b9`). `n` is 6. `ratio_over_tip` is the full-frame median divided by `readcon_tip_a` on the same input. `aa_ratio` is `readcon_tip_b` divided by `readcon_tip_a`. Coordinate-only rows have no ratio.

| arm | work | threads | input | median_s | iqr_s | ratio_over_tip | aa_ratio |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| readcon_tip_a | full-frame | 1 | synthetic | 4.783036 | 0.120363 | 1 | 0.973162 |
| readcon_tip_b | full-frame | 1 | synthetic | 4.654668 | 0.280731 | 0.973162 | 0.973162 |
| readcon_release | full-frame | 1 | synthetic | 4.573592 | 0.243217 | 0.956211 | 0.973162 |
| ase | full-frame | 1 | synthetic | 12.690635 | 0.423141 | 2.653259 | 0.973162 |
| eon | full-frame | 1 | synthetic | 5.995901 | 0.041373 | 1.253576 | 0.973162 |
| readcon_positions_1 | coords-only | 1 | synthetic | 0.201480 | 0.044726 |  |  |
| readcon_positions_all | coords-only | 8 | synthetic | 0.030090 | 0.001773 |  |  |
| readcon_tip_a | full-frame | 1 | cuh2_band | 0.001165 | 0.000055 | 1 | 1.008908 |
| readcon_tip_b | full-frame | 1 | cuh2_band | 0.001175 | 0.000162 | 1.008908 | 1.008908 |
| readcon_release | full-frame | 1 | cuh2_band | 0.001116 | 0.000013 | 0.958495 | 1.008908 |
| ase | full-frame | 1 | cuh2_band | 0.002648 | 0.000041 | 2.273563 | 1.008908 |
| eon | full-frame | 1 | cuh2_band | 0.001672 | 0.000067 | 1.435391 | 1.008908 |
| readcon_positions_1 | coords-only | 1 | cuh2_band | 0.000675 | 0.000026 |  |  |
| readcon_positions_all | coords-only | 8 | cuh2_band | 0.001920 | 0.000244 |  |  |

Full values are in `results/summary.csv`. Per-repeat times are in `results/samples.csv`.
