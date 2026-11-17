# db26 selected, cold, and raw across commits

Commit `a584a28816c2f603c8c94759fdf45d86fc20f069`, tree `c1c761697b9aa9e57f3f1943868811285c5d8d03`. Raw comparison base `aedcbda468d208278b8699b80c6db743edcdc21e` tree `4ec91d84f06cb9dada3326231d811d9ea0063534`. Host Linux 6.12.113+, Intel(R) Xeon(R) Processor, 8 CPUs. OMP_NUM_THREADS=1, OPENBLAS_NUM_THREADS=1, MKL_NUM_THREADS=1, NUMEXPR_NUM_THREADS=1. cpuinfo 2700.0 MHz. Kernel 6.12.113+. CPU Intel(R) Xeon(R) Processor. serial=true. quantile type-7. n=12, serial. The median is type-7. Parentheses are the type-7 IQR. The paired CI is a 10000-draw percentile bootstrap of the ratio at the same sample index (numpy Generator seed 0). Odd sample indexes reverse the arm order. Load average at the start of the timed block was 0.45, 0.96, 0.83.

db24 and db25 are unchanged. db25 did not repeat selected or cold. Those rows are here because `d671c32` unshuffles into the caller buffer. That commit is in this history, and this measurement is `a584a288`.

## Summary

| comparison | op | threads | cache | ratio of medians | paired median | 95% CI | faster |
| --- | --- | --- | --- | --- | --- | --- | --- |
| shuffle/raw | selected | unset | cold | 0.2680 | 0.2525 | [0.2350, 0.2957] | 12/12 |
| shuffle/raw | full_read | unset | cold | 0.1759 | 0.1740 | [0.1488, 0.1843] | 12/12 |
| shuffle/raw | range | unset | cold | 0.1709 | 0.1721 | [0.1485, 0.1923] | 12/12 |
| shuffle/raw | selected | unset | warm | 0.8062 | 0.7965 | [0.7818, 0.8087] | 12/12 |
| a584a288/aedcbda4 raw | full_read | unset | warm | 1.0934 | 1.0446 | [0.8407, 1.2585] | 5/12 |
| a584a288/aedcbda4 raw | range | unset | warm | 1.0258 | 1.0183 | [0.8724, 1.1911] | 6/12 |
| a584a288/aedcbda4 raw | full_read | 1 | warm | 1.0002 | 1.0231 | [0.8372, 1.2127] | 5/12 |
| a584a288/aedcbda4 raw | range | 1 | warm | 0.9375 | 0.9285 | [0.7693, 1.0923] | 7/12 |

## Shuffle versus raw

Arm order is raw, shuffle, reversed on odd indexes. Warm selected is one pass of i*17 mod 64, and the seconds are the mean per frame. Cold advises `DONTNEED` outside the clock, then opens and reads inside it. There is no frame cache.

| op | cache | raw | shuffle-zstd | shuffle/raw | paired median | 95% CI | faster |
| --- | --- | --- | --- | --- | --- | --- | --- |
| full_read | cold | 4.9704e-01 (5.0713e-02) | 8.7410e-02 (1.2515e-02) | 0.1759 | 0.1740 | [0.1488, 0.1843] | 12/12 |
| selected | cold | 5.5541e-03 (5.0727e-04) | 1.4883e-03 (1.5756e-04) | 0.2680 | 0.2525 | [0.2350, 0.2957] | 12/12 |
| range | cold | 1.3647e-01 (2.1310e-02) | 2.3326e-02 (5.9754e-03) | 0.1709 | 0.1721 | [0.1485, 0.1923] | 12/12 |
| selected | warm | 2.5350e-03 (1.6268e-04) | 2.0436e-03 (1.1703e-04) | 0.8062 | 0.7965 | [0.7818, 0.8087] | 12/12 |

full_read cold: paired median 0.1740, 95% CI [0.1488, 0.1843]. shuffle faster in 12 of 12, slower in 0, ties 0. The paired interval is below 1, so shuffle is faster.

selected cold: paired median 0.2525, 95% CI [0.2350, 0.2957]. shuffle faster in 12 of 12, slower in 0, ties 0. The paired interval is below 1, so shuffle is faster.

range cold: paired median 0.1721, 95% CI [0.1485, 0.1923]. shuffle faster in 12 of 12, slower in 0, ties 0. The paired interval is below 1, so shuffle is faster.

selected warm: paired median 0.7965, 95% CI [0.7818, 0.8087]. shuffle faster in 12 of 12, slower in 0, ties 0. The paired interval is below 1, so shuffle is faster.

## Raw full and range, this commit versus aedcbda4

Both arms are `READCON_DB_COOKED_CODEC=raw`. Each arm reads the corpus it wrote. The ratio is this commit over `aedcbda4`. Arm order is tip, aedcbda4, reversed on odd indexes. The load average is the 1-minute value sampled before each pair.

| op | threads | aedcbda4 | a584a288 | tip/base | paired median | 95% CI | tip faster | load 1m median |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| full_read | unset | 2.0834e-01 (5.5084e-02) | 2.2779e-01 (5.1670e-02) | 1.0934 | 1.0446 | [0.8407, 1.2585] | 5/12 | 0.67 |
| range | unset | 5.8174e-02 (8.0720e-03) | 5.9676e-02 (9.1297e-03) | 1.0258 | 1.0183 | [0.8724, 1.1911] | 6/12 | 0.67 |
| full_read | 1 | 2.1230e-01 (3.7364e-02) | 2.1234e-01 (3.9149e-02) | 1.0002 | 1.0231 | [0.8372, 1.2127] | 5/12 | 0.72 |
| range | 1 | 6.5030e-02 (1.3191e-02) | 6.0964e-02 (8.4530e-03) | 0.9375 | 0.9285 | [0.7693, 1.0923] | 7/12 | 0.72 |

RAYON=unset raw full_read: paired median 1.0446, 95% CI [0.8407, 1.2585]. a584a288 faster in 5 of 12, slower in 7, ties 0. The paired interval includes 1.

RAYON=unset raw range: paired median 1.0183, 95% CI [0.8724, 1.1911]. a584a288 faster in 6 of 12, slower in 6, ties 0. The paired interval includes 1.

RAYON=1 raw full_read: paired median 1.0231, 95% CI [0.8372, 1.2127]. a584a288 faster in 5 of 12, slower in 7, ties 0. The paired interval includes 1.

RAYON=1 raw range: paired median 0.9285, 95% CI [0.7693, 1.0923]. a584a288 faster in 7 of 12, slower in 5, ties 0. The paired interval includes 1.

Per-sample 1, 5, and 15 minute load averages are in `ab.json` under `load_raw_unset` and `load_raw_rayon_1`.

## High byte, same columns on both sides

`high_byte.json` is one 100k-atom frame, positions `(i * 0.125, 0.5, 1.0)` and forces `(x * 0.5, 0.25, 0.5)`, byte-shuffled per lane. zstd level 3, window log 12, long-distance matching off. Each time is the mean of 20 rounds after 3 untimed rounds, and the parenthesis is the type-7 IQR of those rounds. A row's uncompressed size, full-shuffle size, and high-four size are the same lanes. The db24 sentence compared uncompressed forces with a high-four figure that also included positions. That mix is not repeated.

| columns | lanes | uncompressed | full shuffle zstd | full decode µs | high-four zstd | low-four raw | high-four decode+copy µs |
| --- | --- | --- | --- | --- | --- | --- | --- |
| positions_and_forces | 6 | 4800000 | 24418 | 355 (2.25) | 22219 | 2400000 | 331 (1.00) |
| forces | 3 | 2400000 | 12206 | 164 (2.00) | 11109 | 1200000 | 166 (0.25) |

Full shuffle stores only the zstd bytes. The high-four scheme stores the zstd of the high four bytes plus the low four bytes raw. On both column sets the full-shuffle blob is the smaller of the two.

## Sizes

| corpus | data.mdb |
| --- | --- |
| raw | 341966848 |
| shuffle | 36569088 |
| aedcbda4 | 341966848 |

`tables.json` is `fair_ase_protocol.record_table_usage`.
