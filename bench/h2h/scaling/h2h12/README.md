# h2h12

Chemfiles 0.10.4 has no CON format and no CON plugin. `Trajectory` on a `.con` path fails with "can not find a format associated with the '.con' extension". The chemfiles-con row is a readcon parse copied through `chemfiles.Frame` (positions and the cell). Its write cell is `no writer`.

The chemfiles-con write cells in `h2h9/`, `h2h10/`, and `h2h11/` are not CON writes. Those records are unchanged. h2h9 and h2h10 stored the readcon CON size on that write (1k 36958, 100k 4303070, 1M 45378064, traj 302664). h2h11 stored 10 bytes, the `projected\n` stub. No other arm in those records was a stub write.

A timed write now fails the run unless the file is non-empty, inside that format's size range, and reads back as `(n_frames, n_atoms, 3)`.

readcon-con, readcon-con-gz, readcon-con-zst, readcon-chemfiles, and readcon-conbin writes in this table were measured again after the short-decimal tie spelling and the unnamed-file publish (`d4347f39`). Reads and the other writes are the earlier run on the same machine: serial, cores 0-7, one warmup, n=6, and n=12 when IQR/median exceeded 5%. The harness unlinks the destination and does not pass `rewrite=True`.

MDCompress is the refresh-bio 2.0.5 binary, not 1.0.0. One-frame inputs fail with "Cannot read first frame", so those rows are unsupported. The trajectory row is eight frames, archive preset, one thread.
