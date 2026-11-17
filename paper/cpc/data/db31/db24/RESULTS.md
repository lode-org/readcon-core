# db24 fair comparison

Commit `a584a28816c2f603c8c94759fdf45d86fc20f069`, tree `c1c761697b9aa9e57f3f1943868811285c5d8d03`. Host Linux 6.12.113+, Intel(R) Xeon(R) Processor, 8 CPUs. `RAYON_NUM_THREADS` was unset for the first block. n=12, serial. OMP_NUM_THREADS=1, OPENBLAS_NUM_THREADS=1, MKL_NUM_THREADS=1, NUMEXPR_NUM_THREADS=1. cpuinfo 2700.0 MHz. Kernel 6.12.113+. CPU Intel(R) Xeon(R) Processor. serial=true. quantile type-7. Arm order is db18, raw, shuffle, ase; reversed on odd sample indexes. Warm selected is one pass of i*17 mod 64, each frame once; seconds are the mean per frame. There is no frame cache. The median is type-7. Each time cell is that median, and the parentheses are the type-7 IQR. Both percentiles use `numpy` method `linear`.

`bench/db23` names unpublished commit `82746979b2a34851019d066f0ead3d3812b98ee2` for tree `4a1b19288f7c66a650ce6e0aad7b88db8c82daaf`. That commit is not in the published history. The published commit for the same tree is `00d32136e9acdbc84fd0297d68b812b0facaedee`. db23 and db22 are unchanged.

db22 lists a warm-selected shuffle/raw ratio of 0.573. That figure is superseded. The raw arm copied the blob before it looked at the tag, which inflated raw. The corrected comparisons are the db23 and db24 warm-selected rows.

## Level and window

`build/db31-staging/db24/levers.json` is the stdout of `record_db24_levers` (release, ignored). One 100k-atom frame, positions and forces, six scalar columns. Each time is the mean of 20 rounds after 3 untimed rounds. The same rounds are in `samples_us`, and `iqr_us` is their type-7 IQR. Long-distance matching is off. `tables.json` is written by `fair_ase_protocol.record_table_usage`.

Two empty `thread::scope` workers cost 115 µs (IQR 68.50 µs).

| level | window | bytes | one thread µs (IQR) | two threads µs (IQR) |
| --- | --- | --- | --- | --- |
| 3 | 20 | 12471 | 530 (20.00) | 420 (180.25) |
| 3 | 12 | 24418 | 372 (13.00) | 358 (201.00) |
| 1 | 12 | 24651 | 374 (19.00) | 314 (152.50) |
| -5 | 12 | 36107 | 327 (8.00) | 268 (20.00) |
| -1 | 12 | 24562 | 375 (20.25) | 447 (244.00) |

Level 3 and a 4 KiB window are the parameters these fair rows used. Level -5 at that window is 45 µs under level 3 on the mean, and the wider of those two IQRs is 13 µs, so that gap is outside the lever's own spread. The compressed columns grow from 24418 bytes to 36107 bytes. The level stays 3. The comparison is against this lever IQR, not a selected-row IQR.

Leaving forces uncompressed would store 2400000 bytes a frame. Shuffling only the high four bytes of each `f64` is 22219 bytes of zstd plus 2400000 raw bytes, and that decode plus the copy is 393 µs (IQR 10.75 µs). Both stay fully shuffled.

## How the two arms run

A single frame is decoded on the calling thread for raw and for shuffle. The shuffled path decompresses the three lanes into reused buffers and unshuffles them straight into `x, y, z` order. It does not scatter one lane at a time. A range or a full shuffle read splits frames across `RAYON_NUM_THREADS` workers, or across the process thread count when that variable is unset. Raw range and raw full stay on one thread. The second table is the warm rows again with `RAYON_NUM_THREADS=1`.

## Sizes

| | db18 | raw | shuffle-zstd | ASE |
| --- | --- | --- | --- | --- |
| traj-100k file | 341966848 | 341966848 | 36569088 | 384503808 |
| `frames_soa` values | 307208960 | 307208960 | 1583727 | |

`frames_soa` values are the `value_bytes` rows in `build/db31-staging/db24/tables.json`, written by `fair_ase_protocol.record_table_usage`.

## Times

| op | cache | db18 | raw | shuffle-zstd | ASE | shuffle/raw |
| --- | --- | --- | --- | --- | --- | --- |
| insert |  | 1.2194e+00 (4.8268e-02) | 2.3528e+00 (1.9406e-01) | 2.2932e+00 (1.8895e-01) | 1.3500e+00 (9.6683e-02) | 0.9747 |
| full_read | cold | 7.0870e-01 (2.2409e-01) | 5.9783e-01 (1.2736e-01) | 9.7501e-02 (3.8641e-02) | 2.0703e+00 (1.0259e-01) | 0.1631 |
| selected | cold | 5.9534e-03 (1.0712e-03) | 5.4467e-03 (1.3947e-03) | 1.4368e-03 (1.4969e-04) | 2.9459e-02 (3.7043e-03) | 0.2638 |
| range | cold | 1.7550e-01 (4.7635e-02) | 1.4869e-01 (5.5284e-02) | 2.9974e-02 (4.5802e-03) | 4.8547e-01 (9.3611e-03) | 0.2016 |
| full_read | warm | 3.5120e-01 (8.4419e-02) | 2.7337e-01 (6.1125e-02) | 9.9443e-02 (5.6871e-02) | 1.7744e+00 (1.3024e-01) | 0.3638 |
| selected | warm | 2.7169e-03 (1.7829e-04) | 2.5570e-03 (2.3838e-04) | 2.0830e-03 (1.9984e-04) | 2.3595e-02 (3.2850e-04) | 0.8146 |
| range | warm | 1.1737e-01 (3.6512e-02) | 8.8544e-02 (2.7140e-02) | 2.6113e-02 (8.1983e-03) | 4.2730e-01 (2.0697e-02) | 0.2949 |

The shuffle/raw column is the ratio of the two medians. The paired ratio below is the type-7 median of shuffle/raw at the same sample index. The CI is a 10000-draw percentile bootstrap of that median (numpy Generator seed 0).

insert: paired median 0.9761, 95% CI [0.8905, 1.0033]. Shuffle faster in 8 of 12, slower in 4, ties 0. The paired interval includes 1.

full_read cold: paired median 0.1801, 95% CI [0.1382, 0.2157]. Shuffle faster in 12 of 12, slower in 0, ties 0. The paired interval is below 1, so shuffle is faster.

selected cold: paired median 0.2541, 95% CI [0.1972, 0.2937]. Shuffle faster in 12 of 12, slower in 0, ties 0. The paired interval is below 1, so shuffle is faster.

range cold: paired median 0.2000, 95% CI [0.1830, 0.2692]. Shuffle faster in 12 of 12, slower in 0, ties 0. The paired interval is below 1, so shuffle is faster.

full_read warm: paired median 0.3752, 95% CI [0.2900, 0.4801]. Shuffle faster in 12 of 12, slower in 0, ties 0. The paired interval is below 1, so shuffle is faster.

selected warm: paired median 0.8068, 95% CI [0.7906, 0.8378]. Shuffle faster in 12 of 12, slower in 0, ties 0. The paired interval is below 1, so shuffle is faster.

range warm: paired median 0.3096, 95% CI [0.2859, 0.3231]. Shuffle faster in 12 of 12, slower in 0, ties 0. The paired interval is below 1, so shuffle is faster.

A slower row is inside the noise when the relative gap of the medians is no larger than the wider of the two IQR/median ratios, and no larger than 0.05 when both spreads are tighter than that. The paired interval is the one used when saying a row is faster.

With `RAYON_NUM_THREADS` unset, warm full reads are faster on the paired interval.

`READCON_DB_COOKED_CODEC=raw` keeps RCSO. The name is case-sensitive; the only other accepted value is `shuffle-zstd`. A reader from before db20 cannot open a corpus written with the shuffle default.

### `RAYON_NUM_THREADS=1`

| op | cache | db18 | raw | shuffle-zstd | ASE | shuffle/raw |
| --- | --- | --- | --- | --- | --- | --- |
| full_read | warm | 3.4983e-01 (7.5600e-02) | 2.6946e-01 (2.3556e-02) | 1.7353e-01 (1.7193e-02) | 1.7323e+00 (1.1922e-01) | 0.6440 |
| selected | warm | 2.6726e-03 (2.0626e-04) | 2.5772e-03 (1.2252e-04) | 2.0891e-03 (5.9839e-05) | 2.3605e-02 (3.4583e-04) | 0.8106 |
| range | warm | 1.1156e-01 (3.4967e-02) | 9.4467e-02 (3.9834e-02) | 4.1378e-02 (1.5921e-02) | 4.4054e-01 (1.1955e-02) | 0.4380 |

RAYON=1 full_read warm: paired median 0.6516, 95% CI [0.6196, 0.7122]. Shuffle faster in 12 of 12, slower in 0, ties 0. The paired interval is below 1, so shuffle is faster.

RAYON=1 selected warm: paired median 0.8227, 95% CI [0.8054, 0.8360]. Shuffle faster in 12 of 12, slower in 0, ties 0. The paired interval is below 1, so shuffle is faster.

RAYON=1 range warm: paired median 0.5411, 95% CI [0.4607, 0.5725]. Shuffle faster in 12 of 12, slower in 0, ties 0. The paired interval is below 1, so shuffle is faster.

Single-thread warm full reads are faster: the paired interval is below 1.
