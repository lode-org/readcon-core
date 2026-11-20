# Like-for-like CON reader benchmark

The head-to-head in `paper/cpc/scripts/bench_readers.py` times `read_positions` on the tip, which returns coordinates only and lets Rayon use every core, against release, ASE, and eOn arms that build a full frame on one thread. This directory times the same full-frame work on every arm, and keeps the coordinate-only reads in a separate column.

## Arms

Full-frame, one thread (`RAYON_NUM_THREADS=1`, `n_threads=1`, OpenMP/MKL/OpenBLAS threads 1, `taskset -c 0`):

- `readcon_tip_a` and `readcon_tip_b`: two separate release builds of this tree's Python bindings. The ratio of the two is the A/A noise band.
- `readcon_release`: the PyPI wheel recorded in `pins.json`.
- `ase`: `ase.io.read(path, index=':', format='eon')`.
- `eon_legacy_python`: `loadcons` from eOn's Python fileio at the commit in `pins.json`, before that module delegated CON parsing to readcon. The rows below record this arm as `eon`.
- `eon_svn_cxx`: `Matter::con2matter` from the eOn SVN client at the revision in `pins.json`. The client reads one frame per call, so the driver loops that `FILE` reader until only whitespace is left. Periodic boundaries start on and would rewrite coordinates into the minimum image; the driver calls `deactivatePeriodicBoundaries` first so the checksum is the parsed positions. Per frame, `con2matter` stores two header lines, parses the three cell lengths and three angles, stores two more header lines, and parses the component count, the atom count of each component, and one mass per component. For each component it turns the symbol into an atomic number, skips the next line, and reads `x y z` plus one integer fixed flag. It does not read velocities or forces. The driver recomputes the three angles from the box vectors and copies the mass, atomic number, fixed flag, and positions. The Python side maps the atomic number through the client's symbol table and copies the one fixed flag onto all three axes. `read_con` on the readcon arms returns the symbol and the three fixed flags directly; the harness copies those, the mass, the coordinates, and the cell lengths and angles. `ensure_eon_svn` hashes the pinned sources and the Eigen tree once per session, before any timed repeat, and that result is a session row. The timed end-to-end call spawns the already-built binary and rebuilds the frames in Python. `eon_svn_binary` clocks only the binary. The r4 clock still included the hash; that split is under r4.

Each full-frame arm builds positions, cell, symbols, masses, and fixed flags for every frame. The SVN arm's symbol and fixed flags are the lookup and the expanded flag above, not a second parse of those fields.

Coordinate-only, not used in the ratio column:

- `readcon_positions_1`: `read_positions` at one thread on cpu 0, using the tip-a build.
- `readcon_positions_all`: `read_positions` at `nproc` Rayon threads, BLAS libraries still at one thread, no cpu pin.

## Inputs

`synthetic` is the modulo pattern from `paper/cpc/scripts/bench_readers.py` (`reference`), 100000 frames of 32 Cu atoms. `cuh2_band` is `resources/examples/cuh2_band.con`. Its sha256 is in `pins.json`.

`al_eam_md` is simulation output. The CON files shipped in readcon-core, lode-org/readcon-db, TheochemUI/eOn, and the HaoZeke/anneal-paper-data dataset are single geometries or short bands. `make_al_md.py` runs 1000 Velocity Verlet steps of a 500-atom FCC aluminum cell (lattice 4.05 angstrom, 5x5x5) with rgpot 3.7.0 `EAMAlPot` and writes one frame after each step. The file is `work/al_eam_md.con`. It is larger than 5 MB, so it stays out of git. Frame count, atom count, sha256, and the generating command are in `pins.json`. The synthetic and `cuh2_band` rows stay as first measured. The aluminum rows use 12 repeats.

Before the timed repeats, one equal-work pass compares frame count, atom count, and the sha256 of the little-endian float64 positions. A mismatch aborts the run. That pass is not a timed repeat and is not dropped from the six repeats.

## Protocol

Six repeats per arm per input. The arm/input list is rotated and reversed in ABBA order (forward, reversed, reversed, forward). The clock starts after the import, in a fresh process. No repeat is discarded. The median and IQR are type-7 linear percentiles. Ratios are full-frame median over `readcon_tip_a` for the same work, thread count, and input, reported next to the A/A ratio. `paper/cpc/scripts/host_from_log.py` refuses a ratio when those fields are absent or unequal.

A ratio inside the A/A band, or within 5% of 1, is not a claim. On synthetic the two tip builds separate (A/A 0.958632, Mann-Whitney p 0.010193), so a placement effect of 4.1368% is part of the measurement.

Rows record arm, work, threads, input name, synthetic or real, sha256, n, median, IQR, revision or version, and the sha256 of `/etc/machine-id`.

## Run

From this directory:

```
snakemake -c1
```

The Snakemake file runs `run_bench.py` and then `run_asv.py`. `asv run` uses `benchmarks/` with warmup time 0, six repeats, and one iteration per sample. The one-thread asv process is pinned to cpu 0. The all-core coordinate benchmark is a second `asv run`. The asv suite times the tip build, ASE, eOn, and the coordinate-only calls in-process. It does not load the release wheel or the second tip build, and it does not interleave arms. The medians below are from `run_bench.py`.

## Results

`synthetic` and `cuh2_band` were measured with `n` 6. `al_eam_md` was measured with `n` 12, on the same tip wheels, built from the development tree after tag `v0.23.2`. Machine hash `9eb296774121518feb1b187b0f6a109a42de7a5dd39e62ccd37d6e7d329604b8`, `nproc` 8. Every arm on an input agreed on frame count, atom count, and the position checksum (`synthetic` `e0961fc8f22fa99a124453d179521d210e50232ffa936cc3882b96060a87cd54`, `cuh2_band` `0cf5f99ad74425f793c0209c6d1c3a39787efa78a375c889470821c467dda9b9`, `al_eam_md` `c34013811a9a444b8441dddd244aa22e97685ad058c5a8b08a2c545f89c1f50a`). `ratio_over_tip` is the full-frame median divided by `readcon_tip_a` on the same input. `aa_ratio` is `readcon_tip_b` divided by `readcon_tip_a`. Coordinate-only rows have no ratio.

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
| readcon_tip_a | full-frame | 1 | al_eam_md | 0.514845 | 0.020334 | 1 | 1.001047 |
| readcon_tip_b | full-frame | 1 | al_eam_md | 0.515384 | 0.019761 | 1.001047 | 1.001047 |
| readcon_release | full-frame | 1 | al_eam_md | 0.494274 | 0.014398 | 0.960045 | 1.001047 |
| ase | full-frame | 1 | al_eam_md | 0.792692 | 0.014445 | 1.539671 | 1.001047 |
| eon | full-frame | 1 | al_eam_md | 0.740669 | 0.023000 | 1.438626 | 1.001047 |
| readcon_positions_1 | coords-only | 1 | al_eam_md | 0.034284 | 0.002768 |  |  |
| readcon_positions_all | coords-only | 8 | al_eam_md | 0.021012 | 0.002637 |  |  |

Full values are in `results/summary.csv`. Per-repeat times are in `results/samples.csv`.

## r3

A second campaign wrote `results/r3-rows.csv`, `results/r3-samples.csv`, and `results/r3-summary.csv`. It did not change the rows above. `synthetic` and `cuh2_band` use `n` 6. `al_eam_md` uses `n` 12. The first six repeats interleave every arm and input; the next six continue `al_eam_md` only. `al_eam_md` was regenerated with `make_al_md.py` and matched the pinned sha256. Ratios are over `readcon_tip_a`. Coordinate-only rows have no ratio. The r3 `eon_svn_cxx` rows time the source hash inside each call. The SVN timer includes the start of a second process.

| arm | work | threads | input | median_s | iqr_s | ratio_over_tip | aa_ratio |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| readcon_tip_a | full-frame | 1 | synthetic | 5.682638 | 0.729537 | 1 | 0.941194 |
| readcon_tip_b | full-frame | 1 | synthetic | 5.348462 | 0.921489 | 0.941194 | 0.941194 |
| readcon_release | full-frame | 1 | synthetic | 5.125558 | 0.396924 | 0.901968 | 0.941194 |
| ase | full-frame | 1 | synthetic | 13.084091 | 0.868704 | 2.302468 | 0.941194 |
| eon_svn_cxx | full-frame | 1 | synthetic | 2.748723 | 0.157217 | 0.483705 | 0.941194 |
| eon_legacy_python | full-frame | 1 | synthetic | 6.290727 | 0.292022 | 1.107008 | 0.941194 |
| readcon_positions_1 | coords-only | 1 | synthetic | 0.204737 | 0.032362 |  |  |
| readcon_positions_all | coords-only | 8 | synthetic | 0.032881 | 0.000447 |  |  |
| readcon_tip_a | full-frame | 1 | cuh2_band | 0.001238 | 0.000123 | 1 | 1.029872 |
| readcon_tip_b | full-frame | 1 | cuh2_band | 0.001275 | 0.000162 | 1.029872 | 1.029872 |
| readcon_release | full-frame | 1 | cuh2_band | 0.001175 | 0.000050 | 0.948624 | 1.029872 |
| ase | full-frame | 1 | cuh2_band | 0.002905 | 0.000286 | 2.345978 | 1.029872 |
| eon_svn_cxx | full-frame | 1 | cuh2_band | 0.015490 | 0.000412 |  | 1.029872 |
| eon_legacy_python | full-frame | 1 | cuh2_band | 0.001859 | 0.000205 | 1.501161 | 1.029872 |
| readcon_positions_1 | coords-only | 1 | cuh2_band | 0.000732 | 0.000055 |  |  |
| readcon_positions_all | coords-only | 8 | cuh2_band | 0.001771 | 0.000129 |  |  |
| readcon_tip_a | full-frame | 1 | al_eam_md | 0.543299 | 0.028835 | 1 | 1.001120 |
| readcon_tip_b | full-frame | 1 | al_eam_md | 0.543907 | 0.043854 | 1.001120 | 1.001120 |
| readcon_release | full-frame | 1 | al_eam_md | 0.501152 | 0.045510 | 0.922424 | 1.001120 |
| ase | full-frame | 1 | al_eam_md | 0.849719 | 0.051739 | 1.564000 | 1.001120 |
| eon_svn_cxx | full-frame | 1 | al_eam_md | 0.408146 | 0.029768 | 0.751237 | 1.001120 |
| eon_legacy_python | full-frame | 1 | al_eam_md | 0.756168 | 0.047811 | 1.391809 | 1.001120 |
| readcon_positions_1 | coords-only | 1 | al_eam_md | 0.036152 | 0.002406 |  |  |
| readcon_positions_all | coords-only | 8 | al_eam_md | 0.020277 | 0.002655 |  |  |

The `eon_svn_cxx` `cuh2_band` row is not like-for-like because the source
hash was timed inside each call. Its historical unequal-work quotient is
12.509741; `r3-summary.csv` retains the full value only in
`historical_unequal_ratio`, outside `ratio_over_tip`.

Full values are in `results/r3-summary.csv`. Per-repeat times are in `results/r3-samples.csv`.

## r4

`synthetic` and `cuh2_band` were measured again at `n` 12, on the same pinned files, tip wheels, release wheel, and eOn revisions. `al_eam_md` was not remeasured; its `n` 12 rows stay in the r3 files. The arm order is the same ABBA rotation. Single-thread arms use `taskset -c 0` and one thread for Rayon and for the BLAS libraries. No repeat was discarded. Checksums match the r3 rows for both inputs. Ratios are over `readcon_tip_a`.

| arm | work | threads | input | median_s | iqr_s | ratio_over_tip | aa_ratio |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| readcon_tip_a | full-frame | 1 | synthetic | 4.894836 | 0.209594 | 1 | 0.958632 |
| readcon_tip_b | full-frame | 1 | synthetic | 4.692345 | 0.141615 | 0.958632 | 0.958632 |
| readcon_release | full-frame | 1 | synthetic | 4.700546 | 0.154412 | 0.960307 | 0.958632 |
| ase | full-frame | 1 | synthetic | 12.619416 | 0.434115 | 2.578108 | 0.958632 |
| eon_svn_cxx | full-frame | 1 | synthetic | 2.660744 | 0.041397 | 0.543582 | 0.958632 |
| eon_legacy_python | full-frame | 1 | synthetic | 5.982422 | 0.098501 | 1.222190 | 0.958632 |
| readcon_positions_1 | coords-only | 1 | synthetic | 0.200997 | 0.038604 |  |  |
| readcon_positions_all | coords-only | 8 | synthetic | 0.027451 | 0.008264 |  |  |
| readcon_tip_a | full-frame | 1 | cuh2_band | 0.001186 | 0.000054 | 1 | 1.025915 |
| readcon_tip_b | full-frame | 1 | cuh2_band | 0.001217 | 0.000136 | 1.025915 | 1.025915 |
| readcon_release | full-frame | 1 | cuh2_band | 0.001180 | 0.000109 | 0.994729 | 1.025915 |
| ase | full-frame | 1 | cuh2_band | 0.002680 | 0.000131 | 2.259222 | 1.025915 |
| eon_svn_cxx | full-frame | 1 | cuh2_band | 0.015214 | 0.000160 | 12.824452 | 1.025915 |
| eon_legacy_python | full-frame | 1 | cuh2_band | 0.001665 | 0.000055 | 1.403531 | 1.025915 |
| readcon_positions_1 | coords-only | 1 | cuh2_band | 0.000660 | 0.000057 |  |  |
| readcon_positions_all | coords-only | 8 | cuh2_band | 0.001899 | 0.000666 |  |  |

The A/A band for an input is the closed interval between the `readcon_tip_a` and `readcon_tip_b` medians. A release median outside that interval is marked in `results/r4-compare.csv`. The rank test is a two-sided Mann-Whitney U on the twelve repeat times (`scipy.stats.mannwhitneyu`, method `auto`).

| input | source | A/A ratio | A/A p | release ratio | release p | release outside A/A band |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| synthetic | r4 | 0.958632 | 0.010193 | 0.960307 | 0.030383 | no |
| cuh2_band | r4 | 1.025915 | 0.099877 | 0.994729 | 0.435731 | yes |
| al_eam_md | r3 | 1.001120 | 0.839860 | 0.922424 | 0.005108 | yes |

On synthetic the release median (4.700546 s) lies between the two tip medians (4.692345 s and 4.894836 s), so the release-vs-tip gap is inside the A/A band. The two rank tests both separate `readcon_tip_a` from the other build and from release; release is not a shift beyond that band. On `cuh2_band` the release median is 6.25 microseconds below the lower tip median, which the flag calls outside, and the rank test does not separate those samples (p 0.435731). The release ratio is closer to 1 than the A/A ratio is. On `al_eam_md` the release median is below both tip medians and the rank test separates them (p 0.005108); that gap is outside the A/A band. Those aluminum times are the r3 samples, not a new run.

The SVN clock on `cuh2_band` is not the four-frame parse. After the campaign, twelve repeats on cpu 0 with the thread variables at 1 timed the pieces of `_full_eon_svn`. The pin-check median is 0.014059 s. Starting the binary with no path, which exits before parsing, is 0.001178 s. The binary on `cuh2_band` is 0.001749 s, and the Python rebuild of that output is 0.000231 s. The whole call, pin check included, is 0.015942 s, next to the campaign arm median of 0.015214 s. The pin check is most of the 12.82 ratio. On `synthetic` the same pin check is inside a 2.597 s whole call (binary 1.734 s, Python rebuild 0.833 s), next to the campaign arm median of 2.661 s, which is 0.544 times the tip. There the time is the parse and the rebuild.

Full values are in `results/r4-summary.csv`, `results/r4-compare.csv`, and `results/r4-overhead.csv`. Per-repeat times are in `results/r4-samples.csv`.

## r5

The source-hash pin runs once, before any timed repeat. `results/r5-session.csv` records it: result ok, 0.014174 s, 7 pinned files, SVN revision 1213. The timed end-to-end arm spawns that binary and rebuilds the frames in Python. `eon_svn_binary` clocks the binary only. Both ran with `readcon_tip_a` and `readcon_tip_b` on `synthetic`, `cuh2_band`, and `al_eam_md`, twelve repeats, ABBA rotation, the same files, tip wheels, SVN revision, and machine. The r2, r3, and r4 result files were left as they were. Checksums match those earlier rows. The end-to-end ratio is full-frame median over `readcon_tip_a` for the same work, thread count, and input. The binary clock stops before the Python rebuild, and the checksum is still the parsed positions. Its `ratio_over_tip` cell stays empty, because binary over full-frame is unequal work.

| arm | work | threads | input | median_s | iqr_s | ratio_over_tip | aa_ratio |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| readcon_tip_a | full-frame | 1 | synthetic | 4.901454 | 0.227641 | 1 | 0.976835 |
| readcon_tip_b | full-frame | 1 | synthetic | 4.787911 | 0.163262 | 0.976835 | 0.976835 |
| eon_svn_cxx | full-frame | 1 | synthetic | 2.647061 | 0.044325 | 0.540056 | 0.976835 |
| eon_svn_binary | binary | 1 | synthetic | 1.796377 | 0.015614 |  | 0.976835 |
| readcon_tip_a | full-frame | 1 | cuh2_band | 0.001204 | 0.000022 | 1 | 1.014290 |
| readcon_tip_b | full-frame | 1 | cuh2_band | 0.001222 | 0.000061 | 1.014290 | 1.014290 |
| eon_svn_cxx | full-frame | 1 | cuh2_band | 0.001868 | 0.000251 | 1.550813 | 1.014290 |
| eon_svn_binary | binary | 1 | cuh2_band | 0.001616 | 0.000085 |  | 1.014290 |
| readcon_tip_a | full-frame | 1 | al_eam_md | 0.519944 | 0.007576 | 1 | 0.984967 |
| readcon_tip_b | full-frame | 1 | al_eam_md | 0.512128 | 0.016792 | 0.984967 | 0.984967 |
| eon_svn_cxx | full-frame | 1 | al_eam_md | 0.367027 | 0.009157 | 0.705897 | 0.984967 |
| eon_svn_binary | binary | 1 | al_eam_md | 0.321986 | 0.003766 |  | 0.984967 |

The three A/A ratios (0.976835, 1.014290, 0.984967) sit within 5% of 1, so they are not claims. On `cuh2_band` the end-to-end ratio is 1.550813. The r4 ratio of 12.82 on that file included the pin check inside every call.

`readcon_tip` full-frame on `synthetic` has campaign median 4.901454 s. The coordinate-only read in the profile process, one thread on cpu 0, was 0.251996 s. Copies span 69.95% to 73.4% of the full-frame call across all four recorded walks. The three rows of `results/r5-profile.csv` and the walk in `results/profile-r5.txt` are that recorded set, produced by `profile_r5.py`. `python_build_s` inside `read_con` is the NumPy slab wrap. It is under 0.03 ms on each recorded call. Per-frame Python objects are built when the harness first indexes the frame.

cProfile on the same function counted 0.722 s inside `read_con` and 6.836 s in the Python body, out of 8.714 s accounted. The profiler stretched that wall time to 9.088 s. py-spy native samples of one uninstrumented call, kept to stacks inside `_full_readcon` (1244 of 1534), put copies at 67.3%, object construction at 22.8%, the Rust parse at 9.1%, and the slab pack at 0.8%. Sampling slowed that call. perf recorded 2568 `cpu-clock` user samples on cpu 0. The retained r10 logs contain neither the exact hardware-counter refusal nor the `perf_event_paranoid` value, so this record reports neither. The flat samples land on the Python evaluator, NumPy index and pack, the pyo3 field getters, and `parse_coord_row_at` / `ingest_coord_rows_f64`.

Full values are in `results/r5-summary.csv`, `results/r5-session.csv`, `results/r5-profile.csv`, and `results/profile-r5.txt`. Per-repeat times are in `results/r5-samples.csv`.
