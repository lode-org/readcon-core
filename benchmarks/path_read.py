"""ASV timing of ``readcon.read_con`` on a plain CON path.

One warmup is outside the sample. asv repeats the call. The file is the
same 32-atom frame repeated, which is the shape of the 100k-frame read.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

HEADER = (
    '{"con_spec_version":3,"con_spec_minor":1,'
    '"units":{"length":"angstrom","energy":"eV"}}\n'
    "20.0 20.0 20.0\n90.0 90.0 90.0\n\n\n1\n32\n63.546\nCu\n"
    "Coordinates of Component 1\n"
)
BODY = "".join(
    f"{(atom * 3 % 10000) / 1000:.8f} {(atom * 3 + 1) % 10000 / 1000:.8f} "
    f"{(atom * 3 + 2) % 10000 / 1000:.8f} 0 {atom}\n"
    for atom in range(32)
)
FRAME = HEADER + BODY + "\n"


def _path(n_frames: int) -> str:
    fd, name = tempfile.mkstemp(suffix=".con")
    os.close(fd)
    path = Path(name)
    path.write_text("\n" + FRAME * n_frames)
    return name


class PathRead:
    timeout = 600
    repeat = 6
    number = 1

    def setup(self):
        import readcon

        self.readcon = readcon
        self.path = _path(200)
        self.n = 200

    def teardown(self):
        Path(self.path).unlink(missing_ok=True)

    def time_read_con(self):
        frames = self.readcon.read_con(self.path, n_threads=1)
        if len(frames) != self.n:
            raise AssertionError(len(frames))
