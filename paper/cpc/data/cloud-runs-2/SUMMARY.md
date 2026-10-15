# Cloud runs 2

Measurements for the two campaigns. Manuscript prose was not edited. Published `data/failure` and `src/figures/generated` were not overwritten. Tables and the restart figure below were written only under this directory.

## Hardware

Recorded on the host before the MPI series (`04/host.txt`).

- Architecture: x86_64, KVM guest, Intel Xeon model 207 (family 6, model 207, stepping 2)
- CPUs: 8, 1 thread per core, 1 socket, 8 cores per socket. `nproc` = 8
- Caches: L1d 384 KiB, L1i 256 KiB, L2 16 MiB, L3 320 MiB
- `MemTotal`: 49342904 kB (about 47 GB). No swap. `free -g` at the start of the MPI script reported 47 total, 27 used, 19 free, 19 available. Usable memory during the runs was the available figure, not the used figure.
- Kernel: Linux 6.12.94+ SMP PREEMPT_DYNAMIC, x86_64 (`uname -a` in `04/host.txt`)
- Root filesystem: `/dev/vdc` ext4, virtio, rotational flag 1, 256G. Not NVMe.
- The requested host was at least 16 physical cores, 64 GB, and local NVMe. This machine has 8 cores and virtio ext4, so ranks stop at 8. Ranks 16 and 32 were not run.

## Software

- Paper checkout: branch `paper/cpc-v4a` at `d9aed13b7a284f1adeabb2bac9d1518bb43c7721`
- readcon-core: `origin/main` `af8aabb60f0c5db970085712dd3f6d476957919f`, package 0.17.0, rust-version 1.88. MPI examples built `--release --features mpi` in `/tmp/readcon-core-main`.
- readcon-db: `main` `55214d138b9c1345e4fba41582a48a936f96312c`, package 0.1.8, rust-version 1.88. `mpi_ingest_check` built `--release --features mpi`.
- rustc: 1.99.0 (b940084d7 2026-09-28)
- MPICH 4.2.3, device ch4:ofi, prefix `/opt/mpich-4.2.3`, configure `--prefix=/opt/mpich-4.2.3 --with-device=ch4:ofi --enable-fortran --enable-romio`, ABI 16:3:4, release date Wed Oct 2 2024. Hydra launch: `mpiexec -bind-to core`.
- Environment on every MPI process: `UCX_TLS=tcp`, `FI_PROVIDER=tcp`, `RAYON_NUM_THREADS=1`, `OMP_NUM_THREADS=1`. One thread per rank.
- GCC / gfortran: Ubuntu 13.3.0-6ubuntu2~24.04.1
- Julia: 1.11.6 at `/opt/julia/bin/julia`
- Python bench environment `/tmp/benchenv`: ase 3.29.0, chemfiles 0.10.4, MDAnalysis 2.10.0, h5py 3.16.0, numpy 2.5.4, matplotlib 3.11.2, readcon 0.17.0 (`CON_SPEC_VERSION` 3)
- Non-Python `libreadcon_core.so` used by C, C++, Fortran, and Julia: `/workspace/target/release/libreadcon_core.so` from `cargo build --release` on the paper checkout (no `python` feature).

## Campaign 04: MPI strong and weak scaling

Each point is 5 repeats. Cold repeats run `sync` and `echo 3 > /proc/sys/vm/drop_caches` first. Warm repeats follow one untimed warmup and do not drop the cache. The recorded time is the harness timer only: `distributed_ms` for reads, `write_ms` for writes, `mpi_s` for ingest. The serial reference that the same process runs afterwards is not included in the seconds below. `sha_match` is the harness `identical` or `match` flag. All 480 repeats matched.

### Files

The core file is not a 218-atom trajectory. `resources/test/tiny_multi_cuh2.con` is 678 bytes and 2 frames. The strong file is 1,583,691 copies of that file: 3,167,382 frames and 1,073,742,498 bytes. The weak core file is 200,000 copies per rank: 400,000 frames and 135,600,000 bytes per rank, so the r=1,2,4,8 files are 135,600,000, 271,200,000, 542,400,000, and 1,084,800,000 bytes.

The database strong file was written by `readcon-db/bench/gen_con.py` with 30,965 frames of 1,000 atoms. Its size is 1,074,071,389 bytes. Each ingest passes that path four times, so `bytes_total` is 4,296,284,756. The weak database file has 7,700 frames of 1,000 atoms per rank. Sizes: r1 254,687,189 bytes, r2 509,374,389, r4 1,018,748,789, r8 2,136,707,894. Four copies, so `bytes_total` is four times the file size. Batch size 4096, 4 shards, first trajectory id 1.

`frames_per_rank` is the harness frame count divided by the rank count. For database ingests the harness frame count sums the four copies, so the strong rows show 123,860, 61,930, 30,965, and 15,482.5 (that is 30,965 times 4, divided by the rank count) and every weak database row shows 30,800 (7,700 times 4).

### Medians

Median is the third of the five sorted repeats. `sha_match` is true for every row.

#### strong

| system | operation | mode | ranks | frames_per_rank | bytes_total | median_s | min_s | max_s | cache | sha_match |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| readcon-core | read | shared | 1 | 3.16738e+06 | 1073742498 | 9.9043 | 9.4382 | 11.8569 | cold | true |
| readcon-core | read | shared | 1 | 3.16738e+06 | 1073742498 | 9.0881 | 8.9995 | 9.3241 | warm | true |
| readcon-core | read | shared | 2 | 1.58369e+06 | 1073742498 | 5.6773 | 5.2817 | 5.8292 | cold | true |
| readcon-core | read | shared | 2 | 1.58369e+06 | 1073742498 | 4.6509 | 4.6161 | 4.7502 | warm | true |
| readcon-core | read | shared | 4 | 791846 | 1073742498 | 3.2205 | 3.1049 | 3.3673 | cold | true |
| readcon-core | read | shared | 4 | 791846 | 1073742498 | 2.5913 | 2.4875 | 3.1034 | warm | true |
| readcon-core | read | shared | 8 | 395923 | 1073742498 | 2.1128 | 2.0149 | 2.3412 | cold | true |
| readcon-core | read | shared | 8 | 395923 | 1073742498 | 1.5041 | 1.4163 | 1.5698 | warm | true |
| readcon-core | read | scatter | 1 | 3.16738e+06 | 1073742498 | 9.9486 | 9.7042 | 10.123 | cold | true |
| readcon-core | read | scatter | 1 | 3.16738e+06 | 1073742498 | 9.2225 | 9.1167 | 9.8292 | warm | true |
| readcon-core | read | scatter | 2 | 1.58369e+06 | 1073742498 | 5.594 | 5.4728 | 5.6935 | cold | true |
| readcon-core | read | scatter | 2 | 1.58369e+06 | 1073742498 | 5.013 | 4.9386 | 5.2123 | warm | true |
| readcon-core | read | scatter | 4 | 791846 | 1073742498 | 3.5173 | 3.4828 | 3.616 | cold | true |
| readcon-core | read | scatter | 4 | 791846 | 1073742498 | 2.9226 | 2.8712 | 2.9806 | warm | true |
| readcon-core | read | scatter | 8 | 395923 | 1073742498 | 2.4379 | 2.355 | 2.4985 | cold | true |
| readcon-core | read | scatter | 8 | 395923 | 1073742498 | 1.8358 | 1.8105 | 1.875 | warm | true |
| readcon-core | write | mpiio | 1 | 3.16738e+06 | 1073742498 | 8.7212 | 8.24 | 8.9754 | cold | true |
| readcon-core | write | mpiio | 1 | 3.16738e+06 | 1073742498 | 8.3693 | 8.2377 | 8.5168 | warm | true |
| readcon-core | write | mpiio | 2 | 1.58369e+06 | 1073742498 | 4.2877 | 4.217 | 4.3849 | cold | true |
| readcon-core | write | mpiio | 2 | 1.58369e+06 | 1073742498 | 4.0601 | 4.0432 | 4.0832 | warm | true |
| readcon-core | write | mpiio | 4 | 791846 | 1073742498 | 2.3035 | 2.2694 | 2.3497 | cold | true |
| readcon-core | write | mpiio | 4 | 791846 | 1073742498 | 2.3047 | 2.2595 | 2.3782 | warm | true |
| readcon-core | write | mpiio | 8 | 395923 | 1073742498 | 1.4771 | 1.3826 | 2.7646 | cold | true |
| readcon-core | write | mpiio | 8 | 395923 | 1073742498 | 1.4161 | 1.3657 | 1.4908 | warm | true |
| readcon-core | write | gather | 1 | 3.16738e+06 | 1073742498 | 9.2329 | 8.9174 | 9.6061 | cold | true |
| readcon-core | write | gather | 1 | 3.16738e+06 | 1073742498 | 9.4898 | 9.4047 | 10.879 | warm | true |
| readcon-core | write | gather | 2 | 1.58369e+06 | 1073742498 | 5.4422 | 5.2105 | 5.6129 | cold | true |
| readcon-core | write | gather | 2 | 1.58369e+06 | 1073742498 | 5.0521 | 5.0393 | 5.8331 | warm | true |
| readcon-core | write | gather | 4 | 791846 | 1073742498 | 3.0506 | 3.0305 | 3.399 | cold | true |
| readcon-core | write | gather | 4 | 791846 | 1073742498 | 3.075 | 3.0232 | 3.0977 | warm | true |
| readcon-core | write | gather | 8 | 395923 | 1073742498 | 2.1183 | 2.112 | 2.1736 | cold | true |
| readcon-core | write | gather | 8 | 395923 | 1073742498 | 2.1521 | 2.1017 | 2.2621 | warm | true |
| readcon-db | ingest | single | 1 | 123860 | 4296285556 | 33.552 | 31.287 | 34.367 | cold | true |
| readcon-db | ingest | single | 1 | 123860 | 4296285556 | 31.699 | 30.861 | 36.466 | warm | true |
| readcon-db | ingest | single | 2 | 61930 | 4296285556 | 24.208 | 23.934 | 25.86 | cold | true |
| readcon-db | ingest | single | 2 | 61930 | 4296285556 | 23.305 | 23.141 | 23.703 | warm | true |
| readcon-db | ingest | single | 4 | 30965 | 4296285556 | 19.76 | 19.195 | 28.385 | cold | true |
| readcon-db | ingest | single | 4 | 30965 | 4296285556 | 19.322 | 19.215 | 19.764 | warm | true |
| readcon-db | ingest | single | 8 | 15482.5 | 4296285556 | 18.133 | 17.182 | 21.784 | cold | true |
| readcon-db | ingest | single | 8 | 15482.5 | 4296285556 | 16.81 | 16.663 | 17.33 | warm | true |
| readcon-db | ingest | sharded | 1 | 123860 | 4296285556 | 33.348 | 32.918 | 39.84 | cold | true |
| readcon-db | ingest | sharded | 1 | 123860 | 4296285556 | 32.549 | 32.387 | 32.734 | warm | true |
| readcon-db | ingest | sharded | 2 | 61930 | 4296285556 | 25.548 | 25.153 | 41.806 | cold | true |
| readcon-db | ingest | sharded | 2 | 61930 | 4296285556 | 25.452 | 25.326 | 27.023 | warm | true |
| readcon-db | ingest | sharded | 4 | 30965 | 4296285556 | 22.145 | 21.005 | 22.502 | cold | true |
| readcon-db | ingest | sharded | 4 | 30965 | 4296285556 | 21.259 | 20.199 | 24.906 | warm | true |
| readcon-db | ingest | sharded | 8 | 15482.5 | 4296285556 | 19.078 | 18.912 | 23.929 | cold | true |
| readcon-db | ingest | sharded | 8 | 15482.5 | 4296285556 | 18.805 | 18.644 | 18.879 | warm | true |

#### weak

| system | operation | mode | ranks | frames_per_rank | bytes_total | median_s | min_s | max_s | cache | sha_match |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| readcon-core | read | shared | 1 | 400000 | 135600000 | 1.2437 | 1.1982 | 1.5448 | cold | true |
| readcon-core | read | shared | 1 | 400000 | 135600000 | 1.161 | 1.1489 | 1.1889 | warm | true |
| readcon-core | read | shared | 2 | 400000 | 271200000 | 1.3917 | 1.3235 | 2.0205 | cold | true |
| readcon-core | read | shared | 2 | 400000 | 271200000 | 1.2083 | 1.1653 | 1.2347 | warm | true |
| readcon-core | read | shared | 4 | 400000 | 542400000 | 1.6681 | 1.6127 | 2.7124 | cold | true |
| readcon-core | read | shared | 4 | 400000 | 542400000 | 1.3546 | 1.311 | 1.3663 | warm | true |
| readcon-core | read | shared | 8 | 400000 | 1084800000 | 2.1866 | 2.1712 | 4.2727 | cold | true |
| readcon-core | read | shared | 8 | 400000 | 1084800000 | 1.5815 | 1.5727 | 1.7924 | warm | true |
| readcon-core | read | scatter | 1 | 400000 | 135600000 | 1.3138 | 1.2488 | 1.3222 | cold | true |
| readcon-core | read | scatter | 1 | 400000 | 135600000 | 1.218 | 1.1689 | 1.2424 | warm | true |
| readcon-core | read | scatter | 2 | 400000 | 271200000 | 1.4864 | 1.4306 | 1.5138 | cold | true |
| readcon-core | read | scatter | 2 | 400000 | 271200000 | 1.2778 | 1.2773 | 1.382 | warm | true |
| readcon-core | read | scatter | 4 | 400000 | 542400000 | 1.8242 | 1.7939 | 1.8548 | cold | true |
| readcon-core | read | scatter | 4 | 400000 | 542400000 | 1.5246 | 1.478 | 1.5609 | warm | true |
| readcon-core | read | scatter | 8 | 400000 | 1084800000 | 2.6279 | 2.5412 | 7.1933 | cold | true |
| readcon-core | read | scatter | 8 | 400000 | 1084800000 | 1.9617 | 1.9486 | 2.264 | warm | true |
| readcon-core | write | mpiio | 1 | 400000 | 135600000 | 1.0506 | 1.0391 | 1.0624 | cold | true |
| readcon-core | write | mpiio | 1 | 400000 | 135600000 | 1.0369 | 1.0318 | 1.0876 | warm | true |
| readcon-core | write | mpiio | 2 | 400000 | 271200000 | 1.0906 | 1.0798 | 1.0963 | cold | true |
| readcon-core | write | mpiio | 2 | 400000 | 271200000 | 1.0854 | 1.0745 | 1.1029 | warm | true |
| readcon-core | write | mpiio | 4 | 400000 | 542400000 | 1.2009 | 1.1886 | 1.2999 | cold | true |
| readcon-core | write | mpiio | 4 | 400000 | 542400000 | 1.1986 | 1.1899 | 1.2271 | warm | true |
| readcon-core | write | mpiio | 8 | 400000 | 1084800000 | 1.4361 | 1.3672 | 1.7969 | cold | true |
| readcon-core | write | mpiio | 8 | 400000 | 1084800000 | 1.3821 | 1.3651 | 1.4463 | warm | true |
| readcon-core | write | gather | 1 | 400000 | 135600000 | 1.2284 | 1.213 | 1.248 | cold | true |
| readcon-core | write | gather | 1 | 400000 | 135600000 | 1.2113 | 1.1644 | 1.2382 | warm | true |
| readcon-core | write | gather | 2 | 400000 | 271200000 | 1.4119 | 1.2471 | 1.5437 | cold | true |
| readcon-core | write | gather | 2 | 400000 | 271200000 | 1.3175 | 1.3092 | 1.3219 | warm | true |
| readcon-core | write | gather | 4 | 400000 | 542400000 | 1.5305 | 1.5102 | 1.9459 | cold | true |
| readcon-core | write | gather | 4 | 400000 | 542400000 | 1.5719 | 1.5066 | 1.6129 | warm | true |
| readcon-core | write | gather | 8 | 400000 | 1084800000 | 2.0785 | 2.0377 | 2.6988 | cold | true |
| readcon-core | write | gather | 8 | 400000 | 1084800000 | 2.161 | 2.097 | 2.2958 | warm | true |
| readcon-db | ingest | single | 1 | 30800 | 1068323900 | 7.9 | 7.869 | 8.444 | cold | true |
| readcon-db | ingest | single | 1 | 30800 | 1068323900 | 7.841 | 7.701 | 7.923 | warm | true |
| readcon-db | ingest | single | 2 | 30800 | 2136675340 | 11.893 | 11.675 | 18.447 | cold | true |
| readcon-db | ingest | single | 2 | 30800 | 2136675340 | 11.518 | 11.392 | 11.854 | warm | true |
| readcon-db | ingest | single | 4 | 30800 | 4273391820 | 20.264 | 19.865 | 23.177 | cold | true |
| readcon-db | ingest | single | 4 | 30800 | 4273391820 | 18.902 | 18.72 | 19.846 | warm | true |
| readcon-db | ingest | single | 8 | 30800 | 8546831576 | 29.606 | 29.503 | 40.565 | cold | true |
| readcon-db | ingest | single | 8 | 30800 | 8546831576 | 29.594 | 28.943 | 30.364 | warm | true |
| readcon-db | ingest | sharded | 1 | 30800 | 1068323900 | 7.76 | 7.589 | 9.905 | cold | true |
| readcon-db | ingest | sharded | 1 | 30800 | 1068323900 | 7.465 | 7.452 | 7.497 | warm | true |
| readcon-db | ingest | sharded | 2 | 30800 | 2136675340 | 11.088 | 10.998 | 12.714 | cold | true |
| readcon-db | ingest | sharded | 2 | 30800 | 2136675340 | 10.856 | 10.821 | 10.891 | warm | true |
| readcon-db | ingest | sharded | 4 | 30800 | 4273391820 | 18.153 | 17.97 | 20.462 | cold | true |
| readcon-db | ingest | sharded | 4 | 30800 | 4273391820 | 18.375 | 18.172 | 19.113 | warm | true |
| readcon-db | ingest | sharded | 8 | 30800 | 8546831576 | 35.345 | 34.356 | 44.072 | cold | true |
| readcon-db | ingest | sharded | 8 | 30800 | 8546831576 | 34.899 | 34.807 | 36.533 | warm | true |

### Every repeat

Seconds are the harness times. The raw timing line is the rank-0 print from the example.

| scale | system | operation | mode | ranks | cache | rep | seconds | frames | sha_match | line |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| strong | readcon-core | read | scatter | 1 | cold | 1 | 10.123 | 3167382 | true | ranks=1 mode=scatter frames=3167382 distributed_ms=10123.0 serial_ms=15317.4 identical=true |
| strong | readcon-core | read | scatter | 1 | cold | 2 | 10.0495 | 3167382 | true | ranks=1 mode=scatter frames=3167382 distributed_ms=10049.5 serial_ms=15683.3 identical=true |
| strong | readcon-core | read | scatter | 1 | cold | 3 | 9.9203 | 3167382 | true | ranks=1 mode=scatter frames=3167382 distributed_ms=9920.3 serial_ms=16023.4 identical=true |
| strong | readcon-core | read | scatter | 1 | cold | 4 | 9.7042 | 3167382 | true | ranks=1 mode=scatter frames=3167382 distributed_ms=9704.2 serial_ms=15985.4 identical=true |
| strong | readcon-core | read | scatter | 1 | cold | 5 | 9.9486 | 3167382 | true | ranks=1 mode=scatter frames=3167382 distributed_ms=9948.6 serial_ms=15945.5 identical=true |
| strong | readcon-core | read | scatter | 1 | warm | 1 | 9.196200000000001 | 3167382 | true | ranks=1 mode=scatter frames=3167382 distributed_ms=9196.2 serial_ms=15739.9 identical=true |
| strong | readcon-core | read | scatter | 1 | warm | 2 | 9.355 | 3167382 | true | ranks=1 mode=scatter frames=3167382 distributed_ms=9355.0 serial_ms=15377.0 identical=true |
| strong | readcon-core | read | scatter | 1 | warm | 3 | 9.8292 | 3167382 | true | ranks=1 mode=scatter frames=3167382 distributed_ms=9829.2 serial_ms=15940.0 identical=true |
| strong | readcon-core | read | scatter | 1 | warm | 4 | 9.116700000000002 | 3167382 | true | ranks=1 mode=scatter frames=3167382 distributed_ms=9116.7 serial_ms=15682.8 identical=true |
| strong | readcon-core | read | scatter | 1 | warm | 5 | 9.2225 | 3167382 | true | ranks=1 mode=scatter frames=3167382 distributed_ms=9222.5 serial_ms=15639.5 identical=true |
| strong | readcon-core | read | scatter | 2 | cold | 1 | 5.4728 | 3167382 | true | ranks=2 mode=scatter frames=3167382 distributed_ms=5472.8 serial_ms=12574.2 identical=true |
| strong | readcon-core | read | scatter | 2 | cold | 2 | 5.533 | 3167382 | true | ranks=2 mode=scatter frames=3167382 distributed_ms=5533.0 serial_ms=13556.1 identical=true |
| strong | readcon-core | read | scatter | 2 | cold | 3 | 5.594 | 3167382 | true | ranks=2 mode=scatter frames=3167382 distributed_ms=5594.0 serial_ms=13902.6 identical=true |
| strong | readcon-core | read | scatter | 2 | cold | 4 | 5.6935 | 3167382 | true | ranks=2 mode=scatter frames=3167382 distributed_ms=5693.5 serial_ms=13430.7 identical=true |
| strong | readcon-core | read | scatter | 2 | cold | 5 | 5.5953 | 3167382 | true | ranks=2 mode=scatter frames=3167382 distributed_ms=5595.3 serial_ms=13164.2 identical=true |
| strong | readcon-core | read | scatter | 2 | warm | 1 | 4.9524 | 3167382 | true | ranks=2 mode=scatter frames=3167382 distributed_ms=4952.4 serial_ms=13196.0 identical=true |
| strong | readcon-core | read | scatter | 2 | warm | 2 | 4.9386 | 3167382 | true | ranks=2 mode=scatter frames=3167382 distributed_ms=4938.6 serial_ms=13606.0 identical=true |
| strong | readcon-core | read | scatter | 2 | warm | 3 | 5.013 | 3167382 | true | ranks=2 mode=scatter frames=3167382 distributed_ms=5013.0 serial_ms=13345.3 identical=true |
| strong | readcon-core | read | scatter | 2 | warm | 4 | 5.0251 | 3167382 | true | ranks=2 mode=scatter frames=3167382 distributed_ms=5025.1 serial_ms=13655.6 identical=true |
| strong | readcon-core | read | scatter | 2 | warm | 5 | 5.2123 | 3167382 | true | ranks=2 mode=scatter frames=3167382 distributed_ms=5212.3 serial_ms=13881.5 identical=true |
| strong | readcon-core | read | scatter | 4 | cold | 1 | 3.616 | 3167382 | true | ranks=4 mode=scatter frames=3167382 distributed_ms=3616.0 serial_ms=13029.8 identical=true |
| strong | readcon-core | read | scatter | 4 | cold | 2 | 3.4828 | 3167382 | true | ranks=4 mode=scatter frames=3167382 distributed_ms=3482.8 serial_ms=13336.1 identical=true |
| strong | readcon-core | read | scatter | 4 | cold | 3 | 3.5373 | 3167382 | true | ranks=4 mode=scatter frames=3167382 distributed_ms=3537.3 serial_ms=13604.4 identical=true |
| strong | readcon-core | read | scatter | 4 | cold | 4 | 3.4914 | 3167382 | true | ranks=4 mode=scatter frames=3167382 distributed_ms=3491.4 serial_ms=13331.4 identical=true |
| strong | readcon-core | read | scatter | 4 | cold | 5 | 3.5173 | 3167382 | true | ranks=4 mode=scatter frames=3167382 distributed_ms=3517.3 serial_ms=13443.4 identical=true |
| strong | readcon-core | read | scatter | 4 | warm | 1 | 2.9806 | 3167382 | true | ranks=4 mode=scatter frames=3167382 distributed_ms=2980.6 serial_ms=13072.8 identical=true |
| strong | readcon-core | read | scatter | 4 | warm | 2 | 2.9612 | 3167382 | true | ranks=4 mode=scatter frames=3167382 distributed_ms=2961.2 serial_ms=12704.1 identical=true |
| strong | readcon-core | read | scatter | 4 | warm | 3 | 2.9226 | 3167382 | true | ranks=4 mode=scatter frames=3167382 distributed_ms=2922.6 serial_ms=12772.7 identical=true |
| strong | readcon-core | read | scatter | 4 | warm | 4 | 2.8879 | 3167382 | true | ranks=4 mode=scatter frames=3167382 distributed_ms=2887.9 serial_ms=12975.6 identical=true |
| strong | readcon-core | read | scatter | 4 | warm | 5 | 2.8712 | 3167382 | true | ranks=4 mode=scatter frames=3167382 distributed_ms=2871.2 serial_ms=12518.4 identical=true |
| strong | readcon-core | read | scatter | 8 | cold | 1 | 2.355 | 3167382 | true | ranks=8 mode=scatter frames=3167382 distributed_ms=2355.0 serial_ms=12771.1 identical=true |
| strong | readcon-core | read | scatter | 8 | cold | 2 | 2.4985 | 3167382 | true | ranks=8 mode=scatter frames=3167382 distributed_ms=2498.5 serial_ms=12736.2 identical=true |
| strong | readcon-core | read | scatter | 8 | cold | 3 | 2.4379 | 3167382 | true | ranks=8 mode=scatter frames=3167382 distributed_ms=2437.9 serial_ms=12548.9 identical=true |
| strong | readcon-core | read | scatter | 8 | cold | 4 | 2.4092 | 3167382 | true | ranks=8 mode=scatter frames=3167382 distributed_ms=2409.2 serial_ms=12993.1 identical=true |
| strong | readcon-core | read | scatter | 8 | cold | 5 | 2.4402 | 3167382 | true | ranks=8 mode=scatter frames=3167382 distributed_ms=2440.2 serial_ms=12846.1 identical=true |
| strong | readcon-core | read | scatter | 8 | warm | 1 | 1.8105 | 3167382 | true | ranks=8 mode=scatter frames=3167382 distributed_ms=1810.5 serial_ms=12636.6 identical=true |
| strong | readcon-core | read | scatter | 8 | warm | 2 | 1.8659000000000001 | 3167382 | true | ranks=8 mode=scatter frames=3167382 distributed_ms=1865.9 serial_ms=13030.0 identical=true |
| strong | readcon-core | read | scatter | 8 | warm | 3 | 1.875 | 3167382 | true | ranks=8 mode=scatter frames=3167382 distributed_ms=1875.0 serial_ms=12628.4 identical=true |
| strong | readcon-core | read | scatter | 8 | warm | 4 | 1.8357999999999999 | 3167382 | true | ranks=8 mode=scatter frames=3167382 distributed_ms=1835.8 serial_ms=12425.6 identical=true |
| strong | readcon-core | read | scatter | 8 | warm | 5 | 1.8117999999999999 | 3167382 | true | ranks=8 mode=scatter frames=3167382 distributed_ms=1811.8 serial_ms=12514.6 identical=true |
| strong | readcon-core | read | shared | 1 | cold | 1 | 11.8569 | 3167382 | true | ranks=1 mode=shared frames=3167382 distributed_ms=11856.9 serial_ms=54052.8 identical=true |
| strong | readcon-core | read | shared | 1 | cold | 2 | 9.9043 | 3167382 | true | ranks=1 mode=shared frames=3167382 distributed_ms=9904.3 serial_ms=15659.4 identical=true |
| strong | readcon-core | read | shared | 1 | cold | 3 | 9.4382 | 3167382 | true | ranks=1 mode=shared frames=3167382 distributed_ms=9438.2 serial_ms=15208.1 identical=true |
| strong | readcon-core | read | shared | 1 | cold | 4 | 10.445799999999998 | 3167382 | true | ranks=1 mode=shared frames=3167382 distributed_ms=10445.8 serial_ms=15965.2 identical=true |
| strong | readcon-core | read | shared | 1 | cold | 5 | 9.7246 | 3167382 | true | ranks=1 mode=shared frames=3167382 distributed_ms=9724.6 serial_ms=16569.3 identical=true |
| strong | readcon-core | read | shared | 1 | warm | 1 | 9.0345 | 3167382 | true | ranks=1 mode=shared frames=3167382 distributed_ms=9034.5 serial_ms=16024.5 identical=true |
| strong | readcon-core | read | shared | 1 | warm | 2 | 9.314 | 3167382 | true | ranks=1 mode=shared frames=3167382 distributed_ms=9314.0 serial_ms=16704.4 identical=true |
| strong | readcon-core | read | shared | 1 | warm | 3 | 9.3241 | 3167382 | true | ranks=1 mode=shared frames=3167382 distributed_ms=9324.1 serial_ms=15882.0 identical=true |
| strong | readcon-core | read | shared | 1 | warm | 4 | 9.0881 | 3167382 | true | ranks=1 mode=shared frames=3167382 distributed_ms=9088.1 serial_ms=16254.4 identical=true |
| strong | readcon-core | read | shared | 1 | warm | 5 | 8.9995 | 3167382 | true | ranks=1 mode=shared frames=3167382 distributed_ms=8999.5 serial_ms=16356.0 identical=true |
| strong | readcon-core | read | shared | 2 | cold | 1 | 5.2817 | 3167382 | true | ranks=2 mode=shared frames=3167382 distributed_ms=5281.7 serial_ms=12985.4 identical=true |
| strong | readcon-core | read | shared | 2 | cold | 2 | 5.6773 | 3167382 | true | ranks=2 mode=shared frames=3167382 distributed_ms=5677.3 serial_ms=14496.2 identical=true |
| strong | readcon-core | read | shared | 2 | cold | 3 | 5.8292 | 3167382 | true | ranks=2 mode=shared frames=3167382 distributed_ms=5829.2 serial_ms=14684.5 identical=true |
| strong | readcon-core | read | shared | 2 | cold | 4 | 5.6774 | 3167382 | true | ranks=2 mode=shared frames=3167382 distributed_ms=5677.4 serial_ms=14277.9 identical=true |
| strong | readcon-core | read | shared | 2 | cold | 5 | 5.531 | 3167382 | true | ranks=2 mode=shared frames=3167382 distributed_ms=5531.0 serial_ms=13821.3 identical=true |
| strong | readcon-core | read | shared | 2 | warm | 1 | 4.6417 | 3167382 | true | ranks=2 mode=shared frames=3167382 distributed_ms=4641.7 serial_ms=14829.5 identical=true |
| strong | readcon-core | read | shared | 2 | warm | 2 | 4.7046 | 3167382 | true | ranks=2 mode=shared frames=3167382 distributed_ms=4704.6 serial_ms=13523.0 identical=true |
| strong | readcon-core | read | shared | 2 | warm | 3 | 4.6509 | 3167382 | true | ranks=2 mode=shared frames=3167382 distributed_ms=4650.9 serial_ms=14475.6 identical=true |
| strong | readcon-core | read | shared | 2 | warm | 4 | 4.7501999999999995 | 3167382 | true | ranks=2 mode=shared frames=3167382 distributed_ms=4750.2 serial_ms=14285.1 identical=true |
| strong | readcon-core | read | shared | 2 | warm | 5 | 4.6161 | 3167382 | true | ranks=2 mode=shared frames=3167382 distributed_ms=4616.1 serial_ms=14104.3 identical=true |
| strong | readcon-core | read | shared | 4 | cold | 1 | 3.3416 | 3167382 | true | ranks=4 mode=shared frames=3167382 distributed_ms=3341.6 serial_ms=12976.3 identical=true |
| strong | readcon-core | read | shared | 4 | cold | 2 | 3.2205 | 3167382 | true | ranks=4 mode=shared frames=3167382 distributed_ms=3220.5 serial_ms=13607.9 identical=true |
| strong | readcon-core | read | shared | 4 | cold | 3 | 3.1854 | 3167382 | true | ranks=4 mode=shared frames=3167382 distributed_ms=3185.4 serial_ms=13344.9 identical=true |
| strong | readcon-core | read | shared | 4 | cold | 4 | 3.1049 | 3167382 | true | ranks=4 mode=shared frames=3167382 distributed_ms=3104.9 serial_ms=13232.4 identical=true |
| strong | readcon-core | read | shared | 4 | cold | 5 | 3.3673 | 3167382 | true | ranks=4 mode=shared frames=3167382 distributed_ms=3367.3 serial_ms=13808.6 identical=true |
| strong | readcon-core | read | shared | 4 | warm | 1 | 2.4920999999999998 | 3167382 | true | ranks=4 mode=shared frames=3167382 distributed_ms=2492.1 serial_ms=13428.1 identical=true |
| strong | readcon-core | read | shared | 4 | warm | 2 | 2.4875 | 3167382 | true | ranks=4 mode=shared frames=3167382 distributed_ms=2487.5 serial_ms=13398.2 identical=true |
| strong | readcon-core | read | shared | 4 | warm | 3 | 2.6712 | 3167382 | true | ranks=4 mode=shared frames=3167382 distributed_ms=2671.2 serial_ms=13754.1 identical=true |
| strong | readcon-core | read | shared | 4 | warm | 4 | 2.5913000000000004 | 3167382 | true | ranks=4 mode=shared frames=3167382 distributed_ms=2591.3 serial_ms=13834.5 identical=true |
| strong | readcon-core | read | shared | 4 | warm | 5 | 3.1034 | 3167382 | true | ranks=4 mode=shared frames=3167382 distributed_ms=3103.4 serial_ms=13235.3 identical=true |
| strong | readcon-core | read | shared | 8 | cold | 1 | 2.0149 | 3167382 | true | ranks=8 mode=shared frames=3167382 distributed_ms=2014.9 serial_ms=13382.1 identical=true |
| strong | readcon-core | read | shared | 8 | cold | 2 | 2.1327 | 3167382 | true | ranks=8 mode=shared frames=3167382 distributed_ms=2132.7 serial_ms=12729.4 identical=true |
| strong | readcon-core | read | shared | 8 | cold | 3 | 2.3411999999999997 | 3167382 | true | ranks=8 mode=shared frames=3167382 distributed_ms=2341.2 serial_ms=12784.5 identical=true |
| strong | readcon-core | read | shared | 8 | cold | 4 | 2.1053 | 3167382 | true | ranks=8 mode=shared frames=3167382 distributed_ms=2105.3 serial_ms=12978.3 identical=true |
| strong | readcon-core | read | shared | 8 | cold | 5 | 2.1128 | 3167382 | true | ranks=8 mode=shared frames=3167382 distributed_ms=2112.8 serial_ms=13332.8 identical=true |
| strong | readcon-core | read | shared | 8 | warm | 1 | 1.5041 | 3167382 | true | ranks=8 mode=shared frames=3167382 distributed_ms=1504.1 serial_ms=12855.8 identical=true |
| strong | readcon-core | read | shared | 8 | warm | 2 | 1.5513 | 3167382 | true | ranks=8 mode=shared frames=3167382 distributed_ms=1551.3 serial_ms=13016.3 identical=true |
| strong | readcon-core | read | shared | 8 | warm | 3 | 1.5697999999999999 | 3167382 | true | ranks=8 mode=shared frames=3167382 distributed_ms=1569.8 serial_ms=13445.6 identical=true |
| strong | readcon-core | read | shared | 8 | warm | 4 | 1.4837 | 3167382 | true | ranks=8 mode=shared frames=3167382 distributed_ms=1483.7 serial_ms=12629.0 identical=true |
| strong | readcon-core | read | shared | 8 | warm | 5 | 1.4163 | 3167382 | true | ranks=8 mode=shared frames=3167382 distributed_ms=1416.3 serial_ms=12310.7 identical=true |
| strong | readcon-core | write | gather | 1 | cold | 1 | 9.4914 | 3167382 | true | ranks=1 mode=gather frames=3167382 bytes=934377690 write_ms=9491.4 serial_write_ms=6421.1 identical=true sidecar_ok=true |
| strong | readcon-core | write | gather | 1 | cold | 2 | 9.073799999999999 | 3167382 | true | ranks=1 mode=gather frames=3167382 bytes=934377690 write_ms=9073.8 serial_write_ms=6198.2 identical=true sidecar_ok=true |
| strong | readcon-core | write | gather | 1 | cold | 3 | 8.917399999999999 | 3167382 | true | ranks=1 mode=gather frames=3167382 bytes=934377690 write_ms=8917.4 serial_write_ms=6029.0 identical=true sidecar_ok=true |
| strong | readcon-core | write | gather | 1 | cold | 4 | 9.232899999999999 | 3167382 | true | ranks=1 mode=gather frames=3167382 bytes=934377690 write_ms=9232.9 serial_write_ms=6052.6 identical=true sidecar_ok=true |
| strong | readcon-core | write | gather | 1 | cold | 5 | 9.6061 | 3167382 | true | ranks=1 mode=gather frames=3167382 bytes=934377690 write_ms=9606.1 serial_write_ms=6014.9 identical=true sidecar_ok=true |
| strong | readcon-core | write | gather | 1 | warm | 1 | 9.4179 | 3167382 | true | ranks=1 mode=gather frames=3167382 bytes=934377690 write_ms=9417.9 serial_write_ms=6207.8 identical=true sidecar_ok=true |
| strong | readcon-core | write | gather | 1 | warm | 2 | 9.6096 | 3167382 | true | ranks=1 mode=gather frames=3167382 bytes=934377690 write_ms=9609.6 serial_write_ms=6003.0 identical=true sidecar_ok=true |
| strong | readcon-core | write | gather | 1 | warm | 3 | 9.489799999999999 | 3167382 | true | ranks=1 mode=gather frames=3167382 bytes=934377690 write_ms=9489.8 serial_write_ms=7586.6 identical=true sidecar_ok=true |
| strong | readcon-core | write | gather | 1 | warm | 4 | 9.4047 | 3167382 | true | ranks=1 mode=gather frames=3167382 bytes=934377690 write_ms=9404.7 serial_write_ms=5991.4 identical=true sidecar_ok=true |
| strong | readcon-core | write | gather | 1 | warm | 5 | 10.879 | 3167382 | true | ranks=1 mode=gather frames=3167382 bytes=934377690 write_ms=10879.0 serial_write_ms=6212.7 identical=true sidecar_ok=true |
| strong | readcon-core | write | gather | 2 | cold | 1 | 5.2105 | 3167382 | true | ranks=2 mode=gather frames=3167382 bytes=934377690 write_ms=5210.5 serial_write_ms=6094.7 identical=true sidecar_ok=true |
| strong | readcon-core | write | gather | 2 | cold | 2 | 5.4422 | 3167382 | true | ranks=2 mode=gather frames=3167382 bytes=934377690 write_ms=5442.2 serial_write_ms=6169.6 identical=true sidecar_ok=true |
| strong | readcon-core | write | gather | 2 | cold | 3 | 5.4248 | 3167382 | true | ranks=2 mode=gather frames=3167382 bytes=934377690 write_ms=5424.8 serial_write_ms=6012.1 identical=true sidecar_ok=true |
| strong | readcon-core | write | gather | 2 | cold | 4 | 5.6129 | 3167382 | true | ranks=2 mode=gather frames=3167382 bytes=934377690 write_ms=5612.9 serial_write_ms=6204.1 identical=true sidecar_ok=true |
| strong | readcon-core | write | gather | 2 | cold | 5 | 5.448600000000001 | 3167382 | true | ranks=2 mode=gather frames=3167382 bytes=934377690 write_ms=5448.6 serial_write_ms=6040.1 identical=true sidecar_ok=true |
| strong | readcon-core | write | gather | 2 | warm | 1 | 5.2803 | 3167382 | true | ranks=2 mode=gather frames=3167382 bytes=934377690 write_ms=5280.3 serial_write_ms=16292.8 identical=true sidecar_ok=true |
| strong | readcon-core | write | gather | 2 | warm | 2 | 5.8331 | 3167382 | true | ranks=2 mode=gather frames=3167382 bytes=934377690 write_ms=5833.1 serial_write_ms=6026.6 identical=true sidecar_ok=true |
| strong | readcon-core | write | gather | 2 | warm | 3 | 5.0393 | 3167382 | true | ranks=2 mode=gather frames=3167382 bytes=934377690 write_ms=5039.3 serial_write_ms=6031.7 identical=true sidecar_ok=true |
| strong | readcon-core | write | gather | 2 | warm | 4 | 5.0469 | 3167382 | true | ranks=2 mode=gather frames=3167382 bytes=934377690 write_ms=5046.9 serial_write_ms=6107.0 identical=true sidecar_ok=true |
| strong | readcon-core | write | gather | 2 | warm | 5 | 5.0521 | 3167382 | true | ranks=2 mode=gather frames=3167382 bytes=934377690 write_ms=5052.1 serial_write_ms=6006.9 identical=true sidecar_ok=true |
| strong | readcon-core | write | gather | 4 | cold | 1 | 3.0505999999999998 | 3167382 | true | ranks=4 mode=gather frames=3167382 bytes=934377690 write_ms=3050.6 serial_write_ms=5983.7 identical=true sidecar_ok=true |
| strong | readcon-core | write | gather | 4 | cold | 2 | 3.0501 | 3167382 | true | ranks=4 mode=gather frames=3167382 bytes=934377690 write_ms=3050.1 serial_write_ms=6022.9 identical=true sidecar_ok=true |
| strong | readcon-core | write | gather | 4 | cold | 3 | 3.399 | 3167382 | true | ranks=4 mode=gather frames=3167382 bytes=934377690 write_ms=3399.0 serial_write_ms=6017.3 identical=true sidecar_ok=true |
| strong | readcon-core | write | gather | 4 | cold | 4 | 3.0791 | 3167382 | true | ranks=4 mode=gather frames=3167382 bytes=934377690 write_ms=3079.1 serial_write_ms=6008.4 identical=true sidecar_ok=true |
| strong | readcon-core | write | gather | 4 | cold | 5 | 3.0305 | 3167382 | true | ranks=4 mode=gather frames=3167382 bytes=934377690 write_ms=3030.5 serial_write_ms=6040.0 identical=true sidecar_ok=true |
| strong | readcon-core | write | gather | 4 | warm | 1 | 3.0902 | 3167382 | true | ranks=4 mode=gather frames=3167382 bytes=934377690 write_ms=3090.2 serial_write_ms=6166.0 identical=true sidecar_ok=true |
| strong | readcon-core | write | gather | 4 | warm | 2 | 3.0231999999999997 | 3167382 | true | ranks=4 mode=gather frames=3167382 bytes=934377690 write_ms=3023.2 serial_write_ms=6238.0 identical=true sidecar_ok=true |
| strong | readcon-core | write | gather | 4 | warm | 3 | 3.0976999999999997 | 3167382 | true | ranks=4 mode=gather frames=3167382 bytes=934377690 write_ms=3097.7 serial_write_ms=6048.0 identical=true sidecar_ok=true |
| strong | readcon-core | write | gather | 4 | warm | 4 | 3.0667 | 3167382 | true | ranks=4 mode=gather frames=3167382 bytes=934377690 write_ms=3066.7 serial_write_ms=5997.7 identical=true sidecar_ok=true |
| strong | readcon-core | write | gather | 4 | warm | 5 | 3.075 | 3167382 | true | ranks=4 mode=gather frames=3167382 bytes=934377690 write_ms=3075.0 serial_write_ms=6021.9 identical=true sidecar_ok=true |
| strong | readcon-core | write | gather | 8 | cold | 1 | 2.159 | 3167382 | true | ranks=8 mode=gather frames=3167382 bytes=934377690 write_ms=2159.0 serial_write_ms=7240.9 identical=true sidecar_ok=true |
| strong | readcon-core | write | gather | 8 | cold | 2 | 2.1736 | 3167382 | true | ranks=8 mode=gather frames=3167382 bytes=934377690 write_ms=2173.6 serial_write_ms=6012.3 identical=true sidecar_ok=true |
| strong | readcon-core | write | gather | 8 | cold | 3 | 2.1183 | 3167382 | true | ranks=8 mode=gather frames=3167382 bytes=934377690 write_ms=2118.3 serial_write_ms=6034.2 identical=true sidecar_ok=true |
| strong | readcon-core | write | gather | 8 | cold | 4 | 2.1141 | 3167382 | true | ranks=8 mode=gather frames=3167382 bytes=934377690 write_ms=2114.1 serial_write_ms=6039.2 identical=true sidecar_ok=true |
| strong | readcon-core | write | gather | 8 | cold | 5 | 2.112 | 3167382 | true | ranks=8 mode=gather frames=3167382 bytes=934377690 write_ms=2112.0 serial_write_ms=6419.6 identical=true sidecar_ok=true |
| strong | readcon-core | write | gather | 8 | warm | 1 | 2.2620999999999998 | 3167382 | true | ranks=8 mode=gather frames=3167382 bytes=934377690 write_ms=2262.1 serial_write_ms=6025.4 identical=true sidecar_ok=true |
| strong | readcon-core | write | gather | 8 | warm | 2 | 2.1016999999999997 | 3167382 | true | ranks=8 mode=gather frames=3167382 bytes=934377690 write_ms=2101.7 serial_write_ms=6186.9 identical=true sidecar_ok=true |
| strong | readcon-core | write | gather | 8 | warm | 3 | 2.1372 | 3167382 | true | ranks=8 mode=gather frames=3167382 bytes=934377690 write_ms=2137.2 serial_write_ms=6080.8 identical=true sidecar_ok=true |
| strong | readcon-core | write | gather | 8 | warm | 4 | 2.1521 | 3167382 | true | ranks=8 mode=gather frames=3167382 bytes=934377690 write_ms=2152.1 serial_write_ms=6062.2 identical=true sidecar_ok=true |
| strong | readcon-core | write | gather | 8 | warm | 5 | 2.1576 | 3167382 | true | ranks=8 mode=gather frames=3167382 bytes=934377690 write_ms=2157.6 serial_write_ms=6195.7 identical=true sidecar_ok=true |
| strong | readcon-core | write | mpiio | 1 | cold | 1 | 8.6181 | 3167382 | true | ranks=1 mode=mpiio frames=3167382 bytes=934377690 write_ms=8618.1 serial_write_ms=6134.7 identical=true sidecar_ok=true |
| strong | readcon-core | write | mpiio | 1 | cold | 2 | 8.24 | 3167382 | true | ranks=1 mode=mpiio frames=3167382 bytes=934377690 write_ms=8240.0 serial_write_ms=6055.0 identical=true sidecar_ok=true |
| strong | readcon-core | write | mpiio | 1 | cold | 3 | 8.721200000000001 | 3167382 | true | ranks=1 mode=mpiio frames=3167382 bytes=934377690 write_ms=8721.2 serial_write_ms=6014.2 identical=true sidecar_ok=true |
| strong | readcon-core | write | mpiio | 1 | cold | 4 | 8.8568 | 3167382 | true | ranks=1 mode=mpiio frames=3167382 bytes=934377690 write_ms=8856.8 serial_write_ms=5995.9 identical=true sidecar_ok=true |
| strong | readcon-core | write | mpiio | 1 | cold | 5 | 8.9754 | 3167382 | true | ranks=1 mode=mpiio frames=3167382 bytes=934377690 write_ms=8975.4 serial_write_ms=9027.9 identical=true sidecar_ok=true |
| strong | readcon-core | write | mpiio | 1 | warm | 1 | 8.2377 | 3167382 | true | ranks=1 mode=mpiio frames=3167382 bytes=934377690 write_ms=8237.7 serial_write_ms=6021.9 identical=true sidecar_ok=true |
| strong | readcon-core | write | mpiio | 1 | warm | 2 | 8.5168 | 3167382 | true | ranks=1 mode=mpiio frames=3167382 bytes=934377690 write_ms=8516.8 serial_write_ms=6508.8 identical=true sidecar_ok=true |
| strong | readcon-core | write | mpiio | 1 | warm | 3 | 8.2476 | 3167382 | true | ranks=1 mode=mpiio frames=3167382 bytes=934377690 write_ms=8247.6 serial_write_ms=6019.5 identical=true sidecar_ok=true |
| strong | readcon-core | write | mpiio | 1 | warm | 4 | 8.403 | 3167382 | true | ranks=1 mode=mpiio frames=3167382 bytes=934377690 write_ms=8403.0 serial_write_ms=6049.5 identical=true sidecar_ok=true |
| strong | readcon-core | write | mpiio | 1 | warm | 5 | 8.369299999999999 | 3167382 | true | ranks=1 mode=mpiio frames=3167382 bytes=934377690 write_ms=8369.3 serial_write_ms=6647.1 identical=true sidecar_ok=true |
| strong | readcon-core | write | mpiio | 2 | cold | 1 | 4.3849 | 3167382 | true | ranks=2 mode=mpiio frames=3167382 bytes=934377690 write_ms=4384.9 serial_write_ms=6225.6 identical=true sidecar_ok=true |
| strong | readcon-core | write | mpiio | 2 | cold | 2 | 4.2877 | 3167382 | true | ranks=2 mode=mpiio frames=3167382 bytes=934377690 write_ms=4287.7 serial_write_ms=6179.0 identical=true sidecar_ok=true |
| strong | readcon-core | write | mpiio | 2 | cold | 3 | 4.2462 | 3167382 | true | ranks=2 mode=mpiio frames=3167382 bytes=934377690 write_ms=4246.2 serial_write_ms=6179.5 identical=true sidecar_ok=true |
| strong | readcon-core | write | mpiio | 2 | cold | 4 | 4.3116 | 3167382 | true | ranks=2 mode=mpiio frames=3167382 bytes=934377690 write_ms=4311.6 serial_write_ms=6122.3 identical=true sidecar_ok=true |
| strong | readcon-core | write | mpiio | 2 | cold | 5 | 4.217 | 3167382 | true | ranks=2 mode=mpiio frames=3167382 bytes=934377690 write_ms=4217.0 serial_write_ms=6091.7 identical=true sidecar_ok=true |
| strong | readcon-core | write | mpiio | 2 | warm | 1 | 4.0434 | 3167382 | true | ranks=2 mode=mpiio frames=3167382 bytes=934377690 write_ms=4043.4 serial_write_ms=6075.2 identical=true sidecar_ok=true |
| strong | readcon-core | write | mpiio | 2 | warm | 2 | 4.0601 | 3167382 | true | ranks=2 mode=mpiio frames=3167382 bytes=934377690 write_ms=4060.1 serial_write_ms=6021.4 identical=true sidecar_ok=true |
| strong | readcon-core | write | mpiio | 2 | warm | 3 | 4.0832 | 3167382 | true | ranks=2 mode=mpiio frames=3167382 bytes=934377690 write_ms=4083.2 serial_write_ms=6035.2 identical=true sidecar_ok=true |
| strong | readcon-core | write | mpiio | 2 | warm | 4 | 4.061 | 3167382 | true | ranks=2 mode=mpiio frames=3167382 bytes=934377690 write_ms=4061.0 serial_write_ms=6028.5 identical=true sidecar_ok=true |
| strong | readcon-core | write | mpiio | 2 | warm | 5 | 4.0432 | 3167382 | true | ranks=2 mode=mpiio frames=3167382 bytes=934377690 write_ms=4043.2 serial_write_ms=6100.7 identical=true sidecar_ok=true |
| strong | readcon-core | write | mpiio | 4 | cold | 1 | 2.3035 | 3167382 | true | ranks=4 mode=mpiio frames=3167382 bytes=934377690 write_ms=2303.5 serial_write_ms=6040.1 identical=true sidecar_ok=true |
| strong | readcon-core | write | mpiio | 4 | cold | 2 | 2.3310999999999997 | 3167382 | true | ranks=4 mode=mpiio frames=3167382 bytes=934377690 write_ms=2331.1 serial_write_ms=6102.1 identical=true sidecar_ok=true |
| strong | readcon-core | write | mpiio | 4 | cold | 3 | 2.3497 | 3167382 | true | ranks=4 mode=mpiio frames=3167382 bytes=934377690 write_ms=2349.7 serial_write_ms=6085.9 identical=true sidecar_ok=true |
| strong | readcon-core | write | mpiio | 4 | cold | 4 | 2.2694 | 3167382 | true | ranks=4 mode=mpiio frames=3167382 bytes=934377690 write_ms=2269.4 serial_write_ms=6036.7 identical=true sidecar_ok=true |
| strong | readcon-core | write | mpiio | 4 | cold | 5 | 2.2698 | 3167382 | true | ranks=4 mode=mpiio frames=3167382 bytes=934377690 write_ms=2269.8 serial_write_ms=6035.2 identical=true sidecar_ok=true |
| strong | readcon-core | write | mpiio | 4 | warm | 1 | 2.3047 | 3167382 | true | ranks=4 mode=mpiio frames=3167382 bytes=934377690 write_ms=2304.7 serial_write_ms=6116.7 identical=true sidecar_ok=true |
| strong | readcon-core | write | mpiio | 4 | warm | 2 | 2.2918000000000003 | 3167382 | true | ranks=4 mode=mpiio frames=3167382 bytes=934377690 write_ms=2291.8 serial_write_ms=6120.2 identical=true sidecar_ok=true |
| strong | readcon-core | write | mpiio | 4 | warm | 3 | 2.3387 | 3167382 | true | ranks=4 mode=mpiio frames=3167382 bytes=934377690 write_ms=2338.7 serial_write_ms=6072.7 identical=true sidecar_ok=true |
| strong | readcon-core | write | mpiio | 4 | warm | 4 | 2.3781999999999996 | 3167382 | true | ranks=4 mode=mpiio frames=3167382 bytes=934377690 write_ms=2378.2 serial_write_ms=6091.9 identical=true sidecar_ok=true |
| strong | readcon-core | write | mpiio | 4 | warm | 5 | 2.2595 | 3167382 | true | ranks=4 mode=mpiio frames=3167382 bytes=934377690 write_ms=2259.5 serial_write_ms=16559.3 identical=true sidecar_ok=true |
| strong | readcon-core | write | mpiio | 8 | cold | 1 | 2.7645999999999997 | 3167382 | true | ranks=8 mode=mpiio frames=3167382 bytes=934377690 write_ms=2764.6 serial_write_ms=7687.8 identical=true sidecar_ok=true |
| strong | readcon-core | write | mpiio | 8 | cold | 2 | 1.4770999999999999 | 3167382 | true | ranks=8 mode=mpiio frames=3167382 bytes=934377690 write_ms=1477.1 serial_write_ms=6170.7 identical=true sidecar_ok=true |
| strong | readcon-core | write | mpiio | 8 | cold | 3 | 1.3825999999999998 | 3167382 | true | ranks=8 mode=mpiio frames=3167382 bytes=934377690 write_ms=1382.6 serial_write_ms=7283.1 identical=true sidecar_ok=true |
| strong | readcon-core | write | mpiio | 8 | cold | 4 | 1.4058 | 3167382 | true | ranks=8 mode=mpiio frames=3167382 bytes=934377690 write_ms=1405.8 serial_write_ms=6061.5 identical=true sidecar_ok=true |
| strong | readcon-core | write | mpiio | 8 | cold | 5 | 1.5275999999999998 | 3167382 | true | ranks=8 mode=mpiio frames=3167382 bytes=934377690 write_ms=1527.6 serial_write_ms=6084.7 identical=true sidecar_ok=true |
| strong | readcon-core | write | mpiio | 8 | warm | 1 | 1.4161 | 3167382 | true | ranks=8 mode=mpiio frames=3167382 bytes=934377690 write_ms=1416.1 serial_write_ms=6657.5 identical=true sidecar_ok=true |
| strong | readcon-core | write | mpiio | 8 | warm | 2 | 1.4207 | 3167382 | true | ranks=8 mode=mpiio frames=3167382 bytes=934377690 write_ms=1420.7 serial_write_ms=6101.2 identical=true sidecar_ok=true |
| strong | readcon-core | write | mpiio | 8 | warm | 3 | 1.3657000000000001 | 3167382 | true | ranks=8 mode=mpiio frames=3167382 bytes=934377690 write_ms=1365.7 serial_write_ms=6068.7 identical=true sidecar_ok=true |
| strong | readcon-core | write | mpiio | 8 | warm | 4 | 1.4908 | 3167382 | true | ranks=8 mode=mpiio frames=3167382 bytes=934377690 write_ms=1490.8 serial_write_ms=6094.2 identical=true sidecar_ok=true |
| strong | readcon-core | write | mpiio | 8 | warm | 5 | 1.3782999999999999 | 3167382 | true | ranks=8 mode=mpiio frames=3167382 bytes=934377690 write_ms=1378.3 serial_write_ms=6074.7 identical=true sidecar_ok=true |
| strong | readcon-db | ingest | sharded | 1 | cold | 1 | 33.366 | 123860 | true | mode=sharded ranks=1 files=4 frames=123860 mpi_s=33.366 serial_s=39.188 mpi_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 serial_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 match=true |
| strong | readcon-db | ingest | sharded | 1 | cold | 2 | 39.84 | 123860 | true | mode=sharded ranks=1 files=4 frames=123860 mpi_s=39.840 serial_s=23.963 mpi_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 serial_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 match=true |
| strong | readcon-db | ingest | sharded | 1 | cold | 3 | 33.348 | 123860 | true | mode=sharded ranks=1 files=4 frames=123860 mpi_s=33.348 serial_s=23.344 mpi_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 serial_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 match=true |
| strong | readcon-db | ingest | sharded | 1 | cold | 4 | 33.144 | 123860 | true | mode=sharded ranks=1 files=4 frames=123860 mpi_s=33.144 serial_s=22.923 mpi_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 serial_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 match=true |
| strong | readcon-db | ingest | sharded | 1 | cold | 5 | 32.918 | 123860 | true | mode=sharded ranks=1 files=4 frames=123860 mpi_s=32.918 serial_s=23.565 mpi_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 serial_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 match=true |
| strong | readcon-db | ingest | sharded | 1 | warm | 1 | 32.387 | 123860 | true | mode=sharded ranks=1 files=4 frames=123860 mpi_s=32.387 serial_s=23.022 mpi_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 serial_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 match=true |
| strong | readcon-db | ingest | sharded | 1 | warm | 2 | 32.395 | 123860 | true | mode=sharded ranks=1 files=4 frames=123860 mpi_s=32.395 serial_s=22.930 mpi_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 serial_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 match=true |
| strong | readcon-db | ingest | sharded | 1 | warm | 3 | 32.582 | 123860 | true | mode=sharded ranks=1 files=4 frames=123860 mpi_s=32.582 serial_s=23.373 mpi_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 serial_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 match=true |
| strong | readcon-db | ingest | sharded | 1 | warm | 4 | 32.734 | 123860 | true | mode=sharded ranks=1 files=4 frames=123860 mpi_s=32.734 serial_s=23.269 mpi_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 serial_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 match=true |
| strong | readcon-db | ingest | sharded | 1 | warm | 5 | 32.549 | 123860 | true | mode=sharded ranks=1 files=4 frames=123860 mpi_s=32.549 serial_s=23.633 mpi_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 serial_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 match=true |
| strong | readcon-db | ingest | sharded | 2 | cold | 1 | 25.548 | 123860 | true | mode=sharded ranks=2 files=4 frames=123860 mpi_s=25.548 serial_s=26.279 mpi_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 serial_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 match=true |
| strong | readcon-db | ingest | sharded | 2 | cold | 2 | 25.153 | 123860 | true | mode=sharded ranks=2 files=4 frames=123860 mpi_s=25.153 serial_s=25.532 mpi_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 serial_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 match=true |
| strong | readcon-db | ingest | sharded | 2 | cold | 3 | 25.447 | 123860 | true | mode=sharded ranks=2 files=4 frames=123860 mpi_s=25.447 serial_s=25.677 mpi_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 serial_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 match=true |
| strong | readcon-db | ingest | sharded | 2 | cold | 4 | 25.806 | 123860 | true | mode=sharded ranks=2 files=4 frames=123860 mpi_s=25.806 serial_s=25.337 mpi_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 serial_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 match=true |
| strong | readcon-db | ingest | sharded | 2 | cold | 5 | 41.806 | 123860 | true | mode=sharded ranks=2 files=4 frames=123860 mpi_s=41.806 serial_s=25.636 mpi_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 serial_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 match=true |
| strong | readcon-db | ingest | sharded | 2 | warm | 1 | 27.023 | 123860 | true | mode=sharded ranks=2 files=4 frames=123860 mpi_s=27.023 serial_s=24.621 mpi_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 serial_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 match=true |
| strong | readcon-db | ingest | sharded | 2 | warm | 2 | 25.555 | 123860 | true | mode=sharded ranks=2 files=4 frames=123860 mpi_s=25.555 serial_s=24.944 mpi_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 serial_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 match=true |
| strong | readcon-db | ingest | sharded | 2 | warm | 3 | 25.326 | 123860 | true | mode=sharded ranks=2 files=4 frames=123860 mpi_s=25.326 serial_s=24.372 mpi_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 serial_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 match=true |
| strong | readcon-db | ingest | sharded | 2 | warm | 4 | 25.452 | 123860 | true | mode=sharded ranks=2 files=4 frames=123860 mpi_s=25.452 serial_s=24.408 mpi_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 serial_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 match=true |
| strong | readcon-db | ingest | sharded | 2 | warm | 5 | 25.386 | 123860 | true | mode=sharded ranks=2 files=4 frames=123860 mpi_s=25.386 serial_s=24.450 mpi_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 serial_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 match=true |
| strong | readcon-db | ingest | sharded | 4 | cold | 1 | 22.502 | 123860 | true | mode=sharded ranks=4 files=4 frames=123860 mpi_s=22.502 serial_s=24.970 mpi_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 serial_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 match=true |
| strong | readcon-db | ingest | sharded | 4 | cold | 2 | 21.005 | 123860 | true | mode=sharded ranks=4 files=4 frames=123860 mpi_s=21.005 serial_s=24.777 mpi_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 serial_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 match=true |
| strong | readcon-db | ingest | sharded | 4 | cold | 3 | 22.295 | 123860 | true | mode=sharded ranks=4 files=4 frames=123860 mpi_s=22.295 serial_s=26.528 mpi_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 serial_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 match=true |
| strong | readcon-db | ingest | sharded | 4 | cold | 4 | 21.523 | 123860 | true | mode=sharded ranks=4 files=4 frames=123860 mpi_s=21.523 serial_s=26.501 mpi_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 serial_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 match=true |
| strong | readcon-db | ingest | sharded | 4 | cold | 5 | 22.145 | 123860 | true | mode=sharded ranks=4 files=4 frames=123860 mpi_s=22.145 serial_s=26.339 mpi_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 serial_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 match=true |
| strong | readcon-db | ingest | sharded | 4 | warm | 1 | 21.158 | 123860 | true | mode=sharded ranks=4 files=4 frames=123860 mpi_s=21.158 serial_s=26.700 mpi_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 serial_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 match=true |
| strong | readcon-db | ingest | sharded | 4 | warm | 2 | 21.259 | 123860 | true | mode=sharded ranks=4 files=4 frames=123860 mpi_s=21.259 serial_s=26.642 mpi_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 serial_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 match=true |
| strong | readcon-db | ingest | sharded | 4 | warm | 3 | 21.32 | 123860 | true | mode=sharded ranks=4 files=4 frames=123860 mpi_s=21.320 serial_s=26.703 mpi_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 serial_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 match=true |
| strong | readcon-db | ingest | sharded | 4 | warm | 4 | 24.906 | 123860 | true | mode=sharded ranks=4 files=4 frames=123860 mpi_s=24.906 serial_s=25.313 mpi_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 serial_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 match=true |
| strong | readcon-db | ingest | sharded | 4 | warm | 5 | 20.199 | 123860 | true | mode=sharded ranks=4 files=4 frames=123860 mpi_s=20.199 serial_s=24.983 mpi_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 serial_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 match=true |
| strong | readcon-db | ingest | sharded | 8 | cold | 1 | 23.929 | 123860 | true | mode=sharded ranks=8 files=4 frames=123860 mpi_s=23.929 serial_s=27.018 mpi_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 serial_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 match=true |
| strong | readcon-db | ingest | sharded | 8 | cold | 2 | 19.108 | 123860 | true | mode=sharded ranks=8 files=4 frames=123860 mpi_s=19.108 serial_s=27.306 mpi_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 serial_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 match=true |
| strong | readcon-db | ingest | sharded | 8 | cold | 3 | 19.078 | 123860 | true | mode=sharded ranks=8 files=4 frames=123860 mpi_s=19.078 serial_s=27.197 mpi_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 serial_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 match=true |
| strong | readcon-db | ingest | sharded | 8 | cold | 4 | 18.912 | 123860 | true | mode=sharded ranks=8 files=4 frames=123860 mpi_s=18.912 serial_s=27.082 mpi_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 serial_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 match=true |
| strong | readcon-db | ingest | sharded | 8 | cold | 5 | 19.005 | 123860 | true | mode=sharded ranks=8 files=4 frames=123860 mpi_s=19.005 serial_s=27.178 mpi_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 serial_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 match=true |
| strong | readcon-db | ingest | sharded | 8 | warm | 1 | 18.805 | 123860 | true | mode=sharded ranks=8 files=4 frames=123860 mpi_s=18.805 serial_s=27.325 mpi_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 serial_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 match=true |
| strong | readcon-db | ingest | sharded | 8 | warm | 2 | 18.879 | 123860 | true | mode=sharded ranks=8 files=4 frames=123860 mpi_s=18.879 serial_s=27.160 mpi_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 serial_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 match=true |
| strong | readcon-db | ingest | sharded | 8 | warm | 3 | 18.644 | 123860 | true | mode=sharded ranks=8 files=4 frames=123860 mpi_s=18.644 serial_s=27.057 mpi_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 serial_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 match=true |
| strong | readcon-db | ingest | sharded | 8 | warm | 4 | 18.749 | 123860 | true | mode=sharded ranks=8 files=4 frames=123860 mpi_s=18.749 serial_s=27.231 mpi_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 serial_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 match=true |
| strong | readcon-db | ingest | sharded | 8 | warm | 5 | 18.84 | 123860 | true | mode=sharded ranks=8 files=4 frames=123860 mpi_s=18.840 serial_s=27.068 mpi_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 serial_sha256=2b5448c859a26f3a622033b091bb57556ec72ba3a89d5fe52878eb52332ce100 match=true |
| strong | readcon-db | ingest | single | 1 | cold | 1 | 34.367 | 123860 | true | mode=single ranks=1 files=4 frames=123860 mpi_s=34.367 serial_s=24.318 mpi_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d serial_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d match=true |
| strong | readcon-db | ingest | single | 1 | cold | 2 | 33.552 | 123860 | true | mode=single ranks=1 files=4 frames=123860 mpi_s=33.552 serial_s=24.002 mpi_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d serial_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d match=true |
| strong | readcon-db | ingest | single | 1 | cold | 3 | 32.237 | 123860 | true | mode=single ranks=1 files=4 frames=123860 mpi_s=32.237 serial_s=23.775 mpi_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d serial_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d match=true |
| strong | readcon-db | ingest | single | 1 | cold | 4 | 33.875 | 123860 | true | mode=single ranks=1 files=4 frames=123860 mpi_s=33.875 serial_s=23.786 mpi_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d serial_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d match=true |
| strong | readcon-db | ingest | single | 1 | cold | 5 | 31.287 | 123860 | true | mode=single ranks=1 files=4 frames=123860 mpi_s=31.287 serial_s=23.258 mpi_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d serial_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d match=true |
| strong | readcon-db | ingest | single | 1 | warm | 1 | 30.957 | 123860 | true | mode=single ranks=1 files=4 frames=123860 mpi_s=30.957 serial_s=23.473 mpi_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d serial_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d match=true |
| strong | readcon-db | ingest | single | 1 | warm | 2 | 33.595 | 123860 | true | mode=single ranks=1 files=4 frames=123860 mpi_s=33.595 serial_s=24.434 mpi_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d serial_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d match=true |
| strong | readcon-db | ingest | single | 1 | warm | 3 | 31.699 | 123860 | true | mode=single ranks=1 files=4 frames=123860 mpi_s=31.699 serial_s=33.611 mpi_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d serial_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d match=true |
| strong | readcon-db | ingest | single | 1 | warm | 4 | 36.466 | 123860 | true | mode=single ranks=1 files=4 frames=123860 mpi_s=36.466 serial_s=22.199 mpi_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d serial_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d match=true |
| strong | readcon-db | ingest | single | 1 | warm | 5 | 30.861 | 123860 | true | mode=single ranks=1 files=4 frames=123860 mpi_s=30.861 serial_s=22.482 mpi_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d serial_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d match=true |
| strong | readcon-db | ingest | single | 2 | cold | 1 | 25.86 | 123860 | true | mode=single ranks=2 files=4 frames=123860 mpi_s=25.860 serial_s=23.559 mpi_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d serial_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d match=true |
| strong | readcon-db | ingest | single | 2 | cold | 2 | 23.934 | 123860 | true | mode=single ranks=2 files=4 frames=123860 mpi_s=23.934 serial_s=22.990 mpi_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d serial_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d match=true |
| strong | readcon-db | ingest | single | 2 | cold | 3 | 24.208 | 123860 | true | mode=single ranks=2 files=4 frames=123860 mpi_s=24.208 serial_s=22.627 mpi_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d serial_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d match=true |
| strong | readcon-db | ingest | single | 2 | cold | 4 | 24.051 | 123860 | true | mode=single ranks=2 files=4 frames=123860 mpi_s=24.051 serial_s=24.475 mpi_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d serial_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d match=true |
| strong | readcon-db | ingest | single | 2 | cold | 5 | 24.384 | 123860 | true | mode=single ranks=2 files=4 frames=123860 mpi_s=24.384 serial_s=23.241 mpi_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d serial_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d match=true |
| strong | readcon-db | ingest | single | 2 | warm | 1 | 23.319 | 123860 | true | mode=single ranks=2 files=4 frames=123860 mpi_s=23.319 serial_s=22.798 mpi_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d serial_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d match=true |
| strong | readcon-db | ingest | single | 2 | warm | 2 | 23.297 | 123860 | true | mode=single ranks=2 files=4 frames=123860 mpi_s=23.297 serial_s=22.623 mpi_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d serial_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d match=true |
| strong | readcon-db | ingest | single | 2 | warm | 3 | 23.141 | 123860 | true | mode=single ranks=2 files=4 frames=123860 mpi_s=23.141 serial_s=22.829 mpi_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d serial_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d match=true |
| strong | readcon-db | ingest | single | 2 | warm | 4 | 23.703 | 123860 | true | mode=single ranks=2 files=4 frames=123860 mpi_s=23.703 serial_s=22.860 mpi_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d serial_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d match=true |
| strong | readcon-db | ingest | single | 2 | warm | 5 | 23.305 | 123860 | true | mode=single ranks=2 files=4 frames=123860 mpi_s=23.305 serial_s=22.676 mpi_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d serial_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d match=true |
| strong | readcon-db | ingest | single | 4 | cold | 1 | 19.77 | 123860 | true | mode=single ranks=4 files=4 frames=123860 mpi_s=19.770 serial_s=23.794 mpi_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d serial_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d match=true |
| strong | readcon-db | ingest | single | 4 | cold | 2 | 19.76 | 123860 | true | mode=single ranks=4 files=4 frames=123860 mpi_s=19.760 serial_s=23.767 mpi_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d serial_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d match=true |
| strong | readcon-db | ingest | single | 4 | cold | 3 | 19.195 | 123860 | true | mode=single ranks=4 files=4 frames=123860 mpi_s=19.195 serial_s=23.458 mpi_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d serial_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d match=true |
| strong | readcon-db | ingest | single | 4 | cold | 4 | 19.666 | 123860 | true | mode=single ranks=4 files=4 frames=123860 mpi_s=19.666 serial_s=23.770 mpi_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d serial_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d match=true |
| strong | readcon-db | ingest | single | 4 | cold | 5 | 28.385 | 123860 | true | mode=single ranks=4 files=4 frames=123860 mpi_s=28.385 serial_s=24.321 mpi_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d serial_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d match=true |
| strong | readcon-db | ingest | single | 4 | warm | 1 | 19.215 | 123860 | true | mode=single ranks=4 files=4 frames=123860 mpi_s=19.215 serial_s=22.220 mpi_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d serial_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d match=true |
| strong | readcon-db | ingest | single | 4 | warm | 2 | 19.322 | 123860 | true | mode=single ranks=4 files=4 frames=123860 mpi_s=19.322 serial_s=23.439 mpi_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d serial_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d match=true |
| strong | readcon-db | ingest | single | 4 | warm | 3 | 19.316 | 123860 | true | mode=single ranks=4 files=4 frames=123860 mpi_s=19.316 serial_s=23.566 mpi_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d serial_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d match=true |
| strong | readcon-db | ingest | single | 4 | warm | 4 | 19.486 | 123860 | true | mode=single ranks=4 files=4 frames=123860 mpi_s=19.486 serial_s=23.979 mpi_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d serial_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d match=true |
| strong | readcon-db | ingest | single | 4 | warm | 5 | 19.764 | 123860 | true | mode=single ranks=4 files=4 frames=123860 mpi_s=19.764 serial_s=23.738 mpi_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d serial_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d match=true |
| strong | readcon-db | ingest | single | 8 | cold | 1 | 21.784 | 123860 | true | mode=single ranks=8 files=4 frames=123860 mpi_s=21.784 serial_s=23.857 mpi_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d serial_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d match=true |
| strong | readcon-db | ingest | single | 8 | cold | 2 | 18.635 | 123860 | true | mode=single ranks=8 files=4 frames=123860 mpi_s=18.635 serial_s=24.614 mpi_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d serial_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d match=true |
| strong | readcon-db | ingest | single | 8 | cold | 3 | 18.133 | 123860 | true | mode=single ranks=8 files=4 frames=123860 mpi_s=18.133 serial_s=23.893 mpi_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d serial_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d match=true |
| strong | readcon-db | ingest | single | 8 | cold | 4 | 17.585 | 123860 | true | mode=single ranks=8 files=4 frames=123860 mpi_s=17.585 serial_s=23.643 mpi_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d serial_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d match=true |
| strong | readcon-db | ingest | single | 8 | cold | 5 | 17.182 | 123860 | true | mode=single ranks=8 files=4 frames=123860 mpi_s=17.182 serial_s=23.632 mpi_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d serial_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d match=true |
| strong | readcon-db | ingest | single | 8 | warm | 1 | 17.053 | 123860 | true | mode=single ranks=8 files=4 frames=123860 mpi_s=17.053 serial_s=23.928 mpi_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d serial_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d match=true |
| strong | readcon-db | ingest | single | 8 | warm | 2 | 16.663 | 123860 | true | mode=single ranks=8 files=4 frames=123860 mpi_s=16.663 serial_s=23.899 mpi_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d serial_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d match=true |
| strong | readcon-db | ingest | single | 8 | warm | 3 | 17.33 | 123860 | true | mode=single ranks=8 files=4 frames=123860 mpi_s=17.330 serial_s=23.898 mpi_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d serial_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d match=true |
| strong | readcon-db | ingest | single | 8 | warm | 4 | 16.8 | 123860 | true | mode=single ranks=8 files=4 frames=123860 mpi_s=16.800 serial_s=23.788 mpi_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d serial_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d match=true |
| strong | readcon-db | ingest | single | 8 | warm | 5 | 16.81 | 123860 | true | mode=single ranks=8 files=4 frames=123860 mpi_s=16.810 serial_s=23.652 mpi_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d serial_sha256=e0b327dd47c115656d4c743238b4b5a0d4a0ec2f9ce74c9746f4aa5017d97e3d match=true |
| weak | readcon-core | read | scatter | 1 | cold | 1 | 1.2866 | 400000 | true | ranks=1 mode=scatter frames=400000 distributed_ms=1286.6 serial_ms=1361.7 identical=true |
| weak | readcon-core | read | scatter | 1 | cold | 2 | 1.3205 | 400000 | true | ranks=1 mode=scatter frames=400000 distributed_ms=1320.5 serial_ms=1289.2 identical=true |
| weak | readcon-core | read | scatter | 1 | cold | 3 | 1.3137999999999999 | 400000 | true | ranks=1 mode=scatter frames=400000 distributed_ms=1313.8 serial_ms=1297.9 identical=true |
| weak | readcon-core | read | scatter | 1 | cold | 4 | 1.2488 | 400000 | true | ranks=1 mode=scatter frames=400000 distributed_ms=1248.8 serial_ms=1347.7 identical=true |
| weak | readcon-core | read | scatter | 1 | cold | 5 | 1.3222 | 400000 | true | ranks=1 mode=scatter frames=400000 distributed_ms=1322.2 serial_ms=1274.3 identical=true |
| weak | readcon-core | read | scatter | 1 | warm | 1 | 1.2346 | 400000 | true | ranks=1 mode=scatter frames=400000 distributed_ms=1234.6 serial_ms=1313.6 identical=true |
| weak | readcon-core | read | scatter | 1 | warm | 2 | 1.1689 | 400000 | true | ranks=1 mode=scatter frames=400000 distributed_ms=1168.9 serial_ms=1355.3 identical=true |
| weak | readcon-core | read | scatter | 1 | warm | 3 | 1.218 | 400000 | true | ranks=1 mode=scatter frames=400000 distributed_ms=1218.0 serial_ms=1323.1 identical=true |
| weak | readcon-core | read | scatter | 1 | warm | 4 | 1.1719000000000002 | 400000 | true | ranks=1 mode=scatter frames=400000 distributed_ms=1171.9 serial_ms=1345.8 identical=true |
| weak | readcon-core | read | scatter | 1 | warm | 5 | 1.2424000000000002 | 400000 | true | ranks=1 mode=scatter frames=400000 distributed_ms=1242.4 serial_ms=1278.0 identical=true |
| weak | readcon-core | read | scatter | 2 | cold | 1 | 1.4864000000000002 | 800000 | true | ranks=2 mode=scatter frames=800000 distributed_ms=1486.4 serial_ms=2556.9 identical=true |
| weak | readcon-core | read | scatter | 2 | cold | 2 | 1.5 | 800000 | true | ranks=2 mode=scatter frames=800000 distributed_ms=1500.0 serial_ms=2512.3 identical=true |
| weak | readcon-core | read | scatter | 2 | cold | 3 | 1.5138 | 800000 | true | ranks=2 mode=scatter frames=800000 distributed_ms=1513.8 serial_ms=2548.5 identical=true |
| weak | readcon-core | read | scatter | 2 | cold | 4 | 1.4790999999999999 | 800000 | true | ranks=2 mode=scatter frames=800000 distributed_ms=1479.1 serial_ms=2511.9 identical=true |
| weak | readcon-core | read | scatter | 2 | cold | 5 | 1.4305999999999999 | 800000 | true | ranks=2 mode=scatter frames=800000 distributed_ms=1430.6 serial_ms=2515.5 identical=true |
| weak | readcon-core | read | scatter | 2 | warm | 1 | 1.382 | 800000 | true | ranks=2 mode=scatter frames=800000 distributed_ms=1382.0 serial_ms=2557.8 identical=true |
| weak | readcon-core | read | scatter | 2 | warm | 2 | 1.2778 | 800000 | true | ranks=2 mode=scatter frames=800000 distributed_ms=1277.8 serial_ms=2504.9 identical=true |
| weak | readcon-core | read | scatter | 2 | warm | 3 | 1.2772999999999999 | 800000 | true | ranks=2 mode=scatter frames=800000 distributed_ms=1277.3 serial_ms=2567.2 identical=true |
| weak | readcon-core | read | scatter | 2 | warm | 4 | 1.3755 | 800000 | true | ranks=2 mode=scatter frames=800000 distributed_ms=1375.5 serial_ms=2519.2 identical=true |
| weak | readcon-core | read | scatter | 2 | warm | 5 | 1.2778 | 800000 | true | ranks=2 mode=scatter frames=800000 distributed_ms=1277.8 serial_ms=2521.7 identical=true |
| weak | readcon-core | read | scatter | 4 | cold | 1 | 1.7939 | 1600000 | true | ranks=4 mode=scatter frames=1600000 distributed_ms=1793.9 serial_ms=4987.6 identical=true |
| weak | readcon-core | read | scatter | 4 | cold | 2 | 1.8548 | 1600000 | true | ranks=4 mode=scatter frames=1600000 distributed_ms=1854.8 serial_ms=4953.5 identical=true |
| weak | readcon-core | read | scatter | 4 | cold | 3 | 1.8335 | 1600000 | true | ranks=4 mode=scatter frames=1600000 distributed_ms=1833.5 serial_ms=4985.7 identical=true |
| weak | readcon-core | read | scatter | 4 | cold | 4 | 1.8242 | 1600000 | true | ranks=4 mode=scatter frames=1600000 distributed_ms=1824.2 serial_ms=5136.8 identical=true |
| weak | readcon-core | read | scatter | 4 | cold | 5 | 1.799 | 1600000 | true | ranks=4 mode=scatter frames=1600000 distributed_ms=1799.0 serial_ms=5079.6 identical=true |
| weak | readcon-core | read | scatter | 4 | warm | 1 | 1.5609000000000002 | 1600000 | true | ranks=4 mode=scatter frames=1600000 distributed_ms=1560.9 serial_ms=4980.3 identical=true |
| weak | readcon-core | read | scatter | 4 | warm | 2 | 1.5342 | 1600000 | true | ranks=4 mode=scatter frames=1600000 distributed_ms=1534.2 serial_ms=4990.5 identical=true |
| weak | readcon-core | read | scatter | 4 | warm | 3 | 1.4829 | 1600000 | true | ranks=4 mode=scatter frames=1600000 distributed_ms=1482.9 serial_ms=4967.0 identical=true |
| weak | readcon-core | read | scatter | 4 | warm | 4 | 1.478 | 1600000 | true | ranks=4 mode=scatter frames=1600000 distributed_ms=1478.0 serial_ms=4961.1 identical=true |
| weak | readcon-core | read | scatter | 4 | warm | 5 | 1.5246 | 1600000 | true | ranks=4 mode=scatter frames=1600000 distributed_ms=1524.6 serial_ms=17529.1 identical=true |
| weak | readcon-core | read | scatter | 8 | cold | 1 | 7.1933 | 3200000 | true | ranks=8 mode=scatter frames=3200000 distributed_ms=7193.3 serial_ms=13487.0 identical=true |
| weak | readcon-core | read | scatter | 8 | cold | 2 | 2.545 | 3200000 | true | ranks=8 mode=scatter frames=3200000 distributed_ms=2545.0 serial_ms=12986.1 identical=true |
| weak | readcon-core | read | scatter | 8 | cold | 3 | 2.5412 | 3200000 | true | ranks=8 mode=scatter frames=3200000 distributed_ms=2541.2 serial_ms=12439.3 identical=true |
| weak | readcon-core | read | scatter | 8 | cold | 4 | 2.6279 | 3200000 | true | ranks=8 mode=scatter frames=3200000 distributed_ms=2627.9 serial_ms=12907.1 identical=true |
| weak | readcon-core | read | scatter | 8 | cold | 5 | 2.8374 | 3200000 | true | ranks=8 mode=scatter frames=3200000 distributed_ms=2837.4 serial_ms=11690.6 identical=true |
| weak | readcon-core | read | scatter | 8 | warm | 1 | 1.9485999999999999 | 3200000 | true | ranks=8 mode=scatter frames=3200000 distributed_ms=1948.6 serial_ms=12030.1 identical=true |
| weak | readcon-core | read | scatter | 8 | warm | 2 | 2.264 | 3200000 | true | ranks=8 mode=scatter frames=3200000 distributed_ms=2264.0 serial_ms=11656.4 identical=true |
| weak | readcon-core | read | scatter | 8 | warm | 3 | 2.1688 | 3200000 | true | ranks=8 mode=scatter frames=3200000 distributed_ms=2168.8 serial_ms=11947.6 identical=true |
| weak | readcon-core | read | scatter | 8 | warm | 4 | 1.9487 | 3200000 | true | ranks=8 mode=scatter frames=3200000 distributed_ms=1948.7 serial_ms=11889.5 identical=true |
| weak | readcon-core | read | scatter | 8 | warm | 5 | 1.9617 | 3200000 | true | ranks=8 mode=scatter frames=3200000 distributed_ms=1961.7 serial_ms=12203.2 identical=true |
| weak | readcon-core | read | shared | 1 | cold | 1 | 1.5448 | 400000 | true | ranks=1 mode=shared frames=400000 distributed_ms=1544.8 serial_ms=1337.4 identical=true |
| weak | readcon-core | read | shared | 1 | cold | 2 | 1.1982000000000002 | 400000 | true | ranks=1 mode=shared frames=400000 distributed_ms=1198.2 serial_ms=1271.8 identical=true |
| weak | readcon-core | read | shared | 1 | cold | 3 | 1.2506 | 400000 | true | ranks=1 mode=shared frames=400000 distributed_ms=1250.6 serial_ms=1345.6 identical=true |
| weak | readcon-core | read | shared | 1 | cold | 4 | 1.2437 | 400000 | true | ranks=1 mode=shared frames=400000 distributed_ms=1243.7 serial_ms=1319.1 identical=true |
| weak | readcon-core | read | shared | 1 | cold | 5 | 1.2425 | 400000 | true | ranks=1 mode=shared frames=400000 distributed_ms=1242.5 serial_ms=1322.1 identical=true |
| weak | readcon-core | read | shared | 1 | warm | 1 | 1.1584 | 400000 | true | ranks=1 mode=shared frames=400000 distributed_ms=1158.4 serial_ms=1329.0 identical=true |
| weak | readcon-core | read | shared | 1 | warm | 2 | 1.1889 | 400000 | true | ranks=1 mode=shared frames=400000 distributed_ms=1188.9 serial_ms=1321.2 identical=true |
| weak | readcon-core | read | shared | 1 | warm | 3 | 1.1718 | 400000 | true | ranks=1 mode=shared frames=400000 distributed_ms=1171.8 serial_ms=1328.2 identical=true |
| weak | readcon-core | read | shared | 1 | warm | 4 | 1.161 | 400000 | true | ranks=1 mode=shared frames=400000 distributed_ms=1161.0 serial_ms=1309.0 identical=true |
| weak | readcon-core | read | shared | 1 | warm | 5 | 1.1489 | 400000 | true | ranks=1 mode=shared frames=400000 distributed_ms=1148.9 serial_ms=1258.8 identical=true |
| weak | readcon-core | read | shared | 2 | cold | 1 | 2.0205 | 800000 | true | ranks=2 mode=shared frames=800000 distributed_ms=2020.5 serial_ms=2580.1 identical=true |
| weak | readcon-core | read | shared | 2 | cold | 2 | 1.3954000000000002 | 800000 | true | ranks=2 mode=shared frames=800000 distributed_ms=1395.4 serial_ms=2561.9 identical=true |
| weak | readcon-core | read | shared | 2 | cold | 3 | 1.3235 | 800000 | true | ranks=2 mode=shared frames=800000 distributed_ms=1323.5 serial_ms=2538.0 identical=true |
| weak | readcon-core | read | shared | 2 | cold | 4 | 1.3917 | 800000 | true | ranks=2 mode=shared frames=800000 distributed_ms=1391.7 serial_ms=2536.3 identical=true |
| weak | readcon-core | read | shared | 2 | cold | 5 | 1.3912 | 800000 | true | ranks=2 mode=shared frames=800000 distributed_ms=1391.2 serial_ms=2542.8 identical=true |
| weak | readcon-core | read | shared | 2 | warm | 1 | 1.2012 | 800000 | true | ranks=2 mode=shared frames=800000 distributed_ms=1201.2 serial_ms=2524.8 identical=true |
| weak | readcon-core | read | shared | 2 | warm | 2 | 1.2312 | 800000 | true | ranks=2 mode=shared frames=800000 distributed_ms=1231.2 serial_ms=2582.3 identical=true |
| weak | readcon-core | read | shared | 2 | warm | 3 | 1.2083 | 800000 | true | ranks=2 mode=shared frames=800000 distributed_ms=1208.3 serial_ms=2550.3 identical=true |
| weak | readcon-core | read | shared | 2 | warm | 4 | 1.1653 | 800000 | true | ranks=2 mode=shared frames=800000 distributed_ms=1165.3 serial_ms=2530.1 identical=true |
| weak | readcon-core | read | shared | 2 | warm | 5 | 1.2347000000000001 | 800000 | true | ranks=2 mode=shared frames=800000 distributed_ms=1234.7 serial_ms=2542.0 identical=true |
| weak | readcon-core | read | shared | 4 | cold | 1 | 2.7124 | 1600000 | true | ranks=4 mode=shared frames=1600000 distributed_ms=2712.4 serial_ms=5935.6 identical=true |
| weak | readcon-core | read | shared | 4 | cold | 2 | 1.655 | 1600000 | true | ranks=4 mode=shared frames=1600000 distributed_ms=1655.0 serial_ms=5885.0 identical=true |
| weak | readcon-core | read | shared | 4 | cold | 3 | 1.6127 | 1600000 | true | ranks=4 mode=shared frames=1600000 distributed_ms=1612.7 serial_ms=5865.1 identical=true |
| weak | readcon-core | read | shared | 4 | cold | 4 | 1.6772 | 1600000 | true | ranks=4 mode=shared frames=1600000 distributed_ms=1677.2 serial_ms=5793.2 identical=true |
| weak | readcon-core | read | shared | 4 | cold | 5 | 1.6681 | 1600000 | true | ranks=4 mode=shared frames=1600000 distributed_ms=1668.1 serial_ms=5428.9 identical=true |
| weak | readcon-core | read | shared | 4 | warm | 1 | 1.3545999999999998 | 1600000 | true | ranks=4 mode=shared frames=1600000 distributed_ms=1354.6 serial_ms=5481.8 identical=true |
| weak | readcon-core | read | shared | 4 | warm | 2 | 1.3622 | 1600000 | true | ranks=4 mode=shared frames=1600000 distributed_ms=1362.2 serial_ms=5766.1 identical=true |
| weak | readcon-core | read | shared | 4 | warm | 3 | 1.311 | 1600000 | true | ranks=4 mode=shared frames=1600000 distributed_ms=1311.0 serial_ms=5826.8 identical=true |
| weak | readcon-core | read | shared | 4 | warm | 4 | 1.3662999999999998 | 1600000 | true | ranks=4 mode=shared frames=1600000 distributed_ms=1366.3 serial_ms=5877.1 identical=true |
| weak | readcon-core | read | shared | 4 | warm | 5 | 1.3147 | 1600000 | true | ranks=4 mode=shared frames=1600000 distributed_ms=1314.7 serial_ms=5925.8 identical=true |
| weak | readcon-core | read | shared | 8 | cold | 1 | 4.2726999999999995 | 3200000 | true | ranks=8 mode=shared frames=3200000 distributed_ms=4272.7 serial_ms=13873.3 identical=true |
| weak | readcon-core | read | shared | 8 | cold | 2 | 2.1828000000000003 | 3200000 | true | ranks=8 mode=shared frames=3200000 distributed_ms=2182.8 serial_ms=12772.3 identical=true |
| weak | readcon-core | read | shared | 8 | cold | 3 | 2.3858 | 3200000 | true | ranks=8 mode=shared frames=3200000 distributed_ms=2385.8 serial_ms=11464.7 identical=true |
| weak | readcon-core | read | shared | 8 | cold | 4 | 2.1866 | 3200000 | true | ranks=8 mode=shared frames=3200000 distributed_ms=2186.6 serial_ms=12636.0 identical=true |
| weak | readcon-core | read | shared | 8 | cold | 5 | 2.1712 | 3200000 | true | ranks=8 mode=shared frames=3200000 distributed_ms=2171.2 serial_ms=12123.6 identical=true |
| weak | readcon-core | read | shared | 8 | warm | 1 | 1.5727 | 3200000 | true | ranks=8 mode=shared frames=3200000 distributed_ms=1572.7 serial_ms=11752.3 identical=true |
| weak | readcon-core | read | shared | 8 | warm | 2 | 1.6777 | 3200000 | true | ranks=8 mode=shared frames=3200000 distributed_ms=1677.7 serial_ms=12656.1 identical=true |
| weak | readcon-core | read | shared | 8 | warm | 3 | 1.7924 | 3200000 | true | ranks=8 mode=shared frames=3200000 distributed_ms=1792.4 serial_ms=12335.2 identical=true |
| weak | readcon-core | read | shared | 8 | warm | 4 | 1.5815 | 3200000 | true | ranks=8 mode=shared frames=3200000 distributed_ms=1581.5 serial_ms=12482.5 identical=true |
| weak | readcon-core | read | shared | 8 | warm | 5 | 1.5811 | 3200000 | true | ranks=8 mode=shared frames=3200000 distributed_ms=1581.1 serial_ms=12678.1 identical=true |
| weak | readcon-core | write | gather | 1 | cold | 1 | 1.2150999999999998 | 400000 | true | ranks=1 mode=gather frames=400000 bytes=118000000 write_ms=1215.1 serial_write_ms=767.2 identical=true sidecar_ok=true |
| weak | readcon-core | write | gather | 1 | cold | 2 | 1.213 | 400000 | true | ranks=1 mode=gather frames=400000 bytes=118000000 write_ms=1213.0 serial_write_ms=1197.7 identical=true sidecar_ok=true |
| weak | readcon-core | write | gather | 1 | cold | 3 | 1.238 | 400000 | true | ranks=1 mode=gather frames=400000 bytes=118000000 write_ms=1238.0 serial_write_ms=782.5 identical=true sidecar_ok=true |
| weak | readcon-core | write | gather | 1 | cold | 4 | 1.2284000000000002 | 400000 | true | ranks=1 mode=gather frames=400000 bytes=118000000 write_ms=1228.4 serial_write_ms=785.5 identical=true sidecar_ok=true |
| weak | readcon-core | write | gather | 1 | cold | 5 | 1.248 | 400000 | true | ranks=1 mode=gather frames=400000 bytes=118000000 write_ms=1248.0 serial_write_ms=791.7 identical=true sidecar_ok=true |
| weak | readcon-core | write | gather | 1 | warm | 1 | 1.2113 | 400000 | true | ranks=1 mode=gather frames=400000 bytes=118000000 write_ms=1211.3 serial_write_ms=768.1 identical=true sidecar_ok=true |
| weak | readcon-core | write | gather | 1 | warm | 2 | 1.2129 | 400000 | true | ranks=1 mode=gather frames=400000 bytes=118000000 write_ms=1212.9 serial_write_ms=766.8 identical=true sidecar_ok=true |
| weak | readcon-core | write | gather | 1 | warm | 3 | 1.2382 | 400000 | true | ranks=1 mode=gather frames=400000 bytes=118000000 write_ms=1238.2 serial_write_ms=776.4 identical=true sidecar_ok=true |
| weak | readcon-core | write | gather | 1 | warm | 4 | 1.1644 | 400000 | true | ranks=1 mode=gather frames=400000 bytes=118000000 write_ms=1164.4 serial_write_ms=767.1 identical=true sidecar_ok=true |
| weak | readcon-core | write | gather | 1 | warm | 5 | 1.2106 | 400000 | true | ranks=1 mode=gather frames=400000 bytes=118000000 write_ms=1210.6 serial_write_ms=3047.0 identical=true sidecar_ok=true |
| weak | readcon-core | write | gather | 2 | cold | 1 | 1.5437 | 800000 | true | ranks=2 mode=gather frames=800000 bytes=236000000 write_ms=1543.7 serial_write_ms=1522.0 identical=true sidecar_ok=true |
| weak | readcon-core | write | gather | 2 | cold | 2 | 1.4119000000000002 | 800000 | true | ranks=2 mode=gather frames=800000 bytes=236000000 write_ms=1411.9 serial_write_ms=1544.3 identical=true sidecar_ok=true |
| weak | readcon-core | write | gather | 2 | cold | 3 | 1.2470999999999999 | 800000 | true | ranks=2 mode=gather frames=800000 bytes=236000000 write_ms=1247.1 serial_write_ms=1527.1 identical=true sidecar_ok=true |
| weak | readcon-core | write | gather | 2 | cold | 4 | 1.2646 | 800000 | true | ranks=2 mode=gather frames=800000 bytes=236000000 write_ms=1264.6 serial_write_ms=1516.1 identical=true sidecar_ok=true |
| weak | readcon-core | write | gather | 2 | cold | 5 | 1.42 | 800000 | true | ranks=2 mode=gather frames=800000 bytes=236000000 write_ms=1420.0 serial_write_ms=1517.5 identical=true sidecar_ok=true |
| weak | readcon-core | write | gather | 2 | warm | 1 | 1.3155999999999999 | 800000 | true | ranks=2 mode=gather frames=800000 bytes=236000000 write_ms=1315.6 serial_write_ms=1518.5 identical=true sidecar_ok=true |
| weak | readcon-core | write | gather | 2 | warm | 2 | 1.3175 | 800000 | true | ranks=2 mode=gather frames=800000 bytes=236000000 write_ms=1317.5 serial_write_ms=1515.6 identical=true sidecar_ok=true |
| weak | readcon-core | write | gather | 2 | warm | 3 | 1.3092000000000001 | 800000 | true | ranks=2 mode=gather frames=800000 bytes=236000000 write_ms=1309.2 serial_write_ms=2359.8 identical=true sidecar_ok=true |
| weak | readcon-core | write | gather | 2 | warm | 4 | 1.3195999999999999 | 800000 | true | ranks=2 mode=gather frames=800000 bytes=236000000 write_ms=1319.6 serial_write_ms=1520.1 identical=true sidecar_ok=true |
| weak | readcon-core | write | gather | 2 | warm | 5 | 1.3219 | 800000 | true | ranks=2 mode=gather frames=800000 bytes=236000000 write_ms=1321.9 serial_write_ms=1517.1 identical=true sidecar_ok=true |
| weak | readcon-core | write | gather | 4 | cold | 1 | 1.9459000000000002 | 1600000 | true | ranks=4 mode=gather frames=1600000 bytes=472000000 write_ms=1945.9 serial_write_ms=6111.6 identical=true sidecar_ok=true |
| weak | readcon-core | write | gather | 4 | cold | 2 | 1.5121 | 1600000 | true | ranks=4 mode=gather frames=1600000 bytes=472000000 write_ms=1512.1 serial_write_ms=3026.2 identical=true sidecar_ok=true |
| weak | readcon-core | write | gather | 4 | cold | 3 | 1.549 | 1600000 | true | ranks=4 mode=gather frames=1600000 bytes=472000000 write_ms=1549.0 serial_write_ms=3027.0 identical=true sidecar_ok=true |
| weak | readcon-core | write | gather | 4 | cold | 4 | 1.5305 | 1600000 | true | ranks=4 mode=gather frames=1600000 bytes=472000000 write_ms=1530.5 serial_write_ms=3029.0 identical=true sidecar_ok=true |
| weak | readcon-core | write | gather | 4 | cold | 5 | 1.5102 | 1600000 | true | ranks=4 mode=gather frames=1600000 bytes=472000000 write_ms=1510.2 serial_write_ms=3035.1 identical=true sidecar_ok=true |
| weak | readcon-core | write | gather | 4 | warm | 1 | 1.5066 | 1600000 | true | ranks=4 mode=gather frames=1600000 bytes=472000000 write_ms=1506.6 serial_write_ms=3016.6 identical=true sidecar_ok=true |
| weak | readcon-core | write | gather | 4 | warm | 2 | 1.5719 | 1600000 | true | ranks=4 mode=gather frames=1600000 bytes=472000000 write_ms=1571.9 serial_write_ms=3038.3 identical=true sidecar_ok=true |
| weak | readcon-core | write | gather | 4 | warm | 3 | 1.5783 | 1600000 | true | ranks=4 mode=gather frames=1600000 bytes=472000000 write_ms=1578.3 serial_write_ms=3213.3 identical=true sidecar_ok=true |
| weak | readcon-core | write | gather | 4 | warm | 4 | 1.5579 | 1600000 | true | ranks=4 mode=gather frames=1600000 bytes=472000000 write_ms=1557.9 serial_write_ms=3980.4 identical=true sidecar_ok=true |
| weak | readcon-core | write | gather | 4 | warm | 5 | 1.6129 | 1600000 | true | ranks=4 mode=gather frames=1600000 bytes=472000000 write_ms=1612.9 serial_write_ms=3019.1 identical=true sidecar_ok=true |
| weak | readcon-core | write | gather | 8 | cold | 1 | 2.6984 | 3200000 | true | ranks=8 mode=gather frames=3200000 bytes=944000000 write_ms=2698.4 serial_write_ms=6304.9 identical=true sidecar_ok=true |
| weak | readcon-core | write | gather | 8 | cold | 2 | 2.0377 | 3200000 | true | ranks=8 mode=gather frames=3200000 bytes=944000000 write_ms=2037.7 serial_write_ms=6176.5 identical=true sidecar_ok=true |
| weak | readcon-core | write | gather | 8 | cold | 3 | 2.6988000000000003 | 3200000 | true | ranks=8 mode=gather frames=3200000 bytes=944000000 write_ms=2698.8 serial_write_ms=6215.3 identical=true sidecar_ok=true |
| weak | readcon-core | write | gather | 8 | cold | 4 | 2.0785 | 3200000 | true | ranks=8 mode=gather frames=3200000 bytes=944000000 write_ms=2078.5 serial_write_ms=6467.9 identical=true sidecar_ok=true |
| weak | readcon-core | write | gather | 8 | cold | 5 | 2.0725 | 3200000 | true | ranks=8 mode=gather frames=3200000 bytes=944000000 write_ms=2072.5 serial_write_ms=6164.5 identical=true sidecar_ok=true |
| weak | readcon-core | write | gather | 8 | warm | 1 | 2.097 | 3200000 | true | ranks=8 mode=gather frames=3200000 bytes=944000000 write_ms=2097.0 serial_write_ms=6070.4 identical=true sidecar_ok=true |
| weak | readcon-core | write | gather | 8 | warm | 2 | 2.1592 | 3200000 | true | ranks=8 mode=gather frames=3200000 bytes=944000000 write_ms=2159.2 serial_write_ms=6086.3 identical=true sidecar_ok=true |
| weak | readcon-core | write | gather | 8 | warm | 3 | 2.2958000000000003 | 3200000 | true | ranks=8 mode=gather frames=3200000 bytes=944000000 write_ms=2295.8 serial_write_ms=6104.3 identical=true sidecar_ok=true |
| weak | readcon-core | write | gather | 8 | warm | 4 | 2.1681 | 3200000 | true | ranks=8 mode=gather frames=3200000 bytes=944000000 write_ms=2168.1 serial_write_ms=6113.7 identical=true sidecar_ok=true |
| weak | readcon-core | write | gather | 8 | warm | 5 | 2.161 | 3200000 | true | ranks=8 mode=gather frames=3200000 bytes=944000000 write_ms=2161.0 serial_write_ms=6073.4 identical=true sidecar_ok=true |
| weak | readcon-core | write | mpiio | 1 | cold | 1 | 1.0624 | 400000 | true | ranks=1 mode=mpiio frames=400000 bytes=118000000 write_ms=1062.4 serial_write_ms=794.4 identical=true sidecar_ok=true |
| weak | readcon-core | write | mpiio | 1 | cold | 2 | 1.0391 | 400000 | true | ranks=1 mode=mpiio frames=400000 bytes=118000000 write_ms=1039.1 serial_write_ms=768.2 identical=true sidecar_ok=true |
| weak | readcon-core | write | mpiio | 1 | cold | 3 | 1.0507 | 400000 | true | ranks=1 mode=mpiio frames=400000 bytes=118000000 write_ms=1050.7 serial_write_ms=783.3 identical=true sidecar_ok=true |
| weak | readcon-core | write | mpiio | 1 | cold | 4 | 1.05 | 400000 | true | ranks=1 mode=mpiio frames=400000 bytes=118000000 write_ms=1050.0 serial_write_ms=778.9 identical=true sidecar_ok=true |
| weak | readcon-core | write | mpiio | 1 | cold | 5 | 1.0506 | 400000 | true | ranks=1 mode=mpiio frames=400000 bytes=118000000 write_ms=1050.6 serial_write_ms=784.0 identical=true sidecar_ok=true |
| weak | readcon-core | write | mpiio | 1 | warm | 1 | 1.0876 | 400000 | true | ranks=1 mode=mpiio frames=400000 bytes=118000000 write_ms=1087.6 serial_write_ms=769.4 identical=true sidecar_ok=true |
| weak | readcon-core | write | mpiio | 1 | warm | 2 | 1.0369000000000002 | 400000 | true | ranks=1 mode=mpiio frames=400000 bytes=118000000 write_ms=1036.9 serial_write_ms=774.2 identical=true sidecar_ok=true |
| weak | readcon-core | write | mpiio | 1 | warm | 3 | 1.0318 | 400000 | true | ranks=1 mode=mpiio frames=400000 bytes=118000000 write_ms=1031.8 serial_write_ms=769.8 identical=true sidecar_ok=true |
| weak | readcon-core | write | mpiio | 1 | warm | 4 | 1.0319 | 400000 | true | ranks=1 mode=mpiio frames=400000 bytes=118000000 write_ms=1031.9 serial_write_ms=767.6 identical=true sidecar_ok=true |
| weak | readcon-core | write | mpiio | 1 | warm | 5 | 1.0407 | 400000 | true | ranks=1 mode=mpiio frames=400000 bytes=118000000 write_ms=1040.7 serial_write_ms=777.1 identical=true sidecar_ok=true |
| weak | readcon-core | write | mpiio | 2 | cold | 1 | 1.0892 | 800000 | true | ranks=2 mode=mpiio frames=800000 bytes=236000000 write_ms=1089.2 serial_write_ms=1538.1 identical=true sidecar_ok=true |
| weak | readcon-core | write | mpiio | 2 | cold | 2 | 1.0914000000000001 | 800000 | true | ranks=2 mode=mpiio frames=800000 bytes=236000000 write_ms=1091.4 serial_write_ms=1532.6 identical=true sidecar_ok=true |
| weak | readcon-core | write | mpiio | 2 | cold | 3 | 1.0797999999999999 | 800000 | true | ranks=2 mode=mpiio frames=800000 bytes=236000000 write_ms=1079.8 serial_write_ms=1537.0 identical=true sidecar_ok=true |
| weak | readcon-core | write | mpiio | 2 | cold | 4 | 1.0963 | 800000 | true | ranks=2 mode=mpiio frames=800000 bytes=236000000 write_ms=1096.3 serial_write_ms=1545.0 identical=true sidecar_ok=true |
| weak | readcon-core | write | mpiio | 2 | cold | 5 | 1.0906 | 800000 | true | ranks=2 mode=mpiio frames=800000 bytes=236000000 write_ms=1090.6 serial_write_ms=1540.5 identical=true sidecar_ok=true |
| weak | readcon-core | write | mpiio | 2 | warm | 1 | 1.0745 | 800000 | true | ranks=2 mode=mpiio frames=800000 bytes=236000000 write_ms=1074.5 serial_write_ms=1582.4 identical=true sidecar_ok=true |
| weak | readcon-core | write | mpiio | 2 | warm | 2 | 1.0816 | 800000 | true | ranks=2 mode=mpiio frames=800000 bytes=236000000 write_ms=1081.6 serial_write_ms=1533.8 identical=true sidecar_ok=true |
| weak | readcon-core | write | mpiio | 2 | warm | 3 | 1.0854000000000001 | 800000 | true | ranks=2 mode=mpiio frames=800000 bytes=236000000 write_ms=1085.4 serial_write_ms=1533.9 identical=true sidecar_ok=true |
| weak | readcon-core | write | mpiio | 2 | warm | 4 | 1.0920999999999998 | 800000 | true | ranks=2 mode=mpiio frames=800000 bytes=236000000 write_ms=1092.1 serial_write_ms=1534.0 identical=true sidecar_ok=true |
| weak | readcon-core | write | mpiio | 2 | warm | 5 | 1.1029 | 800000 | true | ranks=2 mode=mpiio frames=800000 bytes=236000000 write_ms=1102.9 serial_write_ms=1545.9 identical=true sidecar_ok=true |
| weak | readcon-core | write | mpiio | 4 | cold | 1 | 1.1904000000000001 | 1600000 | true | ranks=4 mode=mpiio frames=1600000 bytes=472000000 write_ms=1190.4 serial_write_ms=3074.2 identical=true sidecar_ok=true |
| weak | readcon-core | write | mpiio | 4 | cold | 2 | 1.1885999999999999 | 1600000 | true | ranks=4 mode=mpiio frames=1600000 bytes=472000000 write_ms=1188.6 serial_write_ms=3144.7 identical=true sidecar_ok=true |
| weak | readcon-core | write | mpiio | 4 | cold | 3 | 1.2369 | 1600000 | true | ranks=4 mode=mpiio frames=1600000 bytes=472000000 write_ms=1236.9 serial_write_ms=3069.4 identical=true sidecar_ok=true |
| weak | readcon-core | write | mpiio | 4 | cold | 4 | 1.2009 | 1600000 | true | ranks=4 mode=mpiio frames=1600000 bytes=472000000 write_ms=1200.9 serial_write_ms=3074.0 identical=true sidecar_ok=true |
| weak | readcon-core | write | mpiio | 4 | cold | 5 | 1.2999 | 1600000 | true | ranks=4 mode=mpiio frames=1600000 bytes=472000000 write_ms=1299.9 serial_write_ms=3045.9 identical=true sidecar_ok=true |
| weak | readcon-core | write | mpiio | 4 | warm | 1 | 1.2270999999999999 | 1600000 | true | ranks=4 mode=mpiio frames=1600000 bytes=472000000 write_ms=1227.1 serial_write_ms=3060.7 identical=true sidecar_ok=true |
| weak | readcon-core | write | mpiio | 4 | warm | 2 | 1.2065 | 1600000 | true | ranks=4 mode=mpiio frames=1600000 bytes=472000000 write_ms=1206.5 serial_write_ms=3056.2 identical=true sidecar_ok=true |
| weak | readcon-core | write | mpiio | 4 | warm | 3 | 1.1899000000000002 | 1600000 | true | ranks=4 mode=mpiio frames=1600000 bytes=472000000 write_ms=1189.9 serial_write_ms=3056.9 identical=true sidecar_ok=true |
| weak | readcon-core | write | mpiio | 4 | warm | 4 | 1.1985999999999999 | 1600000 | true | ranks=4 mode=mpiio frames=1600000 bytes=472000000 write_ms=1198.6 serial_write_ms=3056.5 identical=true sidecar_ok=true |
| weak | readcon-core | write | mpiio | 4 | warm | 5 | 1.1937 | 1600000 | true | ranks=4 mode=mpiio frames=1600000 bytes=472000000 write_ms=1193.7 serial_write_ms=3040.4 identical=true sidecar_ok=true |
| weak | readcon-core | write | mpiio | 8 | cold | 1 | 1.7969000000000002 | 3200000 | true | ranks=8 mode=mpiio frames=3200000 bytes=944000000 write_ms=1796.9 serial_write_ms=6132.2 identical=true sidecar_ok=true |
| weak | readcon-core | write | mpiio | 8 | cold | 2 | 1.3672 | 3200000 | true | ranks=8 mode=mpiio frames=3200000 bytes=944000000 write_ms=1367.2 serial_write_ms=6076.2 identical=true sidecar_ok=true |
| weak | readcon-core | write | mpiio | 8 | cold | 3 | 1.3984 | 3200000 | true | ranks=8 mode=mpiio frames=3200000 bytes=944000000 write_ms=1398.4 serial_write_ms=6093.0 identical=true sidecar_ok=true |
| weak | readcon-core | write | mpiio | 8 | cold | 4 | 1.4496 | 3200000 | true | ranks=8 mode=mpiio frames=3200000 bytes=944000000 write_ms=1449.6 serial_write_ms=6091.4 identical=true sidecar_ok=true |
| weak | readcon-core | write | mpiio | 8 | cold | 5 | 1.4361 | 3200000 | true | ranks=8 mode=mpiio frames=3200000 bytes=944000000 write_ms=1436.1 serial_write_ms=6107.5 identical=true sidecar_ok=true |
| weak | readcon-core | write | mpiio | 8 | warm | 1 | 1.4463 | 3200000 | true | ranks=8 mode=mpiio frames=3200000 bytes=944000000 write_ms=1446.3 serial_write_ms=6236.4 identical=true sidecar_ok=true |
| weak | readcon-core | write | mpiio | 8 | warm | 2 | 1.3651 | 3200000 | true | ranks=8 mode=mpiio frames=3200000 bytes=944000000 write_ms=1365.1 serial_write_ms=6106.3 identical=true sidecar_ok=true |
| weak | readcon-core | write | mpiio | 8 | warm | 3 | 1.3805 | 3200000 | true | ranks=8 mode=mpiio frames=3200000 bytes=944000000 write_ms=1380.5 serial_write_ms=6146.0 identical=true sidecar_ok=true |
| weak | readcon-core | write | mpiio | 8 | warm | 4 | 1.3935 | 3200000 | true | ranks=8 mode=mpiio frames=3200000 bytes=944000000 write_ms=1393.5 serial_write_ms=6082.7 identical=true sidecar_ok=true |
| weak | readcon-core | write | mpiio | 8 | warm | 5 | 1.3820999999999999 | 3200000 | true | ranks=8 mode=mpiio frames=3200000 bytes=944000000 write_ms=1382.1 serial_write_ms=6082.0 identical=true sidecar_ok=true |
| weak | readcon-db | ingest | sharded | 1 | cold | 1 | 9.905 | 30800 | true | mode=sharded ranks=1 files=4 frames=30800 mpi_s=9.905 serial_s=6.499 mpi_sha256=3c931e0b34bf245c581a8d1f605eb71bda1cf365dd66f93771fb66eba03a01a4 serial_sha256=3c931e0b34bf245c581a8d1f605eb71bda1cf365dd66f93771fb66eba03a01a4 match=true |
| weak | readcon-db | ingest | sharded | 1 | cold | 2 | 7.771 | 30800 | true | mode=sharded ranks=1 files=4 frames=30800 mpi_s=7.771 serial_s=5.304 mpi_sha256=3c931e0b34bf245c581a8d1f605eb71bda1cf365dd66f93771fb66eba03a01a4 serial_sha256=3c931e0b34bf245c581a8d1f605eb71bda1cf365dd66f93771fb66eba03a01a4 match=true |
| weak | readcon-db | ingest | sharded | 1 | cold | 3 | 7.76 | 30800 | true | mode=sharded ranks=1 files=4 frames=30800 mpi_s=7.760 serial_s=5.209 mpi_sha256=3c931e0b34bf245c581a8d1f605eb71bda1cf365dd66f93771fb66eba03a01a4 serial_sha256=3c931e0b34bf245c581a8d1f605eb71bda1cf365dd66f93771fb66eba03a01a4 match=true |
| weak | readcon-db | ingest | sharded | 1 | cold | 4 | 7.627 | 30800 | true | mode=sharded ranks=1 files=4 frames=30800 mpi_s=7.627 serial_s=5.453 mpi_sha256=3c931e0b34bf245c581a8d1f605eb71bda1cf365dd66f93771fb66eba03a01a4 serial_sha256=3c931e0b34bf245c581a8d1f605eb71bda1cf365dd66f93771fb66eba03a01a4 match=true |
| weak | readcon-db | ingest | sharded | 1 | cold | 5 | 7.589 | 30800 | true | mode=sharded ranks=1 files=4 frames=30800 mpi_s=7.589 serial_s=4.999 mpi_sha256=3c931e0b34bf245c581a8d1f605eb71bda1cf365dd66f93771fb66eba03a01a4 serial_sha256=3c931e0b34bf245c581a8d1f605eb71bda1cf365dd66f93771fb66eba03a01a4 match=true |
| weak | readcon-db | ingest | sharded | 1 | warm | 1 | 7.497 | 30800 | true | mode=sharded ranks=1 files=4 frames=30800 mpi_s=7.497 serial_s=5.032 mpi_sha256=3c931e0b34bf245c581a8d1f605eb71bda1cf365dd66f93771fb66eba03a01a4 serial_sha256=3c931e0b34bf245c581a8d1f605eb71bda1cf365dd66f93771fb66eba03a01a4 match=true |
| weak | readcon-db | ingest | sharded | 1 | warm | 2 | 7.452 | 30800 | true | mode=sharded ranks=1 files=4 frames=30800 mpi_s=7.452 serial_s=4.930 mpi_sha256=3c931e0b34bf245c581a8d1f605eb71bda1cf365dd66f93771fb66eba03a01a4 serial_sha256=3c931e0b34bf245c581a8d1f605eb71bda1cf365dd66f93771fb66eba03a01a4 match=true |
| weak | readcon-db | ingest | sharded | 1 | warm | 3 | 7.456 | 30800 | true | mode=sharded ranks=1 files=4 frames=30800 mpi_s=7.456 serial_s=4.998 mpi_sha256=3c931e0b34bf245c581a8d1f605eb71bda1cf365dd66f93771fb66eba03a01a4 serial_sha256=3c931e0b34bf245c581a8d1f605eb71bda1cf365dd66f93771fb66eba03a01a4 match=true |
| weak | readcon-db | ingest | sharded | 1 | warm | 4 | 7.465 | 30800 | true | mode=sharded ranks=1 files=4 frames=30800 mpi_s=7.465 serial_s=4.930 mpi_sha256=3c931e0b34bf245c581a8d1f605eb71bda1cf365dd66f93771fb66eba03a01a4 serial_sha256=3c931e0b34bf245c581a8d1f605eb71bda1cf365dd66f93771fb66eba03a01a4 match=true |
| weak | readcon-db | ingest | sharded | 1 | warm | 5 | 7.468 | 30800 | true | mode=sharded ranks=1 files=4 frames=30800 mpi_s=7.468 serial_s=4.943 mpi_sha256=3c931e0b34bf245c581a8d1f605eb71bda1cf365dd66f93771fb66eba03a01a4 serial_sha256=3c931e0b34bf245c581a8d1f605eb71bda1cf365dd66f93771fb66eba03a01a4 match=true |
| weak | readcon-db | ingest | sharded | 2 | cold | 1 | 12.714 | 61600 | true | mode=sharded ranks=2 files=4 frames=61600 mpi_s=12.714 serial_s=13.238 mpi_sha256=87874ae3eb2f864528a2bcfea417d3e4144eb1763718c6cce64cd3de4ca4b5ee serial_sha256=87874ae3eb2f864528a2bcfea417d3e4144eb1763718c6cce64cd3de4ca4b5ee match=true |
| weak | readcon-db | ingest | sharded | 2 | cold | 2 | 11.088 | 61600 | true | mode=sharded ranks=2 files=4 frames=61600 mpi_s=11.088 serial_s=11.009 mpi_sha256=87874ae3eb2f864528a2bcfea417d3e4144eb1763718c6cce64cd3de4ca4b5ee serial_sha256=87874ae3eb2f864528a2bcfea417d3e4144eb1763718c6cce64cd3de4ca4b5ee match=true |
| weak | readcon-db | ingest | sharded | 2 | cold | 3 | 11.144 | 61600 | true | mode=sharded ranks=2 files=4 frames=61600 mpi_s=11.144 serial_s=10.894 mpi_sha256=87874ae3eb2f864528a2bcfea417d3e4144eb1763718c6cce64cd3de4ca4b5ee serial_sha256=87874ae3eb2f864528a2bcfea417d3e4144eb1763718c6cce64cd3de4ca4b5ee match=true |
| weak | readcon-db | ingest | sharded | 2 | cold | 4 | 10.998 | 61600 | true | mode=sharded ranks=2 files=4 frames=61600 mpi_s=10.998 serial_s=10.912 mpi_sha256=87874ae3eb2f864528a2bcfea417d3e4144eb1763718c6cce64cd3de4ca4b5ee serial_sha256=87874ae3eb2f864528a2bcfea417d3e4144eb1763718c6cce64cd3de4ca4b5ee match=true |
| weak | readcon-db | ingest | sharded | 2 | cold | 5 | 11.009 | 61600 | true | mode=sharded ranks=2 files=4 frames=61600 mpi_s=11.009 serial_s=10.827 mpi_sha256=87874ae3eb2f864528a2bcfea417d3e4144eb1763718c6cce64cd3de4ca4b5ee serial_sha256=87874ae3eb2f864528a2bcfea417d3e4144eb1763718c6cce64cd3de4ca4b5ee match=true |
| weak | readcon-db | ingest | sharded | 2 | warm | 1 | 10.836 | 61600 | true | mode=sharded ranks=2 files=4 frames=61600 mpi_s=10.836 serial_s=10.797 mpi_sha256=87874ae3eb2f864528a2bcfea417d3e4144eb1763718c6cce64cd3de4ca4b5ee serial_sha256=87874ae3eb2f864528a2bcfea417d3e4144eb1763718c6cce64cd3de4ca4b5ee match=true |
| weak | readcon-db | ingest | sharded | 2 | warm | 2 | 10.821 | 61600 | true | mode=sharded ranks=2 files=4 frames=61600 mpi_s=10.821 serial_s=10.836 mpi_sha256=87874ae3eb2f864528a2bcfea417d3e4144eb1763718c6cce64cd3de4ca4b5ee serial_sha256=87874ae3eb2f864528a2bcfea417d3e4144eb1763718c6cce64cd3de4ca4b5ee match=true |
| weak | readcon-db | ingest | sharded | 2 | warm | 3 | 10.877 | 61600 | true | mode=sharded ranks=2 files=4 frames=61600 mpi_s=10.877 serial_s=10.870 mpi_sha256=87874ae3eb2f864528a2bcfea417d3e4144eb1763718c6cce64cd3de4ca4b5ee serial_sha256=87874ae3eb2f864528a2bcfea417d3e4144eb1763718c6cce64cd3de4ca4b5ee match=true |
| weak | readcon-db | ingest | sharded | 2 | warm | 4 | 10.856 | 61600 | true | mode=sharded ranks=2 files=4 frames=61600 mpi_s=10.856 serial_s=10.870 mpi_sha256=87874ae3eb2f864528a2bcfea417d3e4144eb1763718c6cce64cd3de4ca4b5ee serial_sha256=87874ae3eb2f864528a2bcfea417d3e4144eb1763718c6cce64cd3de4ca4b5ee match=true |
| weak | readcon-db | ingest | sharded | 2 | warm | 5 | 10.891 | 61600 | true | mode=sharded ranks=2 files=4 frames=61600 mpi_s=10.891 serial_s=11.043 mpi_sha256=87874ae3eb2f864528a2bcfea417d3e4144eb1763718c6cce64cd3de4ca4b5ee serial_sha256=87874ae3eb2f864528a2bcfea417d3e4144eb1763718c6cce64cd3de4ca4b5ee match=true |
| weak | readcon-db | ingest | sharded | 4 | cold | 1 | 20.462 | 123200 | true | mode=sharded ranks=4 files=4 frames=123200 mpi_s=20.462 serial_s=25.858 mpi_sha256=9253b93998b2425d76bf034c6434d76d00a798923291b5b486d38ddced437bb7 serial_sha256=9253b93998b2425d76bf034c6434d76d00a798923291b5b486d38ddced437bb7 match=true |
| weak | readcon-db | ingest | sharded | 4 | cold | 2 | 18.316 | 123200 | true | mode=sharded ranks=4 files=4 frames=123200 mpi_s=18.316 serial_s=25.783 mpi_sha256=9253b93998b2425d76bf034c6434d76d00a798923291b5b486d38ddced437bb7 serial_sha256=9253b93998b2425d76bf034c6434d76d00a798923291b5b486d38ddced437bb7 match=true |
| weak | readcon-db | ingest | sharded | 4 | cold | 3 | 17.97 | 123200 | true | mode=sharded ranks=4 files=4 frames=123200 mpi_s=17.970 serial_s=25.912 mpi_sha256=9253b93998b2425d76bf034c6434d76d00a798923291b5b486d38ddced437bb7 serial_sha256=9253b93998b2425d76bf034c6434d76d00a798923291b5b486d38ddced437bb7 match=true |
| weak | readcon-db | ingest | sharded | 4 | cold | 4 | 18.153 | 123200 | true | mode=sharded ranks=4 files=4 frames=123200 mpi_s=18.153 serial_s=25.800 mpi_sha256=9253b93998b2425d76bf034c6434d76d00a798923291b5b486d38ddced437bb7 serial_sha256=9253b93998b2425d76bf034c6434d76d00a798923291b5b486d38ddced437bb7 match=true |
| weak | readcon-db | ingest | sharded | 4 | cold | 5 | 18.121 | 123200 | true | mode=sharded ranks=4 files=4 frames=123200 mpi_s=18.121 serial_s=25.490 mpi_sha256=9253b93998b2425d76bf034c6434d76d00a798923291b5b486d38ddced437bb7 serial_sha256=9253b93998b2425d76bf034c6434d76d00a798923291b5b486d38ddced437bb7 match=true |
| weak | readcon-db | ingest | sharded | 4 | warm | 1 | 18.172 | 123200 | true | mode=sharded ranks=4 files=4 frames=123200 mpi_s=18.172 serial_s=25.912 mpi_sha256=9253b93998b2425d76bf034c6434d76d00a798923291b5b486d38ddced437bb7 serial_sha256=9253b93998b2425d76bf034c6434d76d00a798923291b5b486d38ddced437bb7 match=true |
| weak | readcon-db | ingest | sharded | 4 | warm | 2 | 18.804 | 123200 | true | mode=sharded ranks=4 files=4 frames=123200 mpi_s=18.804 serial_s=25.850 mpi_sha256=9253b93998b2425d76bf034c6434d76d00a798923291b5b486d38ddced437bb7 serial_sha256=9253b93998b2425d76bf034c6434d76d00a798923291b5b486d38ddced437bb7 match=true |
| weak | readcon-db | ingest | sharded | 4 | warm | 3 | 19.113 | 123200 | true | mode=sharded ranks=4 files=4 frames=123200 mpi_s=19.113 serial_s=25.793 mpi_sha256=9253b93998b2425d76bf034c6434d76d00a798923291b5b486d38ddced437bb7 serial_sha256=9253b93998b2425d76bf034c6434d76d00a798923291b5b486d38ddced437bb7 match=true |
| weak | readcon-db | ingest | sharded | 4 | warm | 4 | 18.375 | 123200 | true | mode=sharded ranks=4 files=4 frames=123200 mpi_s=18.375 serial_s=25.724 mpi_sha256=9253b93998b2425d76bf034c6434d76d00a798923291b5b486d38ddced437bb7 serial_sha256=9253b93998b2425d76bf034c6434d76d00a798923291b5b486d38ddced437bb7 match=true |
| weak | readcon-db | ingest | sharded | 4 | warm | 5 | 18.203 | 123200 | true | mode=sharded ranks=4 files=4 frames=123200 mpi_s=18.203 serial_s=25.860 mpi_sha256=9253b93998b2425d76bf034c6434d76d00a798923291b5b486d38ddced437bb7 serial_sha256=9253b93998b2425d76bf034c6434d76d00a798923291b5b486d38ddced437bb7 match=true |
| weak | readcon-db | ingest | sharded | 8 | cold | 1 | 39.256 | 246400 | true | mode=sharded ranks=8 files=4 frames=246400 mpi_s=39.256 serial_s=47.758 mpi_sha256=675047e97d5a9bf59071c4526154fd3b952c9edef45f96ed3d88ed7b5d12a5ee serial_sha256=675047e97d5a9bf59071c4526154fd3b952c9edef45f96ed3d88ed7b5d12a5ee match=true |
| weak | readcon-db | ingest | sharded | 8 | cold | 2 | 35.29 | 246400 | true | mode=sharded ranks=8 files=4 frames=246400 mpi_s=35.290 serial_s=48.417 mpi_sha256=675047e97d5a9bf59071c4526154fd3b952c9edef45f96ed3d88ed7b5d12a5ee serial_sha256=675047e97d5a9bf59071c4526154fd3b952c9edef45f96ed3d88ed7b5d12a5ee match=true |
| weak | readcon-db | ingest | sharded | 8 | cold | 3 | 35.345 | 246400 | true | mode=sharded ranks=8 files=4 frames=246400 mpi_s=35.345 serial_s=47.477 mpi_sha256=675047e97d5a9bf59071c4526154fd3b952c9edef45f96ed3d88ed7b5d12a5ee serial_sha256=675047e97d5a9bf59071c4526154fd3b952c9edef45f96ed3d88ed7b5d12a5ee match=true |
| weak | readcon-db | ingest | sharded | 8 | cold | 4 | 34.356 | 246400 | true | mode=sharded ranks=8 files=4 frames=246400 mpi_s=34.356 serial_s=47.255 mpi_sha256=675047e97d5a9bf59071c4526154fd3b952c9edef45f96ed3d88ed7b5d12a5ee serial_sha256=675047e97d5a9bf59071c4526154fd3b952c9edef45f96ed3d88ed7b5d12a5ee match=true |
| weak | readcon-db | ingest | sharded | 8 | cold | 5 | 44.072 | 246400 | true | mode=sharded ranks=8 files=4 frames=246400 mpi_s=44.072 serial_s=51.700 mpi_sha256=675047e97d5a9bf59071c4526154fd3b952c9edef45f96ed3d88ed7b5d12a5ee serial_sha256=675047e97d5a9bf59071c4526154fd3b952c9edef45f96ed3d88ed7b5d12a5ee match=true |
| weak | readcon-db | ingest | sharded | 8 | warm | 1 | 36.533 | 246400 | true | mode=sharded ranks=8 files=4 frames=246400 mpi_s=36.533 serial_s=47.974 mpi_sha256=675047e97d5a9bf59071c4526154fd3b952c9edef45f96ed3d88ed7b5d12a5ee serial_sha256=675047e97d5a9bf59071c4526154fd3b952c9edef45f96ed3d88ed7b5d12a5ee match=true |
| weak | readcon-db | ingest | sharded | 8 | warm | 2 | 35.38 | 246400 | true | mode=sharded ranks=8 files=4 frames=246400 mpi_s=35.380 serial_s=47.657 mpi_sha256=675047e97d5a9bf59071c4526154fd3b952c9edef45f96ed3d88ed7b5d12a5ee serial_sha256=675047e97d5a9bf59071c4526154fd3b952c9edef45f96ed3d88ed7b5d12a5ee match=true |
| weak | readcon-db | ingest | sharded | 8 | warm | 3 | 34.899 | 246400 | true | mode=sharded ranks=8 files=4 frames=246400 mpi_s=34.899 serial_s=47.715 mpi_sha256=675047e97d5a9bf59071c4526154fd3b952c9edef45f96ed3d88ed7b5d12a5ee serial_sha256=675047e97d5a9bf59071c4526154fd3b952c9edef45f96ed3d88ed7b5d12a5ee match=true |
| weak | readcon-db | ingest | sharded | 8 | warm | 4 | 34.818 | 246400 | true | mode=sharded ranks=8 files=4 frames=246400 mpi_s=34.818 serial_s=47.509 mpi_sha256=675047e97d5a9bf59071c4526154fd3b952c9edef45f96ed3d88ed7b5d12a5ee serial_sha256=675047e97d5a9bf59071c4526154fd3b952c9edef45f96ed3d88ed7b5d12a5ee match=true |
| weak | readcon-db | ingest | sharded | 8 | warm | 5 | 34.807 | 246400 | true | mode=sharded ranks=8 files=4 frames=246400 mpi_s=34.807 serial_s=47.911 mpi_sha256=675047e97d5a9bf59071c4526154fd3b952c9edef45f96ed3d88ed7b5d12a5ee serial_sha256=675047e97d5a9bf59071c4526154fd3b952c9edef45f96ed3d88ed7b5d12a5ee match=true |
| weak | readcon-db | ingest | single | 1 | cold | 1 | 8.444 | 30800 | true | mode=single ranks=1 files=4 frames=30800 mpi_s=8.444 serial_s=5.293 mpi_sha256=4b51e21ccd3a547b3f360c41bc26e736622420414ff29a736690d8ea66dc63c7 serial_sha256=4b51e21ccd3a547b3f360c41bc26e736622420414ff29a736690d8ea66dc63c7 match=true |
| weak | readcon-db | ingest | single | 1 | cold | 2 | 7.869 | 30800 | true | mode=single ranks=1 files=4 frames=30800 mpi_s=7.869 serial_s=5.287 mpi_sha256=4b51e21ccd3a547b3f360c41bc26e736622420414ff29a736690d8ea66dc63c7 serial_sha256=4b51e21ccd3a547b3f360c41bc26e736622420414ff29a736690d8ea66dc63c7 match=true |
| weak | readcon-db | ingest | single | 1 | cold | 3 | 7.9 | 30800 | true | mode=single ranks=1 files=4 frames=30800 mpi_s=7.900 serial_s=5.298 mpi_sha256=4b51e21ccd3a547b3f360c41bc26e736622420414ff29a736690d8ea66dc63c7 serial_sha256=4b51e21ccd3a547b3f360c41bc26e736622420414ff29a736690d8ea66dc63c7 match=true |
| weak | readcon-db | ingest | single | 1 | cold | 4 | 7.873 | 30800 | true | mode=single ranks=1 files=4 frames=30800 mpi_s=7.873 serial_s=5.322 mpi_sha256=4b51e21ccd3a547b3f360c41bc26e736622420414ff29a736690d8ea66dc63c7 serial_sha256=4b51e21ccd3a547b3f360c41bc26e736622420414ff29a736690d8ea66dc63c7 match=true |
| weak | readcon-db | ingest | single | 1 | cold | 5 | 7.946 | 30800 | true | mode=single ranks=1 files=4 frames=30800 mpi_s=7.946 serial_s=5.313 mpi_sha256=4b51e21ccd3a547b3f360c41bc26e736622420414ff29a736690d8ea66dc63c7 serial_sha256=4b51e21ccd3a547b3f360c41bc26e736622420414ff29a736690d8ea66dc63c7 match=true |
| weak | readcon-db | ingest | single | 1 | warm | 1 | 7.923 | 30800 | true | mode=single ranks=1 files=4 frames=30800 mpi_s=7.923 serial_s=5.317 mpi_sha256=4b51e21ccd3a547b3f360c41bc26e736622420414ff29a736690d8ea66dc63c7 serial_sha256=4b51e21ccd3a547b3f360c41bc26e736622420414ff29a736690d8ea66dc63c7 match=true |
| weak | readcon-db | ingest | single | 1 | warm | 2 | 7.701 | 30800 | true | mode=single ranks=1 files=4 frames=30800 mpi_s=7.701 serial_s=5.312 mpi_sha256=4b51e21ccd3a547b3f360c41bc26e736622420414ff29a736690d8ea66dc63c7 serial_sha256=4b51e21ccd3a547b3f360c41bc26e736622420414ff29a736690d8ea66dc63c7 match=true |
| weak | readcon-db | ingest | single | 1 | warm | 3 | 7.733 | 30800 | true | mode=single ranks=1 files=4 frames=30800 mpi_s=7.733 serial_s=5.768 mpi_sha256=4b51e21ccd3a547b3f360c41bc26e736622420414ff29a736690d8ea66dc63c7 serial_sha256=4b51e21ccd3a547b3f360c41bc26e736622420414ff29a736690d8ea66dc63c7 match=true |
| weak | readcon-db | ingest | single | 1 | warm | 4 | 7.868 | 30800 | true | mode=single ranks=1 files=4 frames=30800 mpi_s=7.868 serial_s=5.330 mpi_sha256=4b51e21ccd3a547b3f360c41bc26e736622420414ff29a736690d8ea66dc63c7 serial_sha256=4b51e21ccd3a547b3f360c41bc26e736622420414ff29a736690d8ea66dc63c7 match=true |
| weak | readcon-db | ingest | single | 1 | warm | 5 | 7.841 | 30800 | true | mode=single ranks=1 files=4 frames=30800 mpi_s=7.841 serial_s=5.402 mpi_sha256=4b51e21ccd3a547b3f360c41bc26e736622420414ff29a736690d8ea66dc63c7 serial_sha256=4b51e21ccd3a547b3f360c41bc26e736622420414ff29a736690d8ea66dc63c7 match=true |
| weak | readcon-db | ingest | single | 2 | cold | 1 | 18.447 | 61600 | true | mode=single ranks=2 files=4 frames=61600 mpi_s=18.447 serial_s=13.486 mpi_sha256=700a94ddcf1c727ae355fd03bc8c5ae11ede4077482523a7ddc7adbe6326c802 serial_sha256=700a94ddcf1c727ae355fd03bc8c5ae11ede4077482523a7ddc7adbe6326c802 match=true |
| weak | readcon-db | ingest | single | 2 | cold | 2 | 17.259 | 61600 | true | mode=single ranks=2 files=4 frames=61600 mpi_s=17.259 serial_s=11.878 mpi_sha256=700a94ddcf1c727ae355fd03bc8c5ae11ede4077482523a7ddc7adbe6326c802 serial_sha256=700a94ddcf1c727ae355fd03bc8c5ae11ede4077482523a7ddc7adbe6326c802 match=true |
| weak | readcon-db | ingest | single | 2 | cold | 3 | 11.893 | 61600 | true | mode=single ranks=2 files=4 frames=61600 mpi_s=11.893 serial_s=11.386 mpi_sha256=700a94ddcf1c727ae355fd03bc8c5ae11ede4077482523a7ddc7adbe6326c802 serial_sha256=700a94ddcf1c727ae355fd03bc8c5ae11ede4077482523a7ddc7adbe6326c802 match=true |
| weak | readcon-db | ingest | single | 2 | cold | 4 | 11.675 | 61600 | true | mode=single ranks=2 files=4 frames=61600 mpi_s=11.675 serial_s=11.371 mpi_sha256=700a94ddcf1c727ae355fd03bc8c5ae11ede4077482523a7ddc7adbe6326c802 serial_sha256=700a94ddcf1c727ae355fd03bc8c5ae11ede4077482523a7ddc7adbe6326c802 match=true |
| weak | readcon-db | ingest | single | 2 | cold | 5 | 11.709 | 61600 | true | mode=single ranks=2 files=4 frames=61600 mpi_s=11.709 serial_s=11.448 mpi_sha256=700a94ddcf1c727ae355fd03bc8c5ae11ede4077482523a7ddc7adbe6326c802 serial_sha256=700a94ddcf1c727ae355fd03bc8c5ae11ede4077482523a7ddc7adbe6326c802 match=true |
| weak | readcon-db | ingest | single | 2 | warm | 1 | 11.392 | 61600 | true | mode=single ranks=2 files=4 frames=61600 mpi_s=11.392 serial_s=11.410 mpi_sha256=700a94ddcf1c727ae355fd03bc8c5ae11ede4077482523a7ddc7adbe6326c802 serial_sha256=700a94ddcf1c727ae355fd03bc8c5ae11ede4077482523a7ddc7adbe6326c802 match=true |
| weak | readcon-db | ingest | single | 2 | warm | 2 | 11.854 | 61600 | true | mode=single ranks=2 files=4 frames=61600 mpi_s=11.854 serial_s=11.607 mpi_sha256=700a94ddcf1c727ae355fd03bc8c5ae11ede4077482523a7ddc7adbe6326c802 serial_sha256=700a94ddcf1c727ae355fd03bc8c5ae11ede4077482523a7ddc7adbe6326c802 match=true |
| weak | readcon-db | ingest | single | 2 | warm | 3 | 11.464 | 61600 | true | mode=single ranks=2 files=4 frames=61600 mpi_s=11.464 serial_s=11.683 mpi_sha256=700a94ddcf1c727ae355fd03bc8c5ae11ede4077482523a7ddc7adbe6326c802 serial_sha256=700a94ddcf1c727ae355fd03bc8c5ae11ede4077482523a7ddc7adbe6326c802 match=true |
| weak | readcon-db | ingest | single | 2 | warm | 4 | 11.533 | 61600 | true | mode=single ranks=2 files=4 frames=61600 mpi_s=11.533 serial_s=11.514 mpi_sha256=700a94ddcf1c727ae355fd03bc8c5ae11ede4077482523a7ddc7adbe6326c802 serial_sha256=700a94ddcf1c727ae355fd03bc8c5ae11ede4077482523a7ddc7adbe6326c802 match=true |
| weak | readcon-db | ingest | single | 2 | warm | 5 | 11.518 | 61600 | true | mode=single ranks=2 files=4 frames=61600 mpi_s=11.518 serial_s=11.576 mpi_sha256=700a94ddcf1c727ae355fd03bc8c5ae11ede4077482523a7ddc7adbe6326c802 serial_sha256=700a94ddcf1c727ae355fd03bc8c5ae11ede4077482523a7ddc7adbe6326c802 match=true |
| weak | readcon-db | ingest | single | 4 | cold | 1 | 23.177 | 123200 | true | mode=single ranks=4 files=4 frames=123200 mpi_s=23.177 serial_s=22.617 mpi_sha256=7024d03f2feab80d3792ca4a9247067ef38b2a89d274e163f9fb9bb865893cc5 serial_sha256=7024d03f2feab80d3792ca4a9247067ef38b2a89d274e163f9fb9bb865893cc5 match=true |
| weak | readcon-db | ingest | single | 4 | cold | 2 | 20.698 | 123200 | true | mode=single ranks=4 files=4 frames=123200 mpi_s=20.698 serial_s=23.554 mpi_sha256=7024d03f2feab80d3792ca4a9247067ef38b2a89d274e163f9fb9bb865893cc5 serial_sha256=7024d03f2feab80d3792ca4a9247067ef38b2a89d274e163f9fb9bb865893cc5 match=true |
| weak | readcon-db | ingest | single | 4 | cold | 3 | 20.264 | 123200 | true | mode=single ranks=4 files=4 frames=123200 mpi_s=20.264 serial_s=23.672 mpi_sha256=7024d03f2feab80d3792ca4a9247067ef38b2a89d274e163f9fb9bb865893cc5 serial_sha256=7024d03f2feab80d3792ca4a9247067ef38b2a89d274e163f9fb9bb865893cc5 match=true |
| weak | readcon-db | ingest | single | 4 | cold | 4 | 19.865 | 123200 | true | mode=single ranks=4 files=4 frames=123200 mpi_s=19.865 serial_s=23.597 mpi_sha256=7024d03f2feab80d3792ca4a9247067ef38b2a89d274e163f9fb9bb865893cc5 serial_sha256=7024d03f2feab80d3792ca4a9247067ef38b2a89d274e163f9fb9bb865893cc5 match=true |
| weak | readcon-db | ingest | single | 4 | cold | 5 | 19.958 | 123200 | true | mode=single ranks=4 files=4 frames=123200 mpi_s=19.958 serial_s=23.641 mpi_sha256=7024d03f2feab80d3792ca4a9247067ef38b2a89d274e163f9fb9bb865893cc5 serial_sha256=7024d03f2feab80d3792ca4a9247067ef38b2a89d274e163f9fb9bb865893cc5 match=true |
| weak | readcon-db | ingest | single | 4 | warm | 1 | 18.72 | 123200 | true | mode=single ranks=4 files=4 frames=123200 mpi_s=18.720 serial_s=23.398 mpi_sha256=7024d03f2feab80d3792ca4a9247067ef38b2a89d274e163f9fb9bb865893cc5 serial_sha256=7024d03f2feab80d3792ca4a9247067ef38b2a89d274e163f9fb9bb865893cc5 match=true |
| weak | readcon-db | ingest | single | 4 | warm | 2 | 19.622 | 123200 | true | mode=single ranks=4 files=4 frames=123200 mpi_s=19.622 serial_s=23.295 mpi_sha256=7024d03f2feab80d3792ca4a9247067ef38b2a89d274e163f9fb9bb865893cc5 serial_sha256=7024d03f2feab80d3792ca4a9247067ef38b2a89d274e163f9fb9bb865893cc5 match=true |
| weak | readcon-db | ingest | single | 4 | warm | 3 | 18.743 | 123200 | true | mode=single ranks=4 files=4 frames=123200 mpi_s=18.743 serial_s=23.720 mpi_sha256=7024d03f2feab80d3792ca4a9247067ef38b2a89d274e163f9fb9bb865893cc5 serial_sha256=7024d03f2feab80d3792ca4a9247067ef38b2a89d274e163f9fb9bb865893cc5 match=true |
| weak | readcon-db | ingest | single | 4 | warm | 4 | 18.902 | 123200 | true | mode=single ranks=4 files=4 frames=123200 mpi_s=18.902 serial_s=23.728 mpi_sha256=7024d03f2feab80d3792ca4a9247067ef38b2a89d274e163f9fb9bb865893cc5 serial_sha256=7024d03f2feab80d3792ca4a9247067ef38b2a89d274e163f9fb9bb865893cc5 match=true |
| weak | readcon-db | ingest | single | 4 | warm | 5 | 19.846 | 123200 | true | mode=single ranks=4 files=4 frames=123200 mpi_s=19.846 serial_s=23.604 mpi_sha256=7024d03f2feab80d3792ca4a9247067ef38b2a89d274e163f9fb9bb865893cc5 serial_sha256=7024d03f2feab80d3792ca4a9247067ef38b2a89d274e163f9fb9bb865893cc5 match=true |
| weak | readcon-db | ingest | single | 8 | cold | 1 | 38.19 | 246400 | true | mode=single ranks=8 files=4 frames=246400 mpi_s=38.190 serial_s=60.328 mpi_sha256=a23626b13d04fff916d96d7e87998ab3f3a8a2d1c98ff13ca5d8f49dab303d9b serial_sha256=a23626b13d04fff916d96d7e87998ab3f3a8a2d1c98ff13ca5d8f49dab303d9b match=true |
| weak | readcon-db | ingest | single | 8 | cold | 2 | 40.565 | 246400 | true | mode=single ranks=8 files=4 frames=246400 mpi_s=40.565 serial_s=44.653 mpi_sha256=a23626b13d04fff916d96d7e87998ab3f3a8a2d1c98ff13ca5d8f49dab303d9b serial_sha256=a23626b13d04fff916d96d7e87998ab3f3a8a2d1c98ff13ca5d8f49dab303d9b match=true |
| weak | readcon-db | ingest | single | 8 | cold | 3 | 29.551 | 246400 | true | mode=single ranks=8 files=4 frames=246400 mpi_s=29.551 serial_s=44.073 mpi_sha256=a23626b13d04fff916d96d7e87998ab3f3a8a2d1c98ff13ca5d8f49dab303d9b serial_sha256=a23626b13d04fff916d96d7e87998ab3f3a8a2d1c98ff13ca5d8f49dab303d9b match=true |
| weak | readcon-db | ingest | single | 8 | cold | 4 | 29.606 | 246400 | true | mode=single ranks=8 files=4 frames=246400 mpi_s=29.606 serial_s=43.092 mpi_sha256=a23626b13d04fff916d96d7e87998ab3f3a8a2d1c98ff13ca5d8f49dab303d9b serial_sha256=a23626b13d04fff916d96d7e87998ab3f3a8a2d1c98ff13ca5d8f49dab303d9b match=true |
| weak | readcon-db | ingest | single | 8 | cold | 5 | 29.503 | 246400 | true | mode=single ranks=8 files=4 frames=246400 mpi_s=29.503 serial_s=43.810 mpi_sha256=a23626b13d04fff916d96d7e87998ab3f3a8a2d1c98ff13ca5d8f49dab303d9b serial_sha256=a23626b13d04fff916d96d7e87998ab3f3a8a2d1c98ff13ca5d8f49dab303d9b match=true |
| weak | readcon-db | ingest | single | 8 | warm | 1 | 28.943 | 246400 | true | mode=single ranks=8 files=4 frames=246400 mpi_s=28.943 serial_s=44.627 mpi_sha256=a23626b13d04fff916d96d7e87998ab3f3a8a2d1c98ff13ca5d8f49dab303d9b serial_sha256=a23626b13d04fff916d96d7e87998ab3f3a8a2d1c98ff13ca5d8f49dab303d9b match=true |
| weak | readcon-db | ingest | single | 8 | warm | 2 | 29.706 | 246400 | true | mode=single ranks=8 files=4 frames=246400 mpi_s=29.706 serial_s=43.545 mpi_sha256=a23626b13d04fff916d96d7e87998ab3f3a8a2d1c98ff13ca5d8f49dab303d9b serial_sha256=a23626b13d04fff916d96d7e87998ab3f3a8a2d1c98ff13ca5d8f49dab303d9b match=true |
| weak | readcon-db | ingest | single | 8 | warm | 3 | 29.046 | 246400 | true | mode=single ranks=8 files=4 frames=246400 mpi_s=29.046 serial_s=44.727 mpi_sha256=a23626b13d04fff916d96d7e87998ab3f3a8a2d1c98ff13ca5d8f49dab303d9b serial_sha256=a23626b13d04fff916d96d7e87998ab3f3a8a2d1c98ff13ca5d8f49dab303d9b match=true |
| weak | readcon-db | ingest | single | 8 | warm | 4 | 29.594 | 246400 | true | mode=single ranks=8 files=4 frames=246400 mpi_s=29.594 serial_s=43.473 mpi_sha256=a23626b13d04fff916d96d7e87998ab3f3a8a2d1c98ff13ca5d8f49dab303d9b serial_sha256=a23626b13d04fff916d96d7e87998ab3f3a8a2d1c98ff13ca5d8f49dab303d9b match=true |
| weak | readcon-db | ingest | single | 8 | warm | 5 | 30.364 | 246400 | true | mode=single ranks=8 files=4 frames=246400 mpi_s=30.364 serial_s=63.535 mpi_sha256=a23626b13d04fff916d96d7e87998ab3f3a8a2d1c98ff13ca5d8f49dab303d9b serial_sha256=a23626b13d04fff916d96d7e87998ab3f3a8a2d1c98ff13ca5d8f49dab303d9b match=true |

Per-run stdout, stderr, and the mpiexec command are in `04/logs/`. `04/repeats.jsonl` is the same series, including the six-field keys written before the scale field was added. Those six-field keys are the strong series.

## Campaign 05: cross-binding, H5MD, and ASE trajectory

Harness: `paper/cpc/scripts/failure_matrix.py` and `restart_formats.py` on `paper/cpc-v4a`, driven by `harness/run_05.py`. Outputs are under `05/`. The reference barrier is 0.644561366 eV. The uninterrupted band reached it in 60 steps with 56 free modes on the middle image.

### Failure matrix

`dpos` is the largest absolute coordinate change in Å. R3 `declared` means the velocity came back in the natural unit after applying the declared time unit. `by convention` on R1 means the mask came back under the name `fixed`, which is not an H5MD element. `id`, the velocity `unit` attribute, and `boundary` are H5MD names and are not relabelled.

| format | writer | reader | R1 | R2 | R3 | R4 | pbc | dpos | error | notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CON 3.1 | readcon-core | readcon-core | kept | kept | declared | bit-exact | kept | 0.0 |  |  |
| CON 3.1 | readcon-core | ASE eon reader | error | error | error | error |  |  | ValueError: could not convert string to float: 'Velocities' |  |
| CON 3.1, coordinates only | readcon-core | ASE eon reader | full freeze | lost | lost | bit-exact | FFF | 0.0 |  |  |
| legacy CON | ASE eon writer | readcon-core | error | error | error | error |  |  | TypeError: category must be a Warning subclass, not 'FixCartesian' |  |
| extended XYZ | ASE | ASE | convention | convention | convention | 4.7e-09 A | kept | 4.708383904983293e-09 |  |  |
| extended XYZ | ASE | chemfiles | lost | convention | lost | 4.7e-09 A | - | 4.708383904983293e-09 |  |  |
| extended XYZ | ASE | MDAnalysis | lost | lost | lost | 2.2e-07 A | - | 2.1514905768071912e-07 |  |  |
| extended XYZ | chemfiles | ASE | lost | lost | lost | 4.9e-06 A | TTT | 4.910985489381403e-06 |  |  |
| ASE trajectory | ASE | ASE | kept | lost | convention | bit-exact | kept | 0.0 |  |  |
| POSCAR | ASE | ASE | changed | lost | fixed by format | 4.5e-17 A | TTT | 4.456070928915423e-17 |  |  |
| H5MD | MDAnalysis | MDAnalysis | lost | lost | declared | 2.2e-07 A | TTT | 2.1514905768071912e-07 |  |  |
| CON 3.1 | Python | Python | kept | kept | declared | bit-exact | kept | 0.0 |  | cross-binding |
| CON 3.1 | Python | C | kept | kept | declared | bit-exact | kept | 0.0 |  | cross-binding |
| CON 3.1 | Python | C++ | kept | kept | declared | bit-exact | kept | 0.0 |  | cross-binding |
| CON 3.1 | Python | Fortran | kept | kept | declared | bit-exact | kept | 0.0 |  | cross-binding |
| CON 3.1 | Python | Julia | kept | kept | declared | bit-exact | kept | 0.0 |  | cross-binding |
| CON 3.1 | C | Python | kept | kept | declared | bit-exact | kept | 0.0 |  | cross-binding |
| CON 3.1 | C | C | kept | kept | declared | bit-exact | kept | 0.0 |  | cross-binding |
| CON 3.1 | C | C++ | kept | kept | declared | bit-exact | kept | 0.0 |  | cross-binding |
| CON 3.1 | C | Fortran | kept | kept | declared | bit-exact | kept | 0.0 |  | cross-binding |
| CON 3.1 | C | Julia | kept | kept | declared | bit-exact | kept | 0.0 |  | cross-binding |
| CON 3.1 | C++ | Python | kept | kept | declared | bit-exact | kept | 0.0 |  | cross-binding |
| CON 3.1 | C++ | C | kept | kept | declared | bit-exact | kept | 0.0 |  | cross-binding |
| CON 3.1 | C++ | C++ | kept | kept | declared | bit-exact | kept | 0.0 |  | cross-binding |
| CON 3.1 | C++ | Fortran | kept | kept | declared | bit-exact | kept | 0.0 |  | cross-binding |
| CON 3.1 | C++ | Julia | kept | kept | declared | bit-exact | kept | 0.0 |  | cross-binding |
| CON 3.1 | Fortran | Python | kept | kept | declared | bit-exact | kept | 0.0 |  | Fortran calls rkr_frame_add_atom_full with the C header order. The public module add_atom binding swaps id/mass with the fixed flags and cannot write this frame (status -4, atom id 1 repeated). |
| CON 3.1 | Fortran | C | kept | kept | declared | bit-exact | kept | 0.0 |  | Fortran calls rkr_frame_add_atom_full with the C header order. The public module add_atom binding swaps id/mass with the fixed flags and cannot write this frame (status -4, atom id 1 repeated). |
| CON 3.1 | Fortran | C++ | kept | kept | declared | bit-exact | kept | 0.0 |  | Fortran calls rkr_frame_add_atom_full with the C header order. The public module add_atom binding swaps id/mass with the fixed flags and cannot write this frame (status -4, atom id 1 repeated). |
| CON 3.1 | Fortran | Fortran | kept | kept | declared | bit-exact | kept | 0.0 |  | Fortran calls rkr_frame_add_atom_full with the C header order. The public module add_atom binding swaps id/mass with the fixed flags and cannot write this frame (status -4, atom id 1 repeated). |
| CON 3.1 | Fortran | Julia | kept | kept | declared | bit-exact | kept | 0.0 |  | Fortran calls rkr_frame_add_atom_full with the C header order. The public module add_atom binding swaps id/mass with the fixed flags and cannot write this frame (status -4, atom id 1 repeated). |
| CON 3.1 | Julia | Python | kept | kept | declared | bit-exact | kept | 0.0 |  | cross-binding |
| CON 3.1 | Julia | C | kept | kept | declared | bit-exact | kept | 0.0 |  | cross-binding |
| CON 3.1 | Julia | C++ | kept | kept | declared | bit-exact | kept | 0.0 |  | cross-binding |
| CON 3.1 | Julia | Fortran | kept | kept | declared | bit-exact | kept | 0.0 |  | cross-binding |
| CON 3.1 | Julia | Julia | kept | kept | declared | bit-exact | kept | 0.0 |  | cross-binding |
| H5MD | MDAnalysis | MDAnalysis | lost | lost | declared | 2.2e-07 A | kept | 2.1514905768071912e-07 |  | measured; fixed is by convention; id, unit and boundary are H5MD names |
| H5MD | MDAnalysis | h5py | by convention | kept | declared | 2.2e-07 A | kept | 2.1514905768071912e-07 |  | measured; fixed is by convention; id, unit and boundary are H5MD names |
| H5MD | h5py | h5py | by convention | kept | declared | bit-exact | kept | 0.0 |  | measured; fixed is by convention; id, unit and boundary are H5MD names |
| H5MD | h5py | MDAnalysis | lost | lost | declared | 2.2e-07 A | kept | 2.1514905768071912e-07 |  | measured; fixed is by convention; id, unit and boundary are H5MD names |

Verbatim failures from the original routes, reproduced on this host:

- CON 3.1, readcon-core writer, ASE eon reader: `ValueError: could not convert string to float: 'Velocities'`
- legacy CON, ASE eon writer, readcon-core reader: `TypeError: category must be a Warning subclass, not 'FixCartesian'`

The same two strings are the published `data/failure/matrix.csv` errors. The coordinates-only CON route still reads: R1 full freeze, R2 lost, R3 lost, R4 bit-exact, periodicity FFF.

### Fortran binding

All 25 language pairs (Python, C ABI via ctypes, C++ wrapper, Fortran, Julia) are R1 kept, R2 kept, R3 declared, R4 bit-exact, periodicity kept, on the 9-atom failure-matrix frame.

The Fortran writer in `harness/fortran_io.f90` calls `rkr_frame_add_atom_full` with the C header order `(x, y, z, fixed_x, fixed_y, fixed_z, atom_id, mass, velocity, force)` and stores velocities. The public `ReadCon` module procedure `add_atom` binds `rkr_frame_add_atom_with_fixed_mask` as `(x, y, z, atom_id, mass, fx, fy, fz)`. The C function is `(x, y, z, fx, fy, fz, atom_id, mass)`. A write through that public binding returns status -4. With the library instrumented for one diagnosis, the swallowed cause was:

```
rkr_writer_extend: CON validation failed: atom id 1 is repeated in the frame
```

The public `add_atom` also has no velocity argument. The in-repo Fortran module was not modified. The diagnosis print was removed and `libreadcon_core.so` was rebuilt from the unmodified sources before the recorded runs.

### H5MD

The unpatched MDAnalysis route is the first H5MD row of the matrix: R1 lost, R2 lost, R3 declared, R4 2.2e-07 A (`dpos` 2.1514905768071912e-07), periodicity TTT.

The measured routes write a per-axis mask at `/particles/trajectory/fixed` (bool, N×3), ids at `/particles/trajectory/id` (int64), the velocity unit attribute `Angstrom ps-1`, and box boundary `[periodic, periodic, none]`.

- MDAnalysis writer plus those datasets, read by MDAnalysis: R1 lost, R2 lost, R3 declared, R4 2.2e-07 A, periodicity kept. The MDAnalysis reader does not return `fixed` or `id`.
- Same file, read by h5py: R1 by convention, R2 kept, R3 declared, R4 2.2e-07 A, periodicity kept. The coordinate loss is the MDAnalysis float32 write.
- h5py writer (float64) read by h5py: R1 by convention, R2 kept, R3 declared, R4 bit-exact, periodicity kept.
- h5py writer read by MDAnalysis: R1 lost, R2 lost, R3 declared, R4 2.2e-07 A, periodicity kept.

### Restart

`file_dpos_A` is the largest coordinate change on the interrupted band after the round trip. `max_disp_A` is the largest coordinate change between the resumed band and the uninterrupted band. `d_barrier_eV` is the resumed barrier minus 0.644561366 eV.

| route | steps | converged | barrier_eV | d_barrier_eV | max_disp_A | file_dpos_A | free_modes_mid | error | notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| uninterrupted | 60 | True | 0.644561366 | 0 | 0 |  | 56 |  |  |
| CON 3.1, shortest round trip | 60 | True | 0.644561366 | -5.68e-14 | 2.66e-15 | 0.0e+00 | 56 |  |  |
| CON 3.1, six decimals | 60 | True | 0.644560952 | -4.14e-07 | 6.22e-07 | 4.9e-07 | 56 |  |  |
| CON 3.1 read by the ASE eon reader | 4000 | False | 0.292282514 | -3.52e-01 | 5.43e+00 | 0.0e+00 | 54 |  |  |
| same, periodicity restored by hand | 127 | True | 0.644558431 | -2.93e-06 | 4.21e-02 | 0.0e+00 | 54 |  |  |
| extended XYZ (ASE) | 60 | True | 0.644561367 | 1.09e-09 | 4.94e-09 | 5.0e-09 | 56 |  |  |
| ASE trajectory | 60 | True | 0.644561366 | -2.31e-14 | 3.55e-15 | 0.0e+00 | 56 |  |  |
| POSCAR (ASE) | 98 | True | 0.574323914 | -7.02e-02 | 1.60e-01 | 4.9e-17 | 57 |  |  |
| legacy CON (ASE eon writer) |  |  |  |  |  |  |  | TypeError: category must be a Warning subclass, not 'FixCartesian' |  |
| ASE trajectory, id array | 60 | True | 0.644561366 | -2.31e-14 | 3.55e-15 | 0.0e+00 | 56 |  | id array did not survive the traj round trip; FixCartesian is whatever free_modes_mid shows |
| CON 3.1 Python to Python | 60 | True | 0.644561366 | -2.31e-14 | 3.55e-15 | 0.0e+00 | 56 |  | cross-binding |
| CON 3.1 Python to C | 60 | True | 0.644561366 | -2.31e-14 | 3.55e-15 | 0.0e+00 | 56 |  | cross-binding |
| CON 3.1 Python to C++ | 60 | True | 0.644561366 | -2.31e-14 | 3.55e-15 | 0.0e+00 | 56 |  | cross-binding |
| CON 3.1 Python to Fortran | 60 | True | 0.644561366 | -2.31e-14 | 3.55e-15 | 0.0e+00 | 56 |  | cross-binding |
| CON 3.1 Python to Julia | 60 | True | 0.644561366 | -2.31e-14 | 3.55e-15 | 0.0e+00 | 56 |  | cross-binding |
| CON 3.1 C to Python | 60 | True | 0.644561366 | -2.31e-14 | 3.55e-15 | 0.0e+00 | 56 |  | cross-binding |
| CON 3.1 C to C | 60 | True | 0.644561366 | -2.31e-14 | 3.55e-15 | 0.0e+00 | 56 |  | cross-binding |
| CON 3.1 C to C++ | 60 | True | 0.644561366 | -2.31e-14 | 3.55e-15 | 0.0e+00 | 56 |  | cross-binding |
| CON 3.1 C to Fortran | 60 | True | 0.644561366 | -2.31e-14 | 3.55e-15 | 0.0e+00 | 56 |  | cross-binding |
| CON 3.1 C to Julia | 60 | True | 0.644561366 | -2.31e-14 | 3.55e-15 | 0.0e+00 | 56 |  | cross-binding |
| CON 3.1 C++ to Python | 60 | True | 0.644561366 | -2.31e-14 | 3.55e-15 | 0.0e+00 | 56 |  | cross-binding |
| CON 3.1 C++ to C | 60 | True | 0.644561366 | -2.31e-14 | 3.55e-15 | 0.0e+00 | 56 |  | cross-binding |
| CON 3.1 C++ to C++ | 60 | True | 0.644561366 | -2.31e-14 | 3.55e-15 | 0.0e+00 | 56 |  | cross-binding |
| CON 3.1 C++ to Fortran | 60 | True | 0.644561366 | -2.31e-14 | 3.55e-15 | 0.0e+00 | 56 |  | cross-binding |
| CON 3.1 C++ to Julia | 60 | True | 0.644561366 | -2.31e-14 | 3.55e-15 | 0.0e+00 | 56 |  | cross-binding |
| CON 3.1 Fortran to Python | 60 | True | 0.644561366 | -2.31e-14 | 3.55e-15 | 0.0e+00 | 56 |  | Fortran calls rkr_frame_add_atom_full; the public module add_atom binding does not match the C header |
| CON 3.1 Fortran to C | 60 | True | 0.644561366 | -2.31e-14 | 3.55e-15 | 0.0e+00 | 56 |  | Fortran calls rkr_frame_add_atom_full; the public module add_atom binding does not match the C header |
| CON 3.1 Fortran to C++ | 60 | True | 0.644561366 | -2.31e-14 | 3.55e-15 | 0.0e+00 | 56 |  | Fortran calls rkr_frame_add_atom_full; the public module add_atom binding does not match the C header |
| CON 3.1 Fortran to Fortran | 60 | True | 0.644561366 | -2.31e-14 | 3.55e-15 | 0.0e+00 | 56 |  | Fortran calls rkr_frame_add_atom_full; the public module add_atom binding does not match the C header |
| CON 3.1 Fortran to Julia | 60 | True | 0.644561366 | -2.31e-14 | 3.55e-15 | 0.0e+00 | 56 |  | Fortran calls rkr_frame_add_atom_full; the public module add_atom binding does not match the C header |
| CON 3.1 Julia to Python | 60 | True | 0.644561366 | -2.31e-14 | 3.55e-15 | 0.0e+00 | 56 |  | cross-binding |
| CON 3.1 Julia to C | 60 | True | 0.644561366 | -2.31e-14 | 3.55e-15 | 0.0e+00 | 56 |  | cross-binding |
| CON 3.1 Julia to C++ | 60 | True | 0.644561366 | -2.31e-14 | 3.55e-15 | 0.0e+00 | 56 |  | cross-binding |
| CON 3.1 Julia to Fortran | 60 | True | 0.644561366 | -2.31e-14 | 3.55e-15 | 0.0e+00 | 56 |  | cross-binding |
| CON 3.1 Julia to Julia | 60 | True | 0.644561366 | -2.31e-14 | 3.55e-15 | 0.0e+00 | 56 |  | cross-binding |
| H5MD MDAnalysis to MDAnalysis | 97 | True | 0.573837081 | -7.07e-02 | 1.43e-01 | 4.6e-07 | 84 |  | writer then h5py attaches fixed, id, and boundary; MDAnalysis reader ignores fixed and id |
| H5MD MDAnalysis to h5py | 60 | True | 0.644561168 | -1.98e-07 | 3.67e-07 | 4.6e-07 | 56 |  | fixed is by convention |
| H5MD h5py to h5py | 60 | True | 0.644561366 | -2.31e-14 | 3.55e-15 | 0.0e+00 | 56 |  | fixed is by convention; id, unit and boundary follow H5MD |
| H5MD h5py to MDAnalysis | 97 | True | 0.573837081 | -7.07e-02 | 1.43e-01 | 4.6e-07 | 84 |  | MDAnalysis reader ignores fixed and id |

ASE trajectory with an id array of `17 + 3*i` and `FixCartesian` already on the adatom: the id array did not survive the traj round trip. `free_modes_mid` stayed 56, the same as the uninterrupted band, and the resumed barrier is 0.644561366 eV.

H5MD through the MDAnalysis reader resumes with `free_modes_mid` 84 and barrier 0.573837081 eV (97 steps). That is the mask being dropped: the reader returns no per-axis constraint. H5MD through h5py keeps 56 free modes. The h5py-to-h5py barrier is 0.644561366 eV. MDAnalysis-to-h5py is 0.644561168 eV with file coordinate change 4.6e-07 Å.

The legacy CON restart did not produce a file: `TypeError: category must be a Warning subclass, not 'FixCartesian'`.

Cross-binding resumes (25 pairs) all converged in 60 steps at 0.644561366 eV, `d_barrier_eV` -2.31e-14, `max_disp_A` 3.55e-15, `file_dpos_A` 0.0e+00, `free_modes_mid` 56.

Bands are `05/bands/*.npz`. A slug that stripped trailing underscores made `to C++` overwrite `to C`. Those ten bands were rerun and stored as `*_to_C.npz` and `*_to_Cpp.npz`. The CSV rows were not changed by that rerun; the rerun barriers were again 0.644561366 eV. The restart figure is `05/figures/restart_formats.pdf`, drawn with Atkinson Hyperlegible. Regenerated LaTeX tables are `05/tables/survey_table.tex` and `05/tables/restartfmt_table.tex`. The restart table script replaces any error row with the canned sentence `no file: the writer has no per-axis constraint`; the CSV above is the measured error text.

## Harness

`harness/` contains `run_04.py`, `run_05.py`, `cpp_io.cpp`, `fortran_io.f90`, `julia_io.jl`, and the driver logs `run04.log` and `run05.log`.
