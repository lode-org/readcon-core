"""ASV benchmarks for the shipped ``readcon`` Python API (not a reimplementation).

Timing methods (``time_*``) and memory methods (``ray_*``) live on separate
classes. asv-runner 0.3.2 forces ``number = 1`` when a timing class defines
``setup`` (``asv_runner/benchmarks/time.py``), so the timing classes have no
``setup`` and no ``number``. asv calibrates ``number`` until each sample takes
about ``sample_time`` seconds. That target is asv_runner's default of
0.01 s. Memory classes set ``number = 1`` so
memray records one call. The workflow passes ``repeat`` and ``rounds``.
"""

from __future__ import annotations

import os
from pathlib import Path


def _load_bench_disk():
    import importlib.util

    here = Path(__file__).resolve()
    for parent in (here, *here.parents):
        candidate = parent / "bench" / "h2h" / "bench_disk.py"
        if candidate.is_file():
            spec = importlib.util.spec_from_file_location(
                "readcon_bench_disk", candidate
            )
            module = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(module)
            return module
    raise RuntimeError("bench/h2h/bench_disk.py was not found")


_BENCH = _load_bench_disk()
bench_scratch = _BENCH.bench_scratch
bench_file = _BENCH.bench_file
bench_dir = _BENCH.bench_dir


REPO = Path(__file__).resolve().parent.parent
FIXTURE_TINY = REPO / "resources" / "test" / "tiny_cuh2.con"
FIXTURE_CUH2 = REPO / "resources" / "test" / "cuh2.con"

# Comparison is six rounds of six repeats (36 samples). Main-vs-main timing
# uses twelve rounds and splits them into two 36-sample sides. Memory stays
# one peak per asv invocation (number = 1).
# Smallest even repeat whose median is the mean of the two central samples
# with two samples strictly below that pair and two strictly above it.
REPEAT = 6
# asv_runner TimeBenchmark.sample_time default is 0.01 s. Each sample targets
# that default.
ASV_DEFAULT_SAMPLE_TIME = 0.01
SAMPLE_TIME = ASV_DEFAULT_SAMPLE_TIME
TINY_FRAMES = (50, 100, 200)
CUH2_FRAMES = (50, 100)


def _ladder_con(src: Path, n_frames: int) -> str:
    return src.read_text() * n_frames


def _write_temp(text: str, suffix: str = ".con") -> str:
    path = bench_file("bench-readcon", suffix)
    path.write_text(text)
    return str(path)


def _read_con_string(text: str, n_frames: int) -> None:
    import readcon

    frames = readcon.read_con_string(text)
    assert len(frames) == n_frames
    assert len(frames[0]) > 0


def _read_con_path(path: str, n_frames: int, n_atoms: int | None = None) -> None:
    import readcon

    frames = readcon.read_con(path)
    assert len(frames) == n_frames
    if n_atoms is not None:
        assert len(frames[0]) == n_atoms


def _iter_con_path(path: str, n_frames: int) -> None:
    import readcon

    frames = list(readcon.iter_con(path))
    assert len(frames) == n_frames


def _read_chemfiles(path: str, n_frames: int) -> None:
    import readcon

    frames = readcon.read_chemfiles(path)
    assert len(frames) == n_frames
    assert len(frames[0]) > 0


def _select_name_cu(frame) -> None:
    idx = frame.select_atoms("name Cu")
    assert len(idx) > 0


def _optional_select_frame():
    """One preloaded frame for the selection benchmark.

    Loaded when this module is imported in the benchmark process, before asv
    starts the timer. A missing chemfiles build leaves it as None and the
    benchmark skips.
    """
    try:
        import readcon

        if not readcon.has_chemfiles_support():
            return None
        return readcon.read_first_frame(str(FIXTURE_CUH2))
    except Exception:
        return None


_SELECT_FRAME = _optional_select_frame()


def _skip_if_needed(cache) -> None:
    if isinstance(cache, dict) and cache.get("skip"):
        from asv_runner.benchmarks.mark import SkipNotImplemented

        raise SkipNotImplemented("chemfiles not linked")


def _tiny_files() -> dict[int, tuple[str, str]]:
    out: dict[int, tuple[str, str]] = {}
    for n in TINY_FRAMES:
        text = _ladder_con(FIXTURE_TINY, n)
        out[n] = (text, _write_temp(text))
    return out


def _cuh2_files() -> dict[int, str]:
    return {n: _write_temp(_ladder_con(FIXTURE_CUH2, n)) for n in CUH2_FRAMES}


def _xyz_files() -> dict:
    import readcon

    if not readcon.has_chemfiles_support():
        return {"skip": True}
    frame = readcon.read_first_frame(str(FIXTURE_CUH2))
    atoms = frame.to_ase()
    from ase.io import write

    out: dict = {}
    for n in CUH2_FRAMES:
        path = _write_temp("", suffix=".xyz")
        write(path, [atoms] * n, format="xyz")
        out[n] = path
    return out


class TimeReadConTiny:
    """Parse multi-frame tiny CON (4 atoms/frame) via shipped readcon."""

    timeout = 300
    repeat = REPEAT
    sample_time = SAMPLE_TIME
    min_run_count = 2
    warmup_time = 0.1
    params = list(TINY_FRAMES)
    param_names = ["n_frames"]

    def setup_cache(self) -> dict[int, tuple[str, str]]:
        return _tiny_files()

    def time_read_con_string(self, cache: dict, n_frames: int) -> None:
        text, _path = cache[int(n_frames)]
        _read_con_string(text, int(n_frames))

    def time_read_con_path(self, cache: dict, n_frames: int) -> None:
        _text, path = cache[int(n_frames)]
        _read_con_path(path, int(n_frames))

    def time_iter_con_materialize(self, cache: dict, n_frames: int) -> None:
        _text, path = cache[int(n_frames)]
        _iter_con_path(path, int(n_frames))


class RayReadConTiny:
    """Memray peak for the tiny CON reads. One call per sample."""

    timeout = 180
    number = 1
    repeat = 1
    rounds = 1
    params = list(TINY_FRAMES)
    param_names = ["n_frames"]

    def setup(self, n_frames: int) -> None:
        text = _ladder_con(FIXTURE_TINY, n_frames)
        self._text = text
        self._path = _write_temp(text)
        self._n = n_frames

    def teardown(self, n_frames: int) -> None:
        try:
            os.unlink(self._path)
        except OSError:
            pass

    def ray_read_con_string(self, n_frames: int) -> None:
        _read_con_string(self._text, self._n)

    def ray_read_con_path(self, n_frames: int) -> None:
        _read_con_path(self._path, self._n)

    def ray_iter_con_materialize(self, n_frames: int) -> None:
        _iter_con_path(self._path, self._n)


class TimeReadConCuh2:
    """Parse multi-frame 218-atom CON (cuh2) via shipped readcon."""

    timeout = 300
    repeat = REPEAT
    sample_time = SAMPLE_TIME
    min_run_count = 2
    warmup_time = 0.1
    params = list(CUH2_FRAMES)
    param_names = ["n_frames"]

    def setup_cache(self) -> dict[int, str]:
        return _cuh2_files()

    def time_read_con_path(self, cache: dict, n_frames: int) -> None:
        _read_con_path(cache[int(n_frames)], int(n_frames), n_atoms=218)


class RayReadConCuh2:
    """Memray peak for the 218-atom CON read. One call per sample."""

    timeout = 180
    number = 1
    repeat = 1
    rounds = 1
    params = list(CUH2_FRAMES)
    param_names = ["n_frames"]

    def setup(self, n_frames: int) -> None:
        self._path = _write_temp(_ladder_con(FIXTURE_CUH2, n_frames))
        self._n = n_frames

    def teardown(self, n_frames: int) -> None:
        try:
            os.unlink(self._path)
        except OSError:
            pass

    def ray_read_con_path(self, n_frames: int) -> None:
        _read_con_path(self._path, self._n, n_atoms=218)


class TimeChemfilesXyz:
    """Foreign XYZ to ConFrame via shipped readcon.read_chemfiles (skip if lean)."""

    timeout = 300
    repeat = REPEAT
    sample_time = SAMPLE_TIME
    min_run_count = 2
    warmup_time = 0.1
    params = list(CUH2_FRAMES)
    param_names = ["n_frames"]

    def setup_cache(self) -> dict:
        return _xyz_files()

    def time_read_chemfiles(self, cache: dict, n_frames: int) -> None:
        _skip_if_needed(cache)
        _read_chemfiles(cache[int(n_frames)], int(n_frames))


class RayChemfilesXyz:
    """Memray peak for read_chemfiles. One call per sample."""

    timeout = 180
    number = 1
    repeat = 1
    rounds = 1
    params = list(CUH2_FRAMES)
    param_names = ["n_frames"]

    def setup(self, n_frames: int) -> None:
        import readcon

        if not readcon.has_chemfiles_support():
            raise NotImplementedError("chemfiles not linked")
        frame = readcon.read_first_frame(str(FIXTURE_CUH2))
        atoms = frame.to_ase()
        from ase.io import write

        self._path = _write_temp("", suffix=".xyz")
        write(self._path, [atoms] * n_frames, format="xyz")
        self._n = n_frames

    def teardown(self, n_frames: int) -> None:
        try:
            os.unlink(self._path)
        except OSError:
            pass

    def ray_read_chemfiles(self, n_frames: int) -> None:
        _read_chemfiles(self._path, self._n)


class TimeSelectAtoms:
    """Selection API on a loaded CON frame (needs chemfiles-linked build)."""

    timeout = 300
    repeat = REPEAT
    sample_time = SAMPLE_TIME
    min_run_count = 2
    warmup_time = 0.1

    def time_select_name_Cu(self) -> None:
        if _SELECT_FRAME is None:
            from asv_runner.benchmarks.mark import SkipNotImplemented

            raise SkipNotImplemented("chemfiles not linked")
        _select_name_cu(_SELECT_FRAME)


class RaySelectAtoms:
    """Memray peak for select_atoms. One call per sample."""

    timeout = 120
    number = 1
    repeat = 1
    rounds = 1

    def setup(self) -> None:
        import readcon

        if not readcon.has_chemfiles_support():
            raise NotImplementedError("chemfiles not linked")
        self._frame = readcon.read_first_frame(str(FIXTURE_CUH2))

    def ray_select_name_Cu(self) -> None:
        _select_name_cu(self._frame)
