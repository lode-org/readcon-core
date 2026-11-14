# h2h13

Serial, cores 0-7, one warmup, n=12, fresh process per sample. The harness unlinks the destination and does not pass `rewrite=True`.

The million-atom chemfiles lattice was slow because `write_con` rebuilt every atom through `add_atom` and boxed a coordinate triple each time. An unmodified frame is borrowed, and an exact `N.0` in `0` ..= `9999` comes from the integer table. The timed write is 0.0412 s and 23589411 bytes, the same file as before the borrow. chemfiles' XYZ writer takes 0.2879 s on the 11700075-byte source. readcon-con writes the full CON, velocities included, in 0.0774 s (45378064 bytes).

A gzip read of that CON used to inflate all 45378064 plain bytes and, with the decoder budget unset, start one thread per member. The file has 32 members. Each thread kept an allocator arena, and the worker peak was 637212672 bytes against 289247232 for plain CON. A one-thread read now inflates on that thread, and the plain buffer is dropped once the frames own their coordinates. Remeasured on `53c6faa7`: gzip 0.1255 s warm, 0.1272 s cold, peak 291479552 bytes; zstd 0.1227 s warm, 0.1217 s cold, peak 289640448 bytes. Those reads also include the fix that keeps a member concatenated after an indexed gzip or zstd stream. The gzip and zstd writes are the earlier run, 0.1456 s and 0.0643 s.

The plain CON row stays the interleaved serial read, 0.1068 s warm and 0.1356 s cold. A separate fresh-process pair on the same file, same warmup and n=12, was 0.1027 s serial and 0.1040 s with one worker per core. chemfiles-dcd on this run is 0.0954 s.

CON-bin reads call `read_conbin_columns`, the mapped default. Remeasured on `4df45cf4` after that reader and the rename publish: 1M warm 0.0122 s, cold 0.0139 s, peak 154793984 bytes, 65004144 bytes on disk. The cold read before the map was 0.0691 s. The write was remeasured at 0.0369 s, same size.

The mdtraj write of about 0.88 s in h2h12 was the topology loop inside the clock (0.736 s of `add_atom` at 1M). The trajectory is built before the clock. The timed call is `trajectory.save`: DCD 0.0063 s (12000356 bytes), NetCDF 0.0118 s (12000900 bytes).

MDCompress is the refresh-bio 2.0.5 binary, not 1.0.0. One-frame DCD, XTC, and TRR fail with "Cannot read first frame", so those rows are unsupported. The trajectory row is eight frames, archive preset, one thread.

Chemfiles 0.10.4 has no CON writer. The chemfiles-con row is a readcon parse copied through `chemfiles.Frame`. Its write cell is `no writer`.
