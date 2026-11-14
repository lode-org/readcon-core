"""ASV arm for one million-atom CON read and write.

The table (every library, file size, peak RSS, and the fields each format
drops) is the Snakemake rule ``million``, which runs ``cross_format.py``
with one warmup and 12 fresh processes. This class times the same readcon
calls: plain CON, gzip, zstd, and CON-bin. Setup converts the Cu lattice
once, outside the clock. ``repeat`` is 12 and ``warmup_time`` is 0 because
the campaign, not asv, owns the warmup.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import cross_format


class MillionCon:
    timeout = 1200
    number = 1
    repeat = 12
    rounds = 1
    warmup_time = 0

    def setup(self):
        import readcon

        cross_format.serial_threads()
        cross_format.pin_cores()
        os.environ["RAYON_NUM_THREADS"] = "1"
        directory = cross_format.WORK / "asv-1M"
        directory.mkdir(parents=True, exist_ok=True)
        self.spec = cross_format.make_spec(1_000_000, 1)
        self.con = cross_format.convert_arm("readcon-con", self.spec, directory)
        self.gz = cross_format.convert_arm("readcon-con-gz", self.spec, directory)
        self.zst = cross_format.convert_arm("readcon-con-zst", self.spec, directory)
        self.conbin = cross_format.convert_arm("readcon-conbin", self.spec, directory)
        self.frames = readcon.read_con(os.fspath(self.con), n_threads=1)
        self.read = cross_format.read_arm
        timed = directory / "asv-timed"
        timed.mkdir(parents=True, exist_ok=True)
        self.write_con = timed / "write.con"
        self.write_gz = timed / "write.con.gz"
        self.write_zst = timed / "write.con.zst"
        self.write_conbin = timed / "write.conbin"
        self.plain = os.fspath(self.con)

    def time_read_con(self):
        self.read("readcon-con", os.fspath(self.con))

    def time_read_con_gz(self):
        self.read("readcon-con-gz", os.fspath(self.gz))

    def time_read_con_zst(self):
        self.read("readcon-con-zst", os.fspath(self.zst))

    def time_read_conbin(self):
        self.read("readcon-conbin", os.fspath(self.conbin))

    def time_write_con(self):
        cross_format.write_readcon(self.write_con, self.spec, None)

    def time_write_con_gz(self):
        import readcon

        self.write_gz.unlink(missing_ok=True)
        readcon.write_con(
            os.fspath(self.write_gz),
            self.frames,
            compression="gzip",
            n_threads=1,
        )

    def time_write_con_zst(self):
        import readcon

        self.write_zst.unlink(missing_ok=True)
        readcon.write_con(
            os.fspath(self.write_zst),
            self.frames,
            compression="zstd",
            n_threads=1,
        )

    def time_write_conbin(self):
        import readcon

        self.write_conbin.unlink(missing_ok=True)
        readcon.write_conbin(self.plain, os.fspath(self.write_conbin))

    def track_con_bytes(self):
        return float(self.con.stat().st_size)

    def track_con_gz_bytes(self):
        return float(self.gz.stat().st_size)

    def track_con_zst_bytes(self):
        return float(self.zst.stat().st_size)

    def track_conbin_bytes(self):
        return float(self.conbin.stat().st_size)
