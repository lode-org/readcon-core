# Clean run

## Machine and software

Host `cursor`, Ubuntu 24.04.5 LTS, kernel 6.12.94+.
CPU Intel(R) Xeon(R) Processor, family 6, model 207, stepping 2, 2400.000 MHz, 8 hardware threads.
Memory 49342904 kB.
Recorded 2026-10-14T13:40:03Z.

- Python 3.12.3
- rustc rustc 1.88.0 (6b00bc388 2025-06-23)
- g++ g++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0
- gfortran GNU Fortran (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0
- Julia julia version 1.10.10
- readcon 0.17.0 at `b93a54eb8b9a6211b14ca07a484c6891477c98bc`
- readcon-db 0.1.8 at `55214d138b9c1345e4fba41582a48a936f96312c` (Merge pull request #21 from lode-org/fix/lmdb-map-size)
- ASE 3.29.0, numpy 2.5.4, scipy 1.18.1
- h5py 3.16.0, chemfiles 0.10.4, MDAnalysis 2.10.0
- Repeats 30. BCa interval of the median, 9999 draws, seed 20261011, alpha 0.05.
- Cold cache: sync + drop_caches 3 + posix_fadvise DONTNEED.

## Trajectory

The repeated payload is 10,000 copies of `resources/test/cuh2.con` (218 atoms, 216 copper atoms fixed, two hydrogen atoms free).
The varying payload is a velocity-Verlet EMT trajectory of that checkpoint at 1 fs and 300 K. Only the free hydrogen atoms move. Every free-coordinate frame is distinct.

| payload | n_frames | n_atoms | n_free | md_seconds | integrator | timestep_fs | temperature_K | seed | potential | initial_energy_eV | max_abs_step_A | n_distinct_free_frames | fixed_atom_max_abs_drift_A | rmsd_first_last_A | repeated-10k_con_bytes | repeated-10k_xyz_bytes | repeated-10k_h5_bytes | repeated-10k_extxyz_bytes | repeated-10k_traj_bytes | varying-md_con_bytes | varying-md_xyz_bytes | varying-md_h5_bytes | varying-md_extxyz_bytes | varying-md_traj_bytes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| varying-md | 10000 | 218 | 2 | 124.776 | VelocityVerlet | 1 | 300 | 20261014 | ASE EMT | 50.85838443750094 | 0.04905068816820801 | 10000 | 0 | 12.03848069719289 | 167710000 | 70330000 | 52897172 | 182330000 | 54370434 | 92030997 | 70561913 | 52897172 | 182330000 | 101006447 |

## Reads

Each repeat times one-thread readcon, then the peer. The ratio is readcon divided by the peer. A ratio below 1 means readcon finished sooner. Holm adjustment is over this read family.

| payload | cache | peer | n_pair_ok | median_readcon_s | median_peer_s | median_ratio_readcon_over_peer | bca_low | bca_high | p_raw | holm_p | readcon_faster |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| repeated-10k | cold | ase_extxyz | 30 | 1.18834 | 4.34239 | 0.272837 | 0.270653 | 0.274181 | 0.0001 | 0.002 | 1 |
| repeated-10k | cold | ase_traj | 30 | 1.19637 | 0.859613 | 1.40472 | 1.38512 | 1.41467 | 0.0001 | 0.002 | 0 |
| repeated-10k | cold | chemfiles_xyz | 30 | 1.20366 | 0.486681 | 2.478 | 2.46599 | 2.48718 | 0.0001 | 0.002 | 0 |
| repeated-10k | cold | h5py_h5md | 30 | 1.19737 | 0.0344504 | 34.9014 | 33.5436 | 35.7919 | 0.0001 | 0.002 | 0 |
| repeated-10k | cold | mda_h5md | 30 | 1.20528 | 5.85778 | 0.204921 | 0.20324 | 0.207436 | 0.0001 | 0.002 | 1 |
| repeated-10k | warm | ase_extxyz | 30 | 1.10833 | 4.27257 | 0.259202 | 0.258314 | 0.259596 | 0.0001 | 0.002 | 1 |
| repeated-10k | warm | ase_traj | 30 | 1.09517 | 0.835136 | 1.31474 | 1.30905 | 1.33758 | 0.0001 | 0.002 | 0 |
| repeated-10k | warm | chemfiles_xyz | 30 | 1.08808 | 0.476651 | 2.28858 | 2.27947 | 2.29349 | 0.0001 | 0.002 | 0 |
| repeated-10k | warm | h5py_h5md | 30 | 1.07792 | 0.0146068 | 74.3144 | 73.5683 | 74.8774 | 0.0001 | 0.002 | 0 |
| repeated-10k | warm | mda_h5md | 30 | 1.10137 | 5.92159 | 0.18649 | 0.185 | 0.186823 | 0.0001 | 0.002 | 1 |
| varying-md | cold | ase_extxyz | 30 | 1.22197 | 4.32789 | 0.28186 | 0.279921 | 0.282661 | 0.0001 | 0.002 | 1 |
| varying-md | cold | ase_traj | 30 | 1.22166 | 1.27733 | 0.960198 | 0.95214 | 0.964039 | 0.0001 | 0.002 | 1 |
| varying-md | cold | chemfiles_xyz | 30 | 1.21807 | 0.489812 | 2.49168 | 2.47411 | 2.50693 | 0.0001 | 0.002 | 0 |
| varying-md | cold | h5py_h5md | 30 | 1.24282 | 0.0337123 | 37.1961 | 35.5481 | 37.7179 | 0.0001 | 0.002 | 0 |
| varying-md | cold | mda_h5md | 30 | 1.23006 | 5.93265 | 0.207952 | 0.204458 | 0.209837 | 0.0001 | 0.002 | 1 |
| varying-md | warm | ase_extxyz | 30 | 1.19614 | 4.25303 | 0.281127 | 0.280583 | 0.281468 | 0.0001 | 0.002 | 1 |
| varying-md | warm | ase_traj | 30 | 1.17242 | 1.24612 | 0.940119 | 0.935984 | 0.948151 | 0.0001 | 0.002 | 1 |
| varying-md | warm | chemfiles_xyz | 30 | 1.15483 | 0.473194 | 2.4446 | 2.43676 | 2.44788 | 0.0001 | 0.002 | 0 |
| varying-md | warm | h5py_h5md | 30 | 1.15396 | 0.0133703 | 87.2171 | 86.0971 | 88.058 | 0.0001 | 0.002 | 0 |
| varying-md | warm | mda_h5md | 30 | 1.18256 | 5.95488 | 0.19967 | 0.198313 | 0.200829 | 0.0001 | 0.002 | 1 |

## Writes

Each repeat times `readcon.write_con`, then the peer writer, on objects already in memory. Cold repeats drop the page cache before the call.

| payload | cache | peer | n_pair_ok | median_readcon_s | median_peer_s | median_ratio_readcon_over_peer | bca_low | bca_high | p_raw | holm_p | readcon_faster |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| repeated-10k | cold | ase_extxyz | 30 | 1.61131 | 8.19749 | 0.196631 | 0.195636 | 0.197244 | 0.0001 | 0.002 | 1 |
| repeated-10k | cold | ase_traj | 30 | 1.58745 | 0.759391 | 2.08371 | 2.07328 | 2.09438 | 0.0001 | 0.002 | 0 |
| repeated-10k | cold | chemfiles_xyz | 30 | 1.58143 | 0.794572 | 1.98694 | 1.98118 | 1.99471 | 0.0001 | 0.002 | 0 |
| repeated-10k | cold | h5py_h5md | 30 | 1.57753 | 0.0242112 | 65.1838 | 63.9177 | 66.2966 | 0.0001 | 0.002 | 0 |
| repeated-10k | cold | mda_h5md | 30 | 1.61721 | 6.90837 | 0.234134 | 0.231735 | 0.23555 | 0.0001 | 0.002 | 1 |
| repeated-10k | warm | ase_extxyz | 30 | 1.57121 | 8.03793 | 0.193924 | 0.192357 | 0.197878 | 0.0001 | 0.002 | 1 |
| repeated-10k | warm | ase_traj | 30 | 1.57449 | 0.757219 | 2.0861 | 2.05408 | 2.09603 | 0.0001 | 0.002 | 0 |
| repeated-10k | warm | chemfiles_xyz | 30 | 1.56769 | 0.794245 | 1.97079 | 1.9585 | 1.98033 | 0.0001 | 0.002 | 0 |
| repeated-10k | warm | h5py_h5md | 30 | 1.56628 | 0.0261829 | 59.8196 | 59.3802 | 60.0034 | 0.0001 | 0.002 | 0 |
| repeated-10k | warm | mda_h5md | 30 | 1.56789 | 6.87032 | 0.228878 | 0.226189 | 0.230528 | 0.0001 | 0.002 | 1 |
| varying-md | cold | ase_extxyz | 30 | 1.6154 | 8.2482 | 0.195569 | 0.193918 | 0.196946 | 0.0001 | 0.002 | 1 |
| varying-md | cold | ase_traj | 30 | 1.59045 | 0.768974 | 2.06204 | 2.04966 | 2.07659 | 0.0001 | 0.002 | 0 |
| varying-md | cold | chemfiles_xyz | 30 | 1.56828 | 0.786628 | 1.99044 | 1.98344 | 1.99746 | 0.0001 | 0.002 | 0 |
| varying-md | cold | h5py_h5md | 30 | 1.56765 | 0.0243411 | 64.427 | 63.5728 | 65.1633 | 0.0001 | 0.002 | 0 |
| varying-md | cold | mda_h5md | 30 | 1.60303 | 6.8282 | 0.235112 | 0.232972 | 0.236083 | 0.0001 | 0.002 | 1 |
| varying-md | warm | ase_extxyz | 30 | 1.55576 | 8.28505 | 0.187636 | 0.186512 | 0.189961 | 0.0001 | 0.002 | 1 |
| varying-md | warm | ase_traj | 30 | 1.56511 | 0.773969 | 2.02147 | 2.00203 | 2.03505 | 0.0001 | 0.002 | 0 |
| varying-md | warm | chemfiles_xyz | 30 | 1.57791 | 0.792601 | 1.97618 | 1.96834 | 1.99272 | 0.0001 | 0.002 | 0 |
| varying-md | warm | h5py_h5md | 30 | 1.56568 | 0.0264909 | 59.0709 | 58.7004 | 59.3244 | 0.0001 | 0.002 | 0 |
| varying-md | warm | mda_h5md | 30 | 1.55467 | 6.9456 | 0.224955 | 0.222916 | 0.227354 | 0.0001 | 0.002 | 1 |

## Stages and Amdahl

Stages are warm-cache wall times on the repeated file. `full` is `read_all_frames_with_threads`. The other rows are isolated passes: string load (`read_to_string`), boundary scan, mmap open, UTF-8 validation, a parallel page touch, a whitespace token walk, the stack float parser, the in-memory frame parse, assembly through `con_frame_from_atom_data_with_positions`, and the library file load.

The published Amdahl bound treats the string load and the boundary scan as a serial fraction of the one-thread full read, `f = (string_load + boundary) / t1`, and `S(8) = 1 / (f + (1-f)/8)`. That string load is a separate copy. The timed full read maps the file and validates UTF-8; it does not call `read_to_string`. Counting the string load inside `f` therefore puts work into the numerator that is not a serial prefix of the timed read, and the bound sits below the measured speedup.

The boundary scan does not scale. The token walk and the numeric parse scale to about 7.5 at 8 threads. Assembly scales through 4 threads and then flattens. The parallel page touch stays under a millisecond and does not speed up. The effective serial fraction implied by the measured 8-thread speedup is `(8/S - 1) / 7`.

| t1_full_s | string_load_s | boundary_s | utf8_s | f_paper | amdahl_8_paper | f_boundary_only | amdahl_8_boundary_only | f_utf8_plus_boundary | amdahl_8_utf8_plus_boundary | measured_speedup_8 | measured_speedup_8_low | measured_speedup_8_high | f_effective | paper_published_speedup_8 | paper_published_amdahl_8 | formula_paper |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0.444892 | 0.0824465 | 0.0332094 | 0.0203381 | 0.259964 | 2.83713 | 0.074646 | 5.25444 | 0.120361 | 4.34187 | 3.52734 | 3.47885 | 3.56248 | 0.181143 | 4.35 | 2.79 | 1/(f+(1-f)/8) with f=(string_load+boundary)/t1_full |

| stage | threads | n_ok | median_s | speedup | speedup_low | speedup_high | efficiency | p_raw | holm_p | tags_identical |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| full | 1 | 90 | 0.444892 | 1 | 1 | 1 | 1 |  |  | yes |
| full | 2 | 30 | 0.298716 | 1.5006 | 1.47373 | 1.52874 | 0.7503 | 0.0001 | 0.0033 | yes |
| full | 4 | 30 | 0.180021 | 2.47248 | 2.44592 | 2.50025 | 0.61812 | 0.0001 | 0.0033 | yes |
| full | 8 | 30 | 0.126425 | 3.52734 | 3.47885 | 3.56248 | 0.440917 | 0.0001 | 0.0033 | yes |
| string_load | 1 | 90 | 0.0824465 | 1 | 1 | 1 | 1 |  |  | yes |
| string_load | 2 | 30 | 0.0883568 | 0.954948 | 0.931664 | 0.990009 | 0.477474 | 0.0075 | 0.0525 | yes |
| string_load | 4 | 30 | 0.0882798 | 0.93987 | 0.926876 | 0.959303 | 0.234968 | 0.0001 | 0.0033 | yes |
| string_load | 8 | 30 | 0.0880341 | 0.93078 | 0.91738 | 0.938086 | 0.116347 | 0.0001 | 0.0033 | yes |
| boundary | 1 | 90 | 0.0332094 | 1 | 1 | 1 | 1 |  |  | yes |
| boundary | 2 | 30 | 0.0333427 | 1.00119 | 0.984595 | 1.01477 | 0.500595 | 0.9151 | 1 | yes |
| boundary | 4 | 30 | 0.033399 | 0.994861 | 0.98601 | 0.999238 | 0.248715 | 0.1074 | 0.537 | yes |
| boundary | 8 | 30 | 0.0332939 | 0.990508 | 0.986142 | 0.995084 | 0.123813 | 0.0025 | 0.02 | yes |
| mmap_open | 1 | 90 | 2.38255e-05 | 1 | 1 | 1 | 1 |  |  | yes |
| mmap_open | 2 | 30 | 2.188e-05 | 1.04876 | 0.900953 | 1.24683 | 0.524382 | 0.5827 | 1 | yes |
| mmap_open | 4 | 30 | 2.1492e-05 | 1.18503 | 0.972758 | 1.25203 | 0.296259 | 0.0531 | 0.3186 | yes |
| mmap_open | 8 | 30 | 2.34165e-05 | 1.05592 | 0.866492 | 1.15904 | 0.131991 | 0.3792 | 1 | yes |
| utf8 | 1 | 90 | 0.0203381 | 1 | 1 | 1 | 1 |  |  | yes |
| utf8 | 2 | 30 | 0.0256477 | 0.825925 | 0.792597 | 0.910848 | 0.412963 | 0.0001 | 0.0033 | yes |
| utf8 | 4 | 30 | 0.025436 | 0.806982 | 0.78699 | 0.823736 | 0.201746 | 0.0001 | 0.0033 | yes |
| utf8 | 8 | 30 | 0.0255761 | 0.763737 | 0.751553 | 0.786197 | 0.0954671 | 0.0001 | 0.0033 | yes |
| page_touch | 1 | 90 | 0.000522012 | 1 | 1 | 1 | 1 |  |  | yes |
| page_touch | 2 | 30 | 0.000925557 | 0.615272 | 0.570651 | 0.635796 | 0.307636 | 0.0001 | 0.0033 | yes |
| page_touch | 4 | 30 | 0.000751815 | 0.708771 | 0.679403 | 0.752447 | 0.177193 | 0.0001 | 0.0033 | yes |
| page_touch | 8 | 30 | 0.000795663 | 0.641957 | 0.544866 | 0.719383 | 0.0802447 | 0.0001 | 0.0033 | yes |
| tokenize | 1 | 90 | 0.167929 | 1 | 1 | 1 | 1 |  |  | yes |
| tokenize | 2 | 30 | 0.0850243 | 1.97494 | 1.94623 | 1.98255 | 0.987468 | 0.0001 | 0.0033 | yes |
| tokenize | 4 | 30 | 0.0428967 | 3.91811 | 3.88378 | 3.94109 | 0.979528 | 0.0001 | 0.0033 | yes |
| tokenize | 8 | 30 | 0.0221791 | 7.5478 | 7.08861 | 7.6732 | 0.943476 | 0.0001 | 0.0033 | yes |
| numeric_parse | 1 | 90 | 0.347737 | 1 | 1 | 1 | 1 |  |  | yes |
| numeric_parse | 2 | 30 | 0.175413 | 1.98236 | 1.97157 | 1.99095 | 0.991182 | 0.0001 | 0.0033 | yes |
| numeric_parse | 4 | 30 | 0.0880377 | 3.94542 | 3.91954 | 3.95949 | 0.986356 | 0.0001 | 0.0033 | yes |
| numeric_parse | 8 | 30 | 0.0457968 | 7.60299 | 7.00767 | 7.6962 | 0.950373 | 0.0001 | 0.0033 | yes |
| in_memory | 1 | 90 | 0.425518 | 1 | 1 | 1 | 1 |  |  | yes |
| in_memory | 2 | 30 | 0.258238 | 1.64729 | 1.63243 | 1.65608 | 0.823646 | 0.0001 | 0.0033 | yes |
| in_memory | 4 | 30 | 0.143473 | 2.96762 | 2.93272 | 3.00646 | 0.741904 | 0.0001 | 0.0033 | yes |
| in_memory | 8 | 30 | 0.0880053 | 4.83261 | 4.71208 | 4.88751 | 0.604076 | 0.0001 | 0.0033 | yes |
| assemble | 1 | 90 | 0.0393585 | 1 | 1 | 1 | 1 |  |  | yes |
| assemble | 2 | 30 | 0.0220057 | 1.79028 | 1.7562 | 1.80469 | 0.895139 | 0.0001 | 0.0033 | yes |
| assemble | 4 | 30 | 0.0142786 | 2.76815 | 2.72509 | 2.78807 | 0.692036 | 0.0001 | 0.0033 | yes |
| assemble | 8 | 30 | 0.0163441 | 2.4253 | 2.38903 | 2.45531 | 0.303162 | 0.0001 | 0.0033 | yes |
| lib_load | 1 | 90 | 0.026239 | 1 | 1 | 1 | 1 |  |  | yes |
| lib_load | 2 | 30 | 0.0262142 | 1.00295 | 0.998057 | 1.00737 | 0.501474 | 0.3866 | 1 | yes |
| lib_load | 4 | 30 | 0.025741 | 1.01699 | 1.00373 | 1.02403 | 0.254247 | 0.0003 | 0.0033 | yes |
| lib_load | 8 | 30 | 0.0257717 | 1.01477 | 1.0088 | 1.0203 | 0.126846 | 0.0006 | 0.0054 | yes |

## readcon-db ingest

readcon-db is current main, which grows the LMDB map when a write would exceed it. `RAYON_NUM_THREADS` is 1. The clock wraps `append_trajectory` and a composition `select`. ASE rows are a commit on every write, and one transaction. A megabyte is 10^6 bytes. Holm adjustment is over this ingest family.

| n_frames | peer | n_pair_ok | median_readcon_s | median_peer_s | median_ratio_readcon_over_peer | bca_low | bca_high | p_raw | holm_p | readcon_frames_per_s | peer_frames_per_s | readcon_MB_per_s | bytes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1000 | ase_commit | 30 | 0.0592388 | 1.68952 | 0.0356106 | 0.0321472 | 0.0395125 | 0.0001 | 0.0004 | 16880.8 | 591.886 | 155.325 | 9201249 |
| 1000 | ase_txn | 30 | 0.0570604 | 0.294729 | 0.191551 | 0.189952 | 0.195264 | 0.0001 | 0.0004 | 17525.3 | 3392.95 | 161.255 | 9201249 |
| 10000 | ase_commit | 30 | 0.563381 | 16.8974 | 0.0337201 | 0.0323836 | 0.034631 | 0.0001 | 0.0004 | 17750 | 591.806 | 163.355 | 92030997 |
| 10000 | ase_txn | 30 | 0.579385 | 2.96498 | 0.193494 | 0.190425 | 0.196277 | 0.0001 | 0.0004 | 17259.7 | 3372.7 | 158.843 | 92030997 |

Map growth uses 80,000 frames whose first coordinate differs by 10^-6 angstrom times the frame index, so the texts do not share one hash.

| n_frames | bytes | seconds | frames_per_s | map_before | map_after | map_grew | default_map_bytes | above_default_cap | data_mdb_bytes | readcon_db_sha |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 80000 | 1340194817 | 6.48098 | 12343.8 | 2147483648 | 3342860288 | yes | 2147483648 | yes | 1671409664 | 55214d138b9c1345e4fba41582a48a936f96312c |

## Masked NEB and converged restart

Pd on a 3x3x3 Al(111) slab, EMT. The reactant is an fcc hollow and the product is an hcp hollow, so the endpoint energies differ and the saddle sits between them. Mask 7 fixes the bottom nine atoms on both bands. Mask 4 holds the palladium height on one band. The shift is the masked barrier minus the free barrier.

| band | h_mask | converged | fmax_eV_A | forward_barrier_eV | reverse_barrier_eV | delta_endpoint_eV | reactant_energy_eV | product_energy_eV | saddle_energy_eV | neb_steps |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| free | 0 | True | 0.01754590774866586 | 0.01985192097675625 | 0.03117955658005034 | -0.01132763560329408 | 6.023829078720369 | 6.012501443117075 | 6.043680999697125 | 31 |
| mask4 | 4 | True | 0.01866386660135932 | 0.01502401294897648 | 0.02150812858357654 | -0.006484115634600052 | 6.041269750969652 | 6.034785635335052 | 6.056293763918629 | 26 |
| shift_mask_minus_free |  | True |  | -0.00482790802777977 | -0.009671427996473803 | 0.004843519968694032 |  |  |  |  |

The restart writes the converged free band with the canonical writer, reads it, and continues FIRE at the same force threshold.

| host | kernel | os | cpu_model | cpu_family | cpu_model_num | cpu_stepping | cpu_mhz | nproc | mem_total | date_utc | python | rustc | gpp | gfortran | julia | readcon | readcon_core_sha | readcon_db | readcon_db_sha | readcon_db_subject | ase | numpy | scipy | h5py | chemfiles | mdanalysis | repeats | bootstrap | seed | alpha | cache_cold | band | n_images | nsteps | converged | read_positions_bit_identical | continuation_positions_bit_identical | continuation_energy_bit_identical | max_abs_read_delta_A | max_abs_continue_delta_A | max_abs_energy_delta_eV | energy_bits_equal_to_prerestart |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| cursor | 6.12.94+ | Ubuntu 24.04.5 LTS | Intel(R) Xeon(R) Processor | 6 | 207 | 2 | 2400.000 | 8 | 49342904 kB | 2026-10-14T15:49:28Z | 3.12.3 | rustc 1.88.0 (6b00bc388 2025-06-23) | g++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0 | GNU Fortran (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0 | julia version 1.10.10 | 0.17.0 | b93a54eb8b9a6211b14ca07a484c6891477c98bc | 0.1.8 | 55214d138b9c1345e4fba41582a48a936f96312c | Merge pull request #21 from lode-org/fix/lmdb-map-size | 3.29.0 | 2.5.4 | 1.18.1 | 3.16.0 | 0.10.4 | 2.10.0 | 30 | 9999 | 20261011 | 0.05 | sync + drop_caches 3 + posix_fadvise DONTNEED | free | 7 | 0 | yes | yes | yes | no | 0.0 | 0.0 | 8.881784197001252e-15 | no |

## Conformance

Julia and Fortran logs are `clean_conformance_julia.log` and `clean_conformance_fortran.log` in this directory. Each conformance file is one CASE line.

## Every recorded number

The tables above are the medians, intervals, and checks. Small raw files are inlined below. The larger per-repeat tables stay in this directory: `clean_reads.csv`, `clean_writes.csv`, `clean_db_ingest.csv`, and `clean_stages.csv.gz`.

### clean_environment.csv

```
host,kernel,os,cpu_model,cpu_family,cpu_model_num,cpu_stepping,cpu_mhz,nproc,mem_total,date_utc,python,rustc,gpp,gfortran,julia,readcon,readcon_core_sha,readcon_db,readcon_db_sha,readcon_db_subject,ase,numpy,scipy,h5py,chemfiles,mdanalysis,repeats,bootstrap,seed,alpha,cache_cold
cursor,6.12.94+,Ubuntu 24.04.5 LTS,Intel(R) Xeon(R) Processor,6,207,2,2400.000,8,49342904 kB,2026-10-14T13:40:03Z,3.12.3,rustc 1.88.0 (6b00bc388 2025-06-23),g++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0,GNU Fortran (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0,julia version 1.10.10,0.17.0,b93a54eb8b9a6211b14ca07a484c6891477c98bc,0.1.8,55214d138b9c1345e4fba41582a48a936f96312c,Merge pull request #21 from lode-org/fix/lmdb-map-size,3.29.0,2.5.4,1.18.1,3.16.0,0.10.4,2.10.0,30,9999,20261011,0.05,sync + drop_caches 3 + posix_fadvise DONTNEED
```


### clean_trajectory.csv

```
payload,n_frames,n_atoms,n_free,md_seconds,integrator,timestep_fs,temperature_K,seed,potential,initial_energy_eV,max_abs_step_A,n_distinct_free_frames,fixed_atom_max_abs_drift_A,rmsd_first_last_A,repeated-10k_con_bytes,repeated-10k_xyz_bytes,repeated-10k_h5_bytes,repeated-10k_extxyz_bytes,repeated-10k_traj_bytes,varying-md_con_bytes,varying-md_xyz_bytes,varying-md_h5_bytes,varying-md_extxyz_bytes,varying-md_traj_bytes
varying-md,10000,218,2,124.776,VelocityVerlet,1,300,20261014,ASE EMT,50.85838443750094,0.04905068816820801,10000,0,12.03848069719289,167710000,70330000,52897172,182330000,54370434,92030997,70561913,52897172,182330000,101006447
```


### clean_reads_summary.csv

```
family,payload,cache,peer,n_pair_ok,n_timeout,n_failure,n_baseline_not_ok,median_readcon_s,median_peer_s,median_ratio_readcon_over_peer,bca_low,bca_high,p_raw,holm_p,readcon_faster
read,repeated-10k,cold,ase_extxyz,30,0,0,0,1.18834,4.34239,0.272837,0.270653,0.274181,0.0001,0.002,1
read,repeated-10k,cold,ase_traj,30,0,0,0,1.19637,0.859613,1.40472,1.38512,1.41467,0.0001,0.002,0
read,repeated-10k,cold,chemfiles_xyz,30,0,0,0,1.20366,0.486681,2.478,2.46599,2.48718,0.0001,0.002,0
read,repeated-10k,cold,h5py_h5md,30,0,0,0,1.19737,0.0344504,34.9014,33.5436,35.7919,0.0001,0.002,0
read,repeated-10k,cold,mda_h5md,30,0,0,0,1.20528,5.85778,0.204921,0.20324,0.207436,0.0001,0.002,1
read,repeated-10k,warm,ase_extxyz,30,0,0,0,1.10833,4.27257,0.259202,0.258314,0.259596,0.0001,0.002,1
read,repeated-10k,warm,ase_traj,30,0,0,0,1.09517,0.835136,1.31474,1.30905,1.33758,0.0001,0.002,0
read,repeated-10k,warm,chemfiles_xyz,30,0,0,0,1.08808,0.476651,2.28858,2.27947,2.29349,0.0001,0.002,0
read,repeated-10k,warm,h5py_h5md,30,0,0,0,1.07792,0.0146068,74.3144,73.5683,74.8774,0.0001,0.002,0
read,repeated-10k,warm,mda_h5md,30,0,0,0,1.10137,5.92159,0.18649,0.185,0.186823,0.0001,0.002,1
read,varying-md,cold,ase_extxyz,30,0,0,0,1.22197,4.32789,0.28186,0.279921,0.282661,0.0001,0.002,1
read,varying-md,cold,ase_traj,30,0,0,0,1.22166,1.27733,0.960198,0.95214,0.964039,0.0001,0.002,1
read,varying-md,cold,chemfiles_xyz,30,0,0,0,1.21807,0.489812,2.49168,2.47411,2.50693,0.0001,0.002,0
read,varying-md,cold,h5py_h5md,30,0,0,0,1.24282,0.0337123,37.1961,35.5481,37.7179,0.0001,0.002,0
read,varying-md,cold,mda_h5md,30,0,0,0,1.23006,5.93265,0.207952,0.204458,0.209837,0.0001,0.002,1
read,varying-md,warm,ase_extxyz,30,0,0,0,1.19614,4.25303,0.281127,0.280583,0.281468,0.0001,0.002,1
read,varying-md,warm,ase_traj,30,0,0,0,1.17242,1.24612,0.940119,0.935984,0.948151,0.0001,0.002,1
read,varying-md,warm,chemfiles_xyz,30,0,0,0,1.15483,0.473194,2.4446,2.43676,2.44788,0.0001,0.002,0
read,varying-md,warm,h5py_h5md,30,0,0,0,1.15396,0.0133703,87.2171,86.0971,88.058,0.0001,0.002,0
read,varying-md,warm,mda_h5md,30,0,0,0,1.18256,5.95488,0.19967,0.198313,0.200829,0.0001,0.002,1
```


### clean_writes_summary.csv

```
family,payload,cache,peer,n_pair_ok,n_timeout,n_failure,n_baseline_not_ok,median_readcon_s,median_peer_s,median_ratio_readcon_over_peer,bca_low,bca_high,p_raw,holm_p,readcon_faster
write,repeated-10k,cold,ase_extxyz,30,0,0,0,1.61131,8.19749,0.196631,0.195636,0.197244,0.0001,0.002,1
write,repeated-10k,cold,ase_traj,30,0,0,0,1.58745,0.759391,2.08371,2.07328,2.09438,0.0001,0.002,0
write,repeated-10k,cold,chemfiles_xyz,30,0,0,0,1.58143,0.794572,1.98694,1.98118,1.99471,0.0001,0.002,0
write,repeated-10k,cold,h5py_h5md,30,0,0,0,1.57753,0.0242112,65.1838,63.9177,66.2966,0.0001,0.002,0
write,repeated-10k,cold,mda_h5md,30,0,0,0,1.61721,6.90837,0.234134,0.231735,0.23555,0.0001,0.002,1
write,repeated-10k,warm,ase_extxyz,30,0,0,0,1.57121,8.03793,0.193924,0.192357,0.197878,0.0001,0.002,1
write,repeated-10k,warm,ase_traj,30,0,0,0,1.57449,0.757219,2.0861,2.05408,2.09603,0.0001,0.002,0
write,repeated-10k,warm,chemfiles_xyz,30,0,0,0,1.56769,0.794245,1.97079,1.9585,1.98033,0.0001,0.002,0
write,repeated-10k,warm,h5py_h5md,30,0,0,0,1.56628,0.0261829,59.8196,59.3802,60.0034,0.0001,0.002,0
write,repeated-10k,warm,mda_h5md,30,0,0,0,1.56789,6.87032,0.228878,0.226189,0.230528,0.0001,0.002,1
write,varying-md,cold,ase_extxyz,30,0,0,0,1.6154,8.2482,0.195569,0.193918,0.196946,0.0001,0.002,1
write,varying-md,cold,ase_traj,30,0,0,0,1.59045,0.768974,2.06204,2.04966,2.07659,0.0001,0.002,0
write,varying-md,cold,chemfiles_xyz,30,0,0,0,1.56828,0.786628,1.99044,1.98344,1.99746,0.0001,0.002,0
write,varying-md,cold,h5py_h5md,30,0,0,0,1.56765,0.0243411,64.427,63.5728,65.1633,0.0001,0.002,0
write,varying-md,cold,mda_h5md,30,0,0,0,1.60303,6.8282,0.235112,0.232972,0.236083,0.0001,0.002,1
write,varying-md,warm,ase_extxyz,30,0,0,0,1.55576,8.28505,0.187636,0.186512,0.189961,0.0001,0.002,1
write,varying-md,warm,ase_traj,30,0,0,0,1.56511,0.773969,2.02147,2.00203,2.03505,0.0001,0.002,0
write,varying-md,warm,chemfiles_xyz,30,0,0,0,1.57791,0.792601,1.97618,1.96834,1.99272,0.0001,0.002,0
write,varying-md,warm,h5py_h5md,30,0,0,0,1.56568,0.0264909,59.0709,58.7004,59.3244,0.0001,0.002,0
write,varying-md,warm,mda_h5md,30,0,0,0,1.55467,6.9456,0.224955,0.222916,0.227354,0.0001,0.002,1
```


### clean_stages_summary.csv

```
payload,stage,threads,n_ok,median_s,speedup,speedup_low,speedup_high,efficiency,p_raw,holm_p,tags_identical,n_distinct_tags
repeated-10k,full,1,90,0.444892,1,1,1,1,,,yes,1
repeated-10k,full,2,30,0.298716,1.5006,1.47373,1.52874,0.7503,0.0001,0.0033,yes,1
repeated-10k,full,4,30,0.180021,2.47248,2.44592,2.50025,0.61812,0.0001,0.0033,yes,1
repeated-10k,full,8,30,0.126425,3.52734,3.47885,3.56248,0.440917,0.0001,0.0033,yes,1
repeated-10k,string_load,1,90,0.0824465,1,1,1,1,,,yes,1
repeated-10k,string_load,2,30,0.0883568,0.954948,0.931664,0.990009,0.477474,0.0075,0.0525,yes,1
repeated-10k,string_load,4,30,0.0882798,0.93987,0.926876,0.959303,0.234968,0.0001,0.0033,yes,1
repeated-10k,string_load,8,30,0.0880341,0.93078,0.91738,0.938086,0.116347,0.0001,0.0033,yes,1
repeated-10k,boundary,1,90,0.0332094,1,1,1,1,,,yes,1
repeated-10k,boundary,2,30,0.0333427,1.00119,0.984595,1.01477,0.500595,0.9151,1,yes,1
repeated-10k,boundary,4,30,0.033399,0.994861,0.98601,0.999238,0.248715,0.1074,0.537,yes,1
repeated-10k,boundary,8,30,0.0332939,0.990508,0.986142,0.995084,0.123813,0.0025,0.02,yes,1
repeated-10k,mmap_open,1,90,2.38255e-05,1,1,1,1,,,yes,1
repeated-10k,mmap_open,2,30,2.188e-05,1.04876,0.900953,1.24683,0.524382,0.5827,1,yes,1
repeated-10k,mmap_open,4,30,2.1492e-05,1.18503,0.972758,1.25203,0.296259,0.0531,0.3186,yes,1
repeated-10k,mmap_open,8,30,2.34165e-05,1.05592,0.866492,1.15904,0.131991,0.3792,1,yes,1
repeated-10k,utf8,1,90,0.0203381,1,1,1,1,,,yes,1
repeated-10k,utf8,2,30,0.0256477,0.825925,0.792597,0.910848,0.412963,0.0001,0.0033,yes,1
repeated-10k,utf8,4,30,0.025436,0.806982,0.78699,0.823736,0.201746,0.0001,0.0033,yes,1
repeated-10k,utf8,8,30,0.0255761,0.763737,0.751553,0.786197,0.0954671,0.0001,0.0033,yes,1
repeated-10k,page_touch,1,90,0.000522012,1,1,1,1,,,yes,1
repeated-10k,page_touch,2,30,0.000925557,0.615272,0.570651,0.635796,0.307636,0.0001,0.0033,yes,1
repeated-10k,page_touch,4,30,0.000751815,0.708771,0.679403,0.752447,0.177193,0.0001,0.0033,yes,1
repeated-10k,page_touch,8,30,0.000795663,0.641957,0.544866,0.719383,0.0802447,0.0001,0.0033,yes,1
repeated-10k,tokenize,1,90,0.167929,1,1,1,1,,,yes,1
repeated-10k,tokenize,2,30,0.0850243,1.97494,1.94623,1.98255,0.987468,0.0001,0.0033,yes,1
repeated-10k,tokenize,4,30,0.0428967,3.91811,3.88378,3.94109,0.979528,0.0001,0.0033,yes,1
repeated-10k,tokenize,8,30,0.0221791,7.5478,7.08861,7.6732,0.943476,0.0001,0.0033,yes,1
repeated-10k,numeric_parse,1,90,0.347737,1,1,1,1,,,yes,1
repeated-10k,numeric_parse,2,30,0.175413,1.98236,1.97157,1.99095,0.991182,0.0001,0.0033,yes,1
repeated-10k,numeric_parse,4,30,0.0880377,3.94542,3.91954,3.95949,0.986356,0.0001,0.0033,yes,1
repeated-10k,numeric_parse,8,30,0.0457968,7.60299,7.00767,7.6962,0.950373,0.0001,0.0033,yes,1
repeated-10k,in_memory,1,90,0.425518,1,1,1,1,,,yes,1
repeated-10k,in_memory,2,30,0.258238,1.64729,1.63243,1.65608,0.823646,0.0001,0.0033,yes,1
repeated-10k,in_memory,4,30,0.143473,2.96762,2.93272,3.00646,0.741904,0.0001,0.0033,yes,1
repeated-10k,in_memory,8,30,0.0880053,4.83261,4.71208,4.88751,0.604076,0.0001,0.0033,yes,1
repeated-10k,assemble,1,90,0.0393585,1,1,1,1,,,yes,1
repeated-10k,assemble,2,30,0.0220057,1.79028,1.7562,1.80469,0.895139,0.0001,0.0033,yes,1
repeated-10k,assemble,4,30,0.0142786,2.76815,2.72509,2.78807,0.692036,0.0001,0.0033,yes,1
repeated-10k,assemble,8,30,0.0163441,2.4253,2.38903,2.45531,0.303162,0.0001,0.0033,yes,1
repeated-10k,lib_load,1,90,0.026239,1,1,1,1,,,yes,1
repeated-10k,lib_load,2,30,0.0262142,1.00295,0.998057,1.00737,0.501474,0.3866,1,yes,1
repeated-10k,lib_load,4,30,0.025741,1.01699,1.00373,1.02403,0.254247,0.0003,0.0033,yes,1
repeated-10k,lib_load,8,30,0.0257717,1.01477,1.0088,1.0203,0.126846,0.0006,0.0054,yes,1
```


### clean_amdahl.csv

```
t1_full_s,string_load_s,boundary_s,utf8_s,f_paper,amdahl_8_paper,f_boundary_only,amdahl_8_boundary_only,f_utf8_plus_boundary,amdahl_8_utf8_plus_boundary,measured_speedup_8,measured_speedup_8_low,measured_speedup_8_high,f_effective,paper_published_speedup_8,paper_published_amdahl_8,formula_paper
0.444892,0.0824465,0.0332094,0.0203381,0.259964,2.83713,0.074646,5.25444,0.120361,4.34187,3.52734,3.47885,3.56248,0.181143,4.35,2.79,1/(f+(1-f)/8) with f=(string_load+boundary)/t1_full
```


### clean_db_summary.csv

```
n_frames,peer,n_pair_ok,median_readcon_s,median_peer_s,median_ratio_readcon_over_peer,bca_low,bca_high,p_raw,holm_p,readcon_frames_per_s,peer_frames_per_s,readcon_MB_per_s,bytes
1000,ase_commit,30,0.0592388,1.68952,0.0356106,0.0321472,0.0395125,0.0001,0.0004,16880.8,591.886,155.325,9201249
1000,ase_txn,30,0.0570604,0.294729,0.191551,0.189952,0.195264,0.0001,0.0004,17525.3,3392.95,161.255,9201249
10000,ase_commit,30,0.563381,16.8974,0.0337201,0.0323836,0.034631,0.0001,0.0004,17750,591.806,163.355,92030997
10000,ase_txn,30,0.579385,2.96498,0.193494,0.190425,0.196277,0.0001,0.0004,17259.7,3372.7,158.843,92030997
```


### clean_db_map.csv

```
n_frames,bytes,seconds,frames_per_s,map_before,map_after,map_grew,default_map_bytes,above_default_cap,data_mdb_bytes,readcon_db_sha
80000,1340194817,6.48098,12343.8,2147483648,3342860288,yes,2147483648,yes,1671409664,55214d138b9c1345e4fba41582a48a936f96312c
```


### clean_neb.csv

```
host,kernel,os,cpu_model,cpu_family,cpu_model_num,cpu_stepping,cpu_mhz,nproc,mem_total,date_utc,python,rustc,gpp,gfortran,julia,readcon,readcon_core_sha,readcon_db,readcon_db_sha,readcon_db_subject,ase,numpy,scipy,h5py,chemfiles,mdanalysis,repeats,bootstrap,seed,alpha,cache_cold,band,h_mask,bottom_mask,n_images_movable,k_spring,fmax_target_eV_A,converged,neb_steps,fmax_eV_A,forward_barrier_eV,reverse_barrier_eV,delta_endpoint_eV,reactant_energy_eV,product_energy_eV,saddle_energy_eV,reactant_converged,product_converged,energies_json
cursor,6.12.94+,Ubuntu 24.04.5 LTS,Intel(R) Xeon(R) Processor,6,207,2,2400.000,8,49342904 kB,2026-10-14T15:49:28Z,3.12.3,rustc 1.88.0 (6b00bc388 2025-06-23),g++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0,GNU Fortran (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0,julia version 1.10.10,0.17.0,b93a54eb8b9a6211b14ca07a484c6891477c98bc,0.1.8,55214d138b9c1345e4fba41582a48a936f96312c,Merge pull request #21 from lode-org/fix/lmdb-map-size,3.29.0,2.5.4,1.18.1,3.16.0,0.10.4,2.10.0,30,9999,20261011,0.05,sync + drop_caches 3 + posix_fadvise DONTNEED,free,0,7,5,0.1,0.02,True,31,0.01754590774866586,0.01985192097675625,0.03117955658005034,-0.01132763560329408,6.023829078720369,6.012501443117075,6.043680999697125,True,True,"[6.023829078720369, 6.026891466798836, 6.033547117518528, 6.043680999697125, 6.031713165148853, 6.018348974222274, 6.012501443117075]"
cursor,6.12.94+,Ubuntu 24.04.5 LTS,Intel(R) Xeon(R) Processor,6,207,2,2400.000,8,49342904 kB,2026-10-14T15:49:28Z,3.12.3,rustc 1.88.0 (6b00bc388 2025-06-23),g++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0,GNU Fortran (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0,julia version 1.10.10,0.17.0,b93a54eb8b9a6211b14ca07a484c6891477c98bc,0.1.8,55214d138b9c1345e4fba41582a48a936f96312c,Merge pull request #21 from lode-org/fix/lmdb-map-size,3.29.0,2.5.4,1.18.1,3.16.0,0.10.4,2.10.0,30,9999,20261011,0.05,sync + drop_caches 3 + posix_fadvise DONTNEED,mask4,4,7,5,0.1,0.02,True,26,0.01866386660135932,0.01502401294897648,0.02150812858357654,-0.006484115634600052,6.041269750969652,6.034785635335052,6.056293763918629,True,True,"[6.0412697509696525, 6.044273809491354, 6.048104091699589, 6.056293763918629, 6.043811491246895, 6.037978835936018, 6.034785635335052]"
cursor,6.12.94+,Ubuntu 24.04.5 LTS,Intel(R) Xeon(R) Processor,6,207,2,2400.000,8,49342904 kB,2026-10-14T15:49:28Z,3.12.3,rustc 1.88.0 (6b00bc388 2025-06-23),g++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0,GNU Fortran (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0,julia version 1.10.10,0.17.0,b93a54eb8b9a6211b14ca07a484c6891477c98bc,0.1.8,55214d138b9c1345e4fba41582a48a936f96312c,Merge pull request #21 from lode-org/fix/lmdb-map-size,3.29.0,2.5.4,1.18.1,3.16.0,0.10.4,2.10.0,30,9999,20261011,0.05,sync + drop_caches 3 + posix_fadvise DONTNEED,shift_mask_minus_free,,7,5,0.1,0.02,True,,,-0.00482790802777977,-0.009671427996473803,0.004843519968694032,,,,,,
```


### clean_neb_restart.csv

```
host,kernel,os,cpu_model,cpu_family,cpu_model_num,cpu_stepping,cpu_mhz,nproc,mem_total,date_utc,python,rustc,gpp,gfortran,julia,readcon,readcon_core_sha,readcon_db,readcon_db_sha,readcon_db_subject,ase,numpy,scipy,h5py,chemfiles,mdanalysis,repeats,bootstrap,seed,alpha,cache_cold,band,n_images,nsteps,converged,read_positions_bit_identical,continuation_positions_bit_identical,continuation_energy_bit_identical,max_abs_read_delta_A,max_abs_continue_delta_A,max_abs_energy_delta_eV,energy_bits_equal_to_prerestart
cursor,6.12.94+,Ubuntu 24.04.5 LTS,Intel(R) Xeon(R) Processor,6,207,2,2400.000,8,49342904 kB,2026-10-14T15:49:28Z,3.12.3,rustc 1.88.0 (6b00bc388 2025-06-23),g++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0,GNU Fortran (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0,julia version 1.10.10,0.17.0,b93a54eb8b9a6211b14ca07a484c6891477c98bc,0.1.8,55214d138b9c1345e4fba41582a48a936f96312c,Merge pull request #21 from lode-org/fix/lmdb-map-size,3.29.0,2.5.4,1.18.1,3.16.0,0.10.4,2.10.0,30,9999,20261011,0.05,sync + drop_caches 3 + posix_fadvise DONTNEED,free,7,0,yes,yes,yes,no,0.0,0.0,8.881784197001252e-15,no
```


### clean_reads.csv

Not inlined (727900 bytes, CSV). The rows are in `clean_reads.csv`.


### clean_writes.csv

Not inlined (734380 bytes, CSV). The rows are in `clean_writes.csv`.


### clean_stages.csv.gz

Not inlined (24605 bytes, gzip-compressed CSV). The rows are in `clean_stages.csv.gz`.


### clean_db_ingest.csv

Not inlined (149049 bytes, CSV). The rows are in `clean_db_ingest.csv`.


### clean_conformance_fortran.log

```
PASS v2-minimal valid/v2_minimal.con
PASS v3-units valid/v3_units.con
PASS column-4-spec2-x-only valid/column4_spec2_x_only.con
PASS column-4-spec1-all-fixed valid/column4_spec1_all_fixed.con
PASS column-4-spec2-all-fixed valid/column4_spec2_all_fixed.con
PASS column-4-spec2-y-only valid/column4_spec2_y_only.con
PASS column-4-spec2-xz valid/column4_spec2_xz.con
PASS zero-atom valid/zero_atom.con
PASS zero-atom-eof valid/zero_atom_eof.con
PASS zero-atom-then-frame valid/zero_atom_then_frame.con
PASS missing-spec-version invalid/missing_spec_version.con
PASS v3-missing-units invalid/v3_missing_units.con
PASS v3-bad-units invalid/v3_bad_units.con
PASS column-4-out-of-range invalid/column4_out_of_range.con
PASS unsupported-spec-version invalid/unsupported_spec_version.con
PASS unknown-section invalid/unknown_section.con
PASS validate-true-missing-sections invalid/validate_true_missing_sections.con
PASS per-type-zero invalid/per_type_zero.con
 OK fortran conformance goldens  valid=          10  invalid=           8
```


### clean_conformance_julia.log

```
CASE	valid	v2-minimal	valid/v2_minimal.con
PASS	v2-minimal
CASE	valid	v3-units	valid/v3_units.con
PASS	v3-units
CASE	valid	column-4-spec2-x-only	valid/column4_spec2_x_only.con
PASS	column-4-spec2-x-only
CASE	valid	column-4-spec1-all-fixed	valid/column4_spec1_all_fixed.con
PASS	column-4-spec1-all-fixed
CASE	valid	column-4-spec2-all-fixed	valid/column4_spec2_all_fixed.con
PASS	column-4-spec2-all-fixed
CASE	valid	column-4-spec2-y-only	valid/column4_spec2_y_only.con
PASS	column-4-spec2-y-only
CASE	valid	column-4-spec2-xz	valid/column4_spec2_xz.con
PASS	column-4-spec2-xz
CASE	valid	zero-atom	valid/zero_atom.con
PASS	zero-atom
CASE	valid	zero-atom-eof	valid/zero_atom_eof.con
PASS	zero-atom-eof
CASE	valid	zero-atom-then-frame	valid/zero_atom_then_frame.con
PASS	zero-atom-then-frame
CASE	invalid	missing-spec-version	invalid/missing_spec_version.con
PASS	missing-spec-version
CASE	invalid	v3-missing-units	invalid/v3_missing_units.con
PASS	v3-missing-units
CASE	invalid	v3-bad-units	invalid/v3_bad_units.con
PASS	v3-bad-units
CASE	invalid	column-4-out-of-range	invalid/column4_out_of_range.con
PASS	column-4-out-of-range
CASE	invalid	unsupported-spec-version	invalid/unsupported_spec_version.con
PASS	unsupported-spec-version
CASE	invalid	unknown-section	invalid/unknown_section.con
PASS	unknown-section
CASE	invalid	validate-true-missing-sections	invalid/validate_true_missing_sections.con
PASS	validate-true-missing-sections
CASE	invalid	per-type-zero	invalid/per_type_zero.con
PASS	per-type-zero
Test Summary:       | Pass  Total  Time
conformance goldens |  136    136  1.1s
```

