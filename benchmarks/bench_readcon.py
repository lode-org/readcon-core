"""ASV benchmarks for the shipped ``readcon`` Python API (not a reimplementation)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FIXTURE_TINY = REPO / "resources" / "test" / "tiny_cuh2.con"
FIXTURE_CUH2 = REPO / "resources" / "test" / "cuh2.con"


def _ladder_con(src: Path, n_frames: int) -> str:
    return src.read_text() * n_frames


def _write_temp(text: str, suffix: str = ".con") -> str:
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    Path(path).write_text(text)
    return path


class TimeReadConTiny:
    """Parse multi-frame tiny CON (4 atoms/frame) via shipped readcon."""

    timeout = 60
    repeat = 5
    number = 1
    warmup_time = 0.1
    params = [50, 100, 200]
    param_names = ["n_frames"]

    def setup(self, n_frames: int) -> None:
        import readcon  # noqa: F401

        text = _ladder_con(FIXTURE_TINY, n_frames)
        self._text = text
        self._path = _write_temp(text)
        self._n = n_frames

    def teardown(self, n_frames: int) -> None:
        try:
            os.unlink(self._path)
        except OSError:
            pass

    def time_read_con_string(self, n_frames: int) -> None:
        import readcon

        frames = readcon.read_con_string(self._text)
        assert len(frames) == self._n
        assert len(frames[0]) > 0

    def time_read_con_path(self, n_frames: int) -> None:
        import readcon

        frames = readcon.read_con(self._path)
        assert len(frames) == self._n

    def time_iter_con_materialize(self, n_frames: int) -> None:
        import readcon

        frames = list(readcon.iter_con(self._path))
        assert len(frames) == self._n


class TimeReadConCuh2:
    """Parse multi-frame 218-atom CON (cuh2) via shipped readcon."""

    timeout = 120
    repeat = 3
    number = 1
    warmup_time = 0.1
    params = [50, 100]
    param_names = ["n_frames"]

    def setup(self, n_frames: int) -> None:
        import readcon  # noqa: F401

        text = _ladder_con(FIXTURE_CUH2, n_frames)
        self._path = _write_temp(text)
        self._n = n_frames

    def teardown(self, n_frames: int) -> None:
        try:
            os.unlink(self._path)
        except OSError:
            pass

    def time_read_con_path(self, n_frames: int) -> None:
        import readcon

        frames = readcon.read_con(self._path)
        assert len(frames) == self._n
        assert len(frames[0]) == 218


class TimeChemfilesXyz:
    """Foreign XYZ → ConFrame via shipped readcon.read_chemfiles (skip if lean)."""

    timeout = 120
    repeat = 3
    number = 1
    warmup_time = 0.1
    params = [50, 100]
    param_names = ["n_frames"]

    def setup(self, n_frames: int) -> None:
        import readcon

        if not readcon.has_chemfiles_support():
            raise NotImplementedError("chemfiles not linked")
        fr = readcon.read_first_frame(str(FIXTURE_CUH2))
        atoms = fr.to_ase()
        from ase.io import write

        self._path = _write_temp("", suffix=".xyz")
        write(self._path, [atoms] * n_frames, format="xyz")
        self._n = n_frames

    def teardown(self, n_frames: int) -> None:
        try:
            os.unlink(self._path)
        except OSError:
            pass

    def time_read_chemfiles(self, n_frames: int) -> None:
        import readcon

        frames = readcon.read_chemfiles(self._path)
        assert len(frames) == self._n
        assert len(frames[0]) > 0


class TimeSelectAtoms:
    """Selection API on a loaded CON frame (needs chemfiles-linked build)."""

    timeout = 60
    repeat = 10
    number = 1
    warmup_time = 0.05

    def setup(self) -> None:
        import readcon

        if not readcon.has_chemfiles_support():
            raise NotImplementedError("chemfiles not linked")
        self._frame = readcon.read_first_frame(str(FIXTURE_CUH2))

    def time_select_name_Cu(self) -> None:
        idx = self._frame.select_atoms("name Cu")
        assert len(idx) > 0
