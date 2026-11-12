"""ASV arm for the fidelity fixtures. timeout is 120 s.

``time_*`` is one read or one write. The Snakemake rule records one warmup
and six serial samples of the same calls. Paths that the fidelity table
marks read_error or write_error are not timed here.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import campaign


class ReadconFidelity:
    timeout = 120
    number = 1
    repeat = 6
    rounds = 1
    warmup_time = 0

    def setup(self):
        import readcon

        self.campaign = campaign
        self.readcon = readcon

    def time_read_claisen(self):
        self.campaign.read_once("readcon", "claisen.con")

    def time_write_claisen(self):
        self.campaign.write_once("readcon", "claisen.con")

    def time_read_neb(self):
        self.campaign.read_once("readcon", "neb_band_3.con")

    def time_write_neb(self):
        self.campaign.write_once("readcon", "neb_band_3.con")

    def time_read_slab(self):
        self.campaign.read_once("readcon", "pt100_slab.con")

    def time_write_slab(self):
        self.campaign.write_once("readcon", "pt100_slab.con")

    def time_read_convel(self):
        self.campaign.read_once("readcon", "tiny_multi_cuh2.convel")

    def time_write_convel(self):
        self.campaign.write_once("readcon", "tiny_multi_cuh2.convel")

    def time_read_fs_label(self):
        self.campaign.read_once("readcon", "v30_fs_label.convel")

    def time_write_fs_label(self):
        self.campaign.write_once("readcon", "v30_fs_label.convel")


class AseReadconFidelity:
    timeout = 120
    number = 1
    repeat = 6
    rounds = 1
    warmup_time = 0

    def setup(self):
        import ase.io
        import readcon

        self.campaign = campaign
        self.ase_io = ase.io
        self.readcon = readcon

    def time_read_claisen(self):
        self.campaign.read_once("ase-readcon-con", "claisen.con")

    def time_read_neb(self):
        self.campaign.read_once("ase-readcon-con", "neb_band_3.con")

    def time_write_neb(self):
        self.campaign.write_once("ase-readcon-con", "neb_band_3.con")

    def time_read_slab(self):
        self.campaign.read_once("ase-readcon-con", "pt100_slab.con")

    def time_write_slab(self):
        self.campaign.write_once("ase-readcon-con", "pt100_slab.con")

    def time_read_convel(self):
        self.campaign.read_once("ase-readcon-convel", "tiny_multi_cuh2.convel")

    def time_write_convel(self):
        self.campaign.write_once("ase-readcon-convel", "tiny_multi_cuh2.convel")

    def time_read_fs_label(self):
        self.campaign.read_once("ase-readcon-convel", "v30_fs_label.convel")

    def time_write_fs_label(self):
        self.campaign.write_once("ase-readcon-convel", "v30_fs_label.convel")


class AseEonFidelity:
    timeout = 120
    number = 1
    repeat = 6
    rounds = 1
    warmup_time = 0

    def setup(self):
        import ase.io

        self.campaign = campaign
        self.ase_io = ase.io

    def time_read_claisen(self):
        self.campaign.read_once("ase-eon", "claisen.con")

    def time_write_claisen(self):
        self.campaign.write_once("ase-eon", "claisen.con")

    def time_read_slab(self):
        self.campaign.read_once("ase-eon", "pt100_slab.con")

    def time_write_slab(self):
        self.campaign.write_once("ase-eon", "pt100_slab.con")

    def time_read_fs_label(self):
        self.campaign.read_once("ase-eon", "v30_fs_label.convel")

    def time_write_fs_label(self):
        self.campaign.write_once("ase-eon", "v30_fs_label.convel")


class EonPythonFidelity:
    """eon.fileio.loadcons. Set EON_ROOT to the eOn checkout."""

    timeout = 120
    number = 1
    repeat = 6
    rounds = 1
    warmup_time = 0

    def setup(self):
        import readcon

        self.campaign = campaign
        self.readcon = readcon
        self.campaign.eon_api()

    def time_read_claisen(self):
        self.campaign.read_once("eon-python", "claisen.con")

    def time_write_claisen(self):
        self.campaign.write_once("eon-python", "claisen.con")

    def time_read_neb(self):
        self.campaign.read_once("eon-python", "neb_band_3.con")

    def time_write_neb(self):
        self.campaign.write_once("eon-python", "neb_band_3.con")

    def time_read_slab(self):
        self.campaign.read_once("eon-python", "pt100_slab.con")

    def time_write_slab(self):
        self.campaign.write_once("eon-python", "pt100_slab.con")

    def time_read_convel(self):
        self.campaign.read_once("eon-python", "tiny_multi_cuh2.convel")

    def time_write_convel(self):
        self.campaign.write_once("eon-python", "tiny_multi_cuh2.convel")

    def time_read_fs_label(self):
        self.campaign.read_once("eon-python", "v30_fs_label.convel")

    def time_write_fs_label(self):
        self.campaign.write_once("eon-python", "v30_fs_label.convel")
