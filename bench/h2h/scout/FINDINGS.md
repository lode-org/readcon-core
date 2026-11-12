# Scout: what is worth adopting

Adopt the lazy coordinate column in `read_positions` and the extended-XYZ scan. Adopt byte-shuffle plus zstd as an opt-in coordinate codec for a corpus store. Leave the CON text reader, `fast_dec`, and whole-file zstd as they are. Do not adopt a trained dictionary or a low-rank trajectory codec on this corpus.

The prototypes live behind `--features scout` in `src/scout`. They are not on the read path. `examples/scout_bench.rs` is the measurement.

## How the numbers were taken

Host: Intel Xeon Processor, x86_64, 8 processors in `/proc/cpuinfo`, `MemTotal` 49342816 KiB. Every arm was pinned with `taskset -c 0`. The campaign log reports `nproc 1` because `available_parallelism` sees that cpuset.

Serial. One warmup, then six samples. Median and interquartile range are the type-7 quantile (NumPy `linear`: index `(n-1)p`). Lossless arms were checked, bit for bit, against `read_positions_with_threads` or `tables_from_extxyz_path` before the clock started. The low-rank arms are lossy and opt-in; their check is the absolute error, not bit identity.

RSS is `VmHWM` of a fresh process that performs the read once, minus the size of the file that process opened. Massif is one run, not six, with Valgrind 3.22 `--tool=massif --pages-as-heap=yes`. Raw logs are `bench/h2h/scout/raw/`. Inputs are the head-to-head generators: 100000 frames of 32 copper atoms (CON, convel, extended XYZ) and one CON frame of 10^6 atoms. Those files are not in git.

## What was surveyed

**Streaming and structural indexing.** simdjson splits a SIMD structural index from value materialization and is faster when the caller does not need a full DOM ([Langdale and Lemire, The VLDB Journal, 2019](https://doi.org/10.1007/s00778-019-00578-5), [arXiv:1902.08318](https://arxiv.org/abs/1902.08318)). CON already has that first stage: `memchr` and an AVX2 newline skip in `ConFrameIterator`. A second newline index would rescan bytes the coordinate parser reads anyway. The remaining cost on a homogeneous trajectory is the per-frame object (JSON, owned header strings, an atom table). The prototype writes `x y z` into one buffer and skips vector sections by line count.

**Float parsing.** Lemire's `fast_float` turns the common case of at most 19 significant digits into one or two 64-bit multiplications ([Software: Practice and Experience 51, 2021](https://doi.org/10.1002/spe.2984), [arXiv:2101.11408](https://arxiv.org/abs/2101.11408); code at [lemire/fast_float](https://github.com/lemire/fast_float)). On the same machine his notes put the Rust port ahead of `lexical` ([blog comparison](https://lemire.me/blog/2021/01/29/number-parsing-at-a-gigabyte-per-second/)). This crate already uses that algorithm as `fast_float2` for the general token, and a shorter kernel (`fast_dec`) for the no-exponent decimals CON actually writes. Replacing the short kernel was the experiment, not a new parser.

**Columnar and compressed storage.** Arrow stores a primitive column as one contiguous buffer ([Arrow Columnar Format](https://arrow.apache.org/docs/format/Columnar.html)). Parquet stores those columns in row groups ([Parquet file format](https://parquet.apache.org/docs/file-format/)). HDF5's shuffle filter regroups byte lanes of a fixed-width type before deflate, and does not compress by itself ([`H5Pset_shuffle`](https://docs.hdfgroup.org/documentation/hdf5/latest/group___d_c_p_l.html)). Zarr chunks an N-dimensional array and compresses each chunk ([Zarr core specification](https://zarr-specs.readthedocs.io/en/stable/v3/core/index.html)); MDAnalysis-shaped trajectories have been stored that way as `.zarrmd` ([zarrtraj](https://zarrtraj.readthedocs.io/en/latest/zarrmd-file-spec/v0.2.0.html)). H5MD is the HDF5 layout for positions, velocities, and observables ([de Buyl, Colberg, and Höfling, Computer Physics Communications 185, 2014](https://doi.org/10.1016/j.cpc.2014.01.018), [arXiv:1308.6382](https://arxiv.org/abs/1308.6382)). MDAnalysis reads H5MD and defaults the chunk to one frame, `(1, n_atoms, 3)` ([H5MD reader](https://docs.mdanalysis.org/stable/documentation_pages/coordinates/H5MD.html); the library paper is [Michaud-Agrawal et al., J. Comput. Chem. 32, 2011](https://doi.org/10.1002/jcc.21787)). ASE stores configurations as database rows rather than a time-major array ([Larsen et al., J. Phys.: Condens. Matter 29, 2017](https://doi.org/10.1088/1361-648X/aa680e)). chemfiles is the multi-format library MDAnalysis delegates to ([chemfiles](https://chemfiles.org)). TNG is GROMACS's container for multi-frame compression ([Lundborg et al., J. Comput. Chem. 35, 2014](https://doi.org/10.1002/jcc.23495)). zstd dictionaries target many similar records under about 100 KiB; a single large frame already has a window ([RFC 8878](https://www.rfc-editor.org/rfc/rfc8878), [zdict.h](https://github.com/facebook/zstd/blob/release/lib/zdict.h)).

`conbin` in this repo is already an uncompressed f64 column. The new codec is the HDF5 shuffle in front of zstd level 3, which is the level the CON writer already uses. One chunk holds every frame, because these arms read every coordinate. A per-frame chunk, as in the MDAnalysis H5MD default, would match random frame access and was not the measured access pattern.

**Low rank and tensor trains.** The first step of a tensor-train SVD is a low-rank factorization of an unfolding ([Oseledets, SIAM J. Sci. Comput. 33, 2011](https://doi.org/10.1137/090752286)). For a trajectory shaped `(frames, atoms, xyz)` that unfolding is the coordinate matrix. MDZ is an error-bounded lossy compressor built for molecular-dynamics trajectories ([Zhao et al., ICDE 2022](https://doi.org/10.1109/ICDE53745.2022.00007)); it was not ported. The prototype is the unfolding: center, Jacobi eigensystem of the Gram matrix, then the smallest rank whose reconstruction stays inside a caller-supplied absolute bound. A non-positive bound is refused. The reader never calls it.

## Speed

Median and interquartile range, seconds. "Bit exact" is against the current reader. The low-rank rows are the absolute error.

| arm | median s | iqr s | check |
| --- | ---: | ---: | --- |
| readcon frames, 100000×32 CON | 0.470 | 0.032 | 100000 frames |
| readcon positions, same file | 0.307 | 0.0016 | baseline |
| column, same file | 0.115 | 0.0022 | bit exact |
| readcon frames, 100000×32 convel | 0.514 | 0.0066 | 100000 frames |
| readcon positions, convel | 0.416 | 0.0026 | baseline |
| column, convel | 0.183 | 0.0021 | bit exact |
| readcon frames, 10^6-atom CON | 0.0496 | 0.00012 | 1 frame |
| readcon positions, 10^6-atom CON | 0.104 | 0.00053 | baseline |
| column, 10^6-atom CON | 0.0366 | 0.00069 | bit exact |
| readcon extended XYZ, 100000×32 | 0.260 | 0.0015 | baseline |
| column extended XYZ | 0.179 | 0.011 | bit exact |
| zstd text + readcon positions, CON | 0.485 | 0.0050 | bit exact |
| zstd text + readcon positions, convel | 0.636 | 0.0075 | bit exact |
| zstd text + readcon positions, 10^6 atoms | 0.124 | 0.00043 | bit exact |
| dict frames + column, CON | 0.252 | 0.0013 | bit exact |
| dict frames + column, convel | 0.430 | 0.0061 | bit exact |
| dict on the whole CON + column | 0.180 | 0.00084 | bit exact |
| shuffle + zstd, CON coordinates | 0.0459 | 0.00076 | bit exact |
| shuffle + zstd, 10^6-atom coordinates | 0.0135 | 0.00012 | bit exact |
| raw f64 column, CON | 0.0189 | 0.0031 | bit exact |
| raw f64 column, 10^6 atoms | 0.00514 | 0.00060 | bit exact |
| low rank, bound 10^-3, CON | 0.204 | 0.00021 | max abs 1.96e-13 |
| low rank, bound 10^-8, CON | 0.202 | 0.0018 | max abs 1.96e-13 |

On the million-atom file the current positions API is slower than `read_all_frames` (0.104 s versus 0.050 s). It walks the frame to find the boundary, parses it, then copies. The column walker does one pass and does not build the atom table.

`fast_dec` against `fast_float2` on 3×10^6 coordinate tokens from the million-atom file, in process, same warmup and six samples: 0 fallbacks, 0 bit mismatches. `fast_dec` median 0.0219 s (IQR 0.00011 s), `fast_float2` median 0.0248 s (IQR 0.000080 s). The short kernel is about 13% faster on this decimal shape. Keep it. Keep `fast_float2` for exponents.

## Size

| file | bytes |
| --- | ---: |
| CON text, 100000×32 | 136700001 |
| convel text | 258400000 |
| extended XYZ | 124700000 |
| CON text, 10^6 atoms | 39589039 |
| raw f64 positions, 100000×32 | 76800000 |
| raw f64 positions, 10^6 atoms | 24000000 |
| whole-file zstd level 3, CON | 11315649 |
| whole-file zstd level 3, convel | 12287192 |
| whole-file zstd level 3, 10^6 atoms | 709563 |
| zstd dictionary, one frame per record, CON | 26855772 |
| same, convel | 27540322 |
| dictionary trained on frames, then one frame for the whole CON | 11726923 |
| shuffle + zstd, CON positions | 521014 |
| shuffle + zstd, 10^6-atom positions | 304586 |
| low rank, either bound | 76874548 |

The 100000-frame generator is `round(((frame*17 + atom*3 + axis) mod 10000) / 1000, 8)`. The million-atom file is an integer lattice written with six decimal places. Both are much more regular than a thermal trajectory. Shuffle groups the identical high bytes of those floats, which is why 136700001 bytes of text become 521014 bytes. A production trajectory with noise in the last digits will not shrink by that factor. The method is still the one HDF5 uses in front of a compressor, and on this host the decode is already faster than parsing the text.

## Memory

`over` is `VmHWM` minus the opened file, in KiB. Massif `over` is the pages-as-heap peak minus the file, in bytes, for the six arms that were traced.

| arm | VmHWM KiB | over KiB | massif peak | massif over |
| --- | ---: | ---: | ---: | ---: |
| readcon frames, CON | 798092 | 664596 |  |  |
| readcon positions, CON | 212472 | 78976 | 223375360 | 86675359 |
| column, CON | 213772 | 80276 | 282902528 | 146202527 |
| readcon positions, convel | 331272 | 78929 |  |  |
| column, convel | 332720 | 80377 |  |  |
| readcon frames, 10^6 atoms | 166524 | 127863 |  |  |
| readcon positions, 10^6 atoms | 315068 | 276407 | 328433664 | 288844625 |
| column, 10^6 atoms | 65220 | 26559 | 81965056 | 42376017 |
| readcon extended XYZ | 282604 | 160827 |  |  |
| column extended XYZ | 201996 | 80219 |  |  |
| shuffle, CON | 228532 | 228024 | 239751168 | 239230154 |
| shuffle, 10^6 atoms | 73804 | 73507 | 81129472 | 80824886 |
| raw f64, CON | 152656 | 77656 |  |  |
| raw f64, 10^6 atoms | 49364 | 25927 |  |  |

On the 100000-frame CON, column and `read_positions` use about the same RSS: the mapped text plus one 76800000-byte buffer. Massif's pages-as-heap peak is higher for the column walker than `VmHWM`; both are reported. On the million-atom file the column walker is the memory win, in both tools, because it does not allocate an atom table for 10^6 atoms. Shuffle's `over` looks large because the opened file is a few hundred kilobytes and the decoded column is tens of megabytes. Its absolute peak matches the column walker on the million-atom file and is far under `read_all_frames` on the 100000-frame file.

## Negative results

A per-frame zstd dictionary does not beat one zstd frame. The dictionary file is 26855772 bytes against 11315649 for whole-file zstd on the same CON, and reading it (0.252 s) is slower than the column walker on the plain text (0.115 s). Training the dictionary and then compressing the whole file (11726923 bytes) is slightly larger than zstd with no dictionary. That matches the zstd guidance: once the input is a single stream inside the window, the dictionary has nothing extra to point at. Dictionaries would matter for a store that compresses each ~1.5 KiB frame as its own message and never sees the neighbors. They are the wrong tool for one trajectory file.

Whole-file zstd plus the current positions parser is slower than the plain text (0.485 s versus 0.307 s on the 100000-frame CON, 0.124 s versus 0.104 s on the million-atom file). Compression here is a size win for archival text, not a read-speed win, until the consumer stops building frames.

Low rank does not compress this trajectory. The max-abs error at rank k of 96 is 9.80, 9.64, 9.25, 8.44, 6.84, 4.13, 2.09 at ranks 1, 2, 4, 8, 16, 32, 64, and 1.96×10^-13 at rank 96. Both requested bounds are met only by keeping every component. The file is 76874548 bytes, larger than the raw column, and the decode (0.20 s) is slower than parsing the text with the column walker. The second tensor-train rank of that basis is 3, and the three-core layout is 76873800 bytes: the same size as the unfolding, which is what a 3-mode train does when the last mode is already width 3. The modular generator is a poor match for a low-rank model. The fit stays opt-in and is not a default.

`fast_float2` is not faster than `fast_dec` on these tokens, and it is not more accurate here: zero mismatches.

## What to adopt

1. Use the column walker for coordinate reads. On this host it is 2.7×, 2.3×, and 2.8× faster than `read_positions` on the 100000-frame CON, the convel, and the million-atom CON, and 1.4× faster than the current extended-XYZ scan. The million-atom RSS falls from 315068 KiB to 65220 KiB. The next change is to call it from `read_positions_with_threads` instead of parsing a `ConFrame` and copying. Full frame objects stay on `read_all_frames` for callers that need headers and sections.

2. Add shuffle-plus-zstd as an opt-in column next to CON text in the corpus store. It is bit-exact to the parsed `f64` values, 521014 bytes against 136700001 of CON text on the 100000-frame file, and the decode is faster than the text parse. Do not replace the CON writer with it. Quote the ratio as what this generator does, not as the ratio of a thermal trajectory. `conbin` is the uncompressed form of the same column; the missing piece is the shuffle.

3. Leave dictionaries, low rank, and the float kernel alone. One zstd frame remains the right compressor when the bytes have to stay CON text. A low-rank fit with an explicit bound is in the prototype for a later corpus that actually has one; it does not earn a default on these files.
