"""ASV arm for the h2h15 formats on the eight-frame trajectory.

The table is ``h2h15.py``: fresh process per sample, one warmup, n=12.
This class repeats those calls with ``repeat`` 12 and ``warmup_time`` 0.
Setup builds every file once. The 0.12.0-dev chemfiles library is its own
class so a run can load it in a process that never imports chemfiles 0.10.4.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import cross_format  # noqa: E402
import h2h15  # noqa: E402


class H2H15Shared:
    timeout = 1200
    number = 1
    repeat = 12
    rounds = 1
    warmup_time = 0

    def setup(self):
        cross_format.serial_threads()
        cross_format.pin_cores()
        os.environ["RAYON_NUM_THREADS"] = "1"
        h2h15.pin_mdcompress()
        directory = cross_format.BENCH / "work" / "h2h15" / "asv-shared"
        directory.mkdir(parents=True, exist_ok=True)
        self.spec = cross_format.make_spec(1000, 8)
        self.con = directory / "readcon.con"
        cross_format.write_readcon(self.con, self.spec, None)
        self.gz = directory / "readcon.con.gz"
        self.zst = directory / "readcon.con.zst"
        cross_format.write_readcon(self.gz, self.spec, "gzip")
        cross_format.write_readcon(self.zst, self.spec, "zstd")
        self.conbin = directory / "readcon.conbin"
        import readcon

        readcon.write_conbin_columns(
            os.fspath(self.conbin),
            self.spec["positions"],
            self.spec["velocities"],
            self.spec["masses"],
            self.spec["cell"],
            self.spec["fixed"],
        )
        self.frames = readcon.read_con(os.fspath(self.con), n_threads=1)
        self.dcd = directory / "source.dcd"
        self.xtc = directory / "source.xtc"
        cross_format.write_chemfiles(self.dcd, self.spec, "DCD")
        cross_format.write_chemfiles(self.xtc, self.spec, "XTC")
        self.desc = directory / "mdcompress.desc"
        self.desc.write_text("MOL\tmetal\t1000\n", encoding="utf-8")
        self.mdc_dcd = directory / "mdcompress.dcd.mdc"
        self.mdc_xtc = directory / "mdcompress.xtc.mdc"
        cross_format.write_mdcompress(self.mdc_dcd, self.dcd, self.desc)
        cross_format.write_mdcompress(self.mdc_xtc, self.xtc, self.desc)
        timed = directory / "timed"
        timed.mkdir(parents=True, exist_ok=True)
        self.write_con = timed / "write.con"
        self.write_gz = timed / "write.con.gz"
        self.write_zst = timed / "write.con.zst"
        self.write_conbin = timed / "write.conbin"
        self.write_dcd = timed / "chemfiles.dcd"
        self.write_mdc_dcd = timed / "mdcompress.dcd.mdc"
        self.write_mdc_xtc = timed / "mdcompress.xtc.mdc"
        self.cf_frames = cross_format.build_chemfiles_frames(
            self.spec, "DCD", self.write_dcd
        )
        h2h15.stamp_chemfiles_0104(self.cf_frames)

    def time_read_con(self):
        cross_format.read_arm("readcon-con", os.fspath(self.con), n_threads=1)

    def time_read_con_gz(self):
        cross_format.read_arm("readcon-con-gz", os.fspath(self.gz), n_threads=1)

    def time_read_con_zst(self):
        cross_format.read_arm("readcon-con-zst", os.fspath(self.zst), n_threads=1)

    def time_read_conbin(self):
        cross_format.read_arm("readcon-conbin", os.fspath(self.conbin), n_threads=1)

    def time_read_mdcompress_dcd(self):
        cross_format.read_mdcompress(os.fspath(self.mdc_dcd))

    def time_read_mdcompress_xtc(self):
        cross_format.read_mdcompress(os.fspath(self.mdc_xtc))

    def time_read_chemfiles_dcd(self):
        cross_format.read_arm("chemfiles-dcd", os.fspath(self.dcd), n_threads=1)

    def time_write_con(self):
        cross_format.write_readcon(self.write_con, self.spec, None)

    def time_write_con_gz(self):
        import readcon

        self.write_gz.unlink(missing_ok=True)
        readcon.write_con(
            os.fspath(self.write_gz), self.frames, compression="gzip", n_threads=1
        )

    def time_write_con_zst(self):
        import readcon

        self.write_zst.unlink(missing_ok=True)
        readcon.write_con(
            os.fspath(self.write_zst), self.frames, compression="zstd", n_threads=1
        )

    def time_write_conbin(self):
        import readcon

        self.write_conbin.unlink(missing_ok=True)
        readcon.write_conbin_columns(
            os.fspath(self.write_conbin),
            self.spec["positions"],
            self.spec["velocities"],
            self.spec["masses"],
            self.spec["cell"],
            self.spec["fixed"],
        )

    def time_write_chemfiles_dcd(self):
        cross_format.write_built_chemfiles(self.write_dcd, "DCD", self.cf_frames)

    def time_write_mdcompress_dcd(self):
        cross_format.write_mdcompress(self.write_mdc_dcd, self.dcd, self.desc)

    def time_write_mdcompress_xtc(self):
        cross_format.write_mdcompress(self.write_mdc_xtc, self.xtc, self.desc)


class H2H15Chemfiles012:
    timeout = 1200
    number = 1
    repeat = 12
    rounds = 1
    warmup_time = 0

    def setup(self):
        cross_format.serial_threads()
        cross_format.pin_cores()
        directory = cross_format.BENCH / "work" / "h2h15" / "asv-012"
        directory.mkdir(parents=True, exist_ok=True)
        library = h2h15.chemfiles_012_library()
        if library is None:
            raise RuntimeError("chemfiles fc1e930 is not installed")
        self.lib = h2h15.load_chemfiles(library)
        self.spec = cross_format.make_spec(1000, 8)
        self.frames = h2h15.build_cf012_frames(self.lib, self.spec)
        self.path = directory / "chemfiles012.dcd"
        h2h15.write_cf012(self.lib, self.path, self.frames)
        self.dest = directory / "timed.dcd"

    def time_read_chemfiles_dcd_012(self):
        h2h15.read_cf012(self.lib, self.path)

    def time_write_chemfiles_dcd_012(self):
        h2h15.write_cf012(self.lib, self.dest, self.frames)
