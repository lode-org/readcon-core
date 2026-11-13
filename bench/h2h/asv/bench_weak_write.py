"""ASV arm for the weak write and its pwrite ceiling.

``time_*`` is one call. The Snakemake rules ``sink_ceiling`` and
``weak_write`` record one warmup and six serial samples, the type-7
median, and the interquartile range. This class is not pinned to one
core: the ceiling is N threads pwriting disjoint offsets.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import weak_write


class WeakWrite:
    """One weak write, one concurrent pwrite, and one single-thread pwrite."""

    timeout = 600
    number = 1
    repeat = 6
    rounds = 1
    warmup_time = 0
    params = [
        (medium, threads)
        for medium in ("pagecache", "tmpfs")
        for threads in weak_write.WIDTHS
    ]
    param_names = ["medium", "threads"]

    def setup(self, medium: str, threads: int):
        weak_write.ensure_module()
        directory = weak_write.PAGE if medium == "pagecache" else weak_write.TMPFS
        directory.mkdir(parents=True, exist_ok=True)
        frames = weak_write.load_frames(int(threads))
        # The sink payload is N copies of one written frame. The multi-frame
        # file has a single header, so it is not that payload.
        one = weak_write.capture_write(
            weak_write.load_frames(1), 1, directory / "asv-one.con"
        )
        chunks, serial, total = weak_write.sink_parts(one, int(threads))
        self.frames = frames
        self.threads = int(threads)
        self.chunks = chunks
        self.serial = serial
        self.total = total
        self.weak_path = directory / "asv-weak.con"
        self.sink_path = directory / "asv-sink.bin"
        self.serial_path = directory / "asv-serial.bin"

    def time_weak_write(self, medium: str, threads: int):
        weak_write.weak_once(self.frames, self.threads, self.weak_path)

    def time_sink_ceiling(self, medium: str, threads: int):
        weak_write.pwrite_chunks(self.sink_path, self.chunks, self.total)

    def time_sink_serial(self, medium: str, threads: int):
        weak_write.pwrite_chunks(self.serial_path, [(self.serial, 0)], self.total)
