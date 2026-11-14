"""ASV benchmarks for the shipped ``readcon`` Python API (not a reimplementation).

Timing methods (``time_*``) and memory methods (``ray_*``) live on separate
classes. asv-runner 0.3.2 forces ``number = 1`` when a timing class defines
``setup`` (``asv_runner/benchmarks/time.py``), so the timing classes have no
``setup`` and no ``number``. asv calibrates ``number`` until each sample takes
about ``sample_time`` seconds. That target is asv_runner's default of
0.01 s. Memory classes set ``number = 1``. Each ``ray_*`` sample is one
parse, and the memray peak is the median of ``repeat`` of those.
``track_python_heap_*`` is tracemalloc of the Python heap, not that peak.

Timing rows use ``asv.conf.json`` and the shipped mimalloc build.
Memory rows use ``asv.mem.conf.json`` and the ``system-alloc`` feature,
which drops mimalloc so memray's malloc hook sees the parser.
Timing rows and the shipped library keep mimalloc. Native traces are not
required. A child ``ru_maxrss`` delta stays at zero because importing
the extension already sets the high-water mark.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FIXTURE_TINY = REPO / "resources" / "test" / "tiny_cuh2.con"
FIXTURE_CUH2 = REPO / "resources" / "test" / "cuh2.con"

# Comparison is six rounds of six repeats (36 samples). Main-vs-main timing
# uses twelve rounds and splits them into two 36-sample sides. Memory uses
# the same six repeats, one call each (number = 1). A round's peak is the
# median of those six memray samples.
# Smallest even repeat whose median is the mean of the two central samples
# with two samples strictly below that pair and two strictly above it.
REPEAT = 6
# asv_runner TimeBenchmark.sample_time default is 0.01 s. Each sample targets
# that default.
ASV_DEFAULT_SAMPLE_TIME = 0.01
SAMPLE_TIME = ASV_DEFAULT_SAMPLE_TIME
TINY_FRAMES = (50, 100, 200)
CUH2_FRAMES = (50, 100)

# Cited with the results by benchmarks/memory_context.py.
MEMORY_TRACKING_METHOD = (
    "memray Tracker peak_memory, median of 6 repeats after one untracked "
    "warmup; asv.mem.conf.json enables the system-alloc feature so the "
    "parser uses the system allocator; track_python_heap_* is tracemalloc; "
    "timing rows stay on mimalloc"
)
# Bytes of the coordinate slab for one atom in one frame. Masses stay on
# the shared header. Ids, fixed flags, and the symbol index are stored
# once when they do not change by frame, so they are not part of this
# per-atom-frame floor. A velocity or force slab adds 24 bytes.
MIN_ATOM_BYTES = 3 * 8


def minimal_output_bytes(n_atoms: int, n_frames: int, extra_atom_bytes: int = 0) -> int:
    return int(n_atoms) * int(n_frames) * (MIN_ATOM_BYTES + int(extra_atom_bytes))


def _ladder_con(src: Path, n_frames: int) -> str:
    return src.read_text() * n_frames


def _bench_dir() -> Path:
    path = REPO / "build" / "bench"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_temp(text: str, suffix: str = ".con") -> str:
    fd, path = tempfile.mkstemp(suffix=suffix, dir=_bench_dir())
    os.close(fd)
    Path(path).write_text(text)
    return path


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


def _read_con_threads(path: str, n_frames: int, n_atoms: int, n_threads: int) -> None:
    import readcon

    frames = readcon.read_con(path, n_threads=int(n_threads))
    _hold_parsed(frames, int(n_frames), n_atoms=int(n_atoms))


THREAD_COUNTS = (2, 4, 8)


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


def _hold_parsed(frames, n_frames: int, n_atoms: int | None = None):
    """Keep the object ``read_con`` returned until the sample ends.

    The coordinates stay the arrays the parser built. A NumPy copy would
    add test-side bytes on top of that parse. ``len`` of the first frame
    checks the atom count; it does not allocate another coordinate buffer.
    """
    n = len(frames)
    if n != n_frames:
        raise AssertionError(n)
    if n_frames == 0:
        raise AssertionError("no frames")
    n0 = len(frames[0])
    if n_atoms is not None and n0 != n_atoms:
        raise AssertionError(n0)
    if n0 <= 0:
        raise AssertionError(n0)
    return frames


def _tracemalloc_peak(action) -> int:
    """Peak Python-heap bytes of ``action``.

    This is not the parser peak. The resident set of a fresh process does
    not move once import has reserved the high-water mark, so a
    ``ru_maxrss`` delta of the same parse is zero. tracemalloc counts
    the Python objects built for the sample.
    """
    import tracemalloc

    tracemalloc.start()
    try:
        action()
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return int(peak)


def _peak_samples(action) -> dict:
    samples = [_tracemalloc_peak(action) for _ in range(REPEAT)]
    return {"samples": samples, "number": 1}


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
    """Memray peak for the tiny CON reads. One call per sample.

    Path samples call ``read_con`` on the file. String samples call
    ``read_con_string``. Setup parses once, untracked, so the recorded
    peak is the parse and not the first-call reserve.
    """

    timeout = 180
    number = 1
    repeat = REPEAT
    rounds = 1
    unit = "bytes"
    params = list(TINY_FRAMES)
    param_names = ["n_frames"]

    def setup(self, n_frames: int) -> None:
        import readcon

        text = _ladder_con(FIXTURE_TINY, n_frames)
        self._text = text
        self._path = _write_temp(text)
        self._n = n_frames
        _hold_parsed(readcon.read_con(self._path), self._n)
        _hold_parsed(readcon.read_con_string(self._text), self._n)
        _hold_parsed(list(readcon.iter_con(self._path)), self._n)

    def teardown(self, n_frames: int) -> None:
        try:
            os.unlink(self._path)
        except OSError:
            pass

    def ray_read_con_string(self, n_frames: int) -> None:
        import readcon

        _hold_parsed(readcon.read_con_string(self._text), self._n)

    def ray_read_con_path(self, n_frames: int) -> None:
        import readcon

        _hold_parsed(readcon.read_con(self._path), self._n)

    def track_python_heap_read_con_path(self, n_frames: int) -> dict:
        import readcon

        return _peak_samples(
            lambda: _hold_parsed(readcon.read_con(self._path), self._n)
        )

    def ray_iter_con_materialize(self, n_frames: int) -> None:
        import readcon

        _hold_parsed(list(readcon.iter_con(self._path)), self._n)


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
    """Memray peak for the 218-atom CON read. One call per sample.

    The sample calls ``read_con`` on the file and holds the frames the
    parser returned. A mapped file is part of that peak when the map is
    still live; the frames make the peak larger than the file.
    """

    timeout = 180
    number = 1
    repeat = REPEAT
    rounds = 1
    unit = "bytes"
    params = list(CUH2_FRAMES)
    param_names = ["n_frames"]

    def setup(self, n_frames: int) -> None:
        import readcon

        text = _ladder_con(FIXTURE_CUH2, n_frames)
        self._path = _write_temp(text)
        self._n = n_frames
        _hold_parsed(readcon.read_con(self._path), self._n, n_atoms=218)

    def teardown(self, n_frames: int) -> None:
        try:
            os.unlink(self._path)
        except OSError:
            pass

    def ray_read_con_path(self, n_frames: int) -> None:
        import readcon

        _hold_parsed(readcon.read_con(self._path), self._n, n_atoms=218)

    def track_python_heap_read_con_path(self, n_frames: int) -> dict:
        import readcon

        return _peak_samples(
            lambda: _hold_parsed(
                readcon.read_con(self._path), self._n, n_atoms=218
            )
        )


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
    """Memray peak for read_chemfiles on an XYZ file.

    The atoms come from the first cuh2 frame, written as XYZ. This is
    not a CON head-to-head: the file and the parser are different from
    the ``read_con`` and ASE eOn rows.
    """

    timeout = 180
    number = 1
    repeat = REPEAT
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
        _hold_parsed(readcon.read_chemfiles(self._path), self._n)

    def teardown(self, n_frames: int) -> None:
        try:
            os.unlink(self._path)
        except OSError:
            pass

    def ray_read_chemfiles_xyz(self, n_frames: int) -> None:
        import readcon

        _hold_parsed(readcon.read_chemfiles(self._path), self._n)


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
    repeat = REPEAT
    rounds = 1

    def setup(self) -> None:
        import readcon

        if not readcon.has_chemfiles_support():
            raise NotImplementedError("chemfiles not linked")
        self._frame = readcon.read_first_frame(str(FIXTURE_CUH2))
        _select_name_cu(self._frame)

    def ray_select_name_Cu(self) -> None:
        _select_name_cu(self._frame)


def _ase_eon(path: str, n_frames: int, n_atoms: int):
    from ase.io import read

    images = read(path, index=":", format="eon")
    if len(images) != n_frames:
        raise AssertionError(len(images))
    if len(images[0]) != n_atoms:
        raise AssertionError(len(images[0]))
    return images


class RayAseEonTiny:
    """ASE ``format='eon'`` on the same tiny CON files as ``read_con``."""

    timeout = 180
    number = 1
    repeat = REPEAT
    rounds = 1
    unit = "bytes"
    params = list(TINY_FRAMES)
    param_names = ["n_frames"]

    def setup(self, n_frames: int) -> None:
        text = _ladder_con(FIXTURE_TINY, n_frames)
        self._path = _write_temp(text)
        self._n = n_frames
        _ase_eon(self._path, self._n, 4)

    def teardown(self, n_frames: int) -> None:
        try:
            os.unlink(self._path)
        except OSError:
            pass

    def ray_read_ase_eon(self, n_frames: int) -> None:
        _ase_eon(self._path, self._n, 4)


class RayAseEonCuh2:
    """ASE ``format='eon'`` on the same 218-atom CON files as ``read_con``."""

    timeout = 180
    number = 1
    repeat = REPEAT
    rounds = 1
    unit = "bytes"
    params = list(CUH2_FRAMES)
    param_names = ["n_frames"]

    def setup(self, n_frames: int) -> None:
        text = _ladder_con(FIXTURE_CUH2, n_frames)
        self._path = _write_temp(text)
        self._n = n_frames
        _ase_eon(self._path, self._n, 218)

    def teardown(self, n_frames: int) -> None:
        try:
            os.unlink(self._path)
        except OSError:
            pass

    def ray_read_ase_eon(self, n_frames: int) -> None:
        _ase_eon(self._path, self._n, 218)


class TimeAseEonTiny:
    """Time ASE ``format='eon'`` on the same tiny CON files as ``read_con``."""

    timeout = 300
    repeat = REPEAT
    sample_time = SAMPLE_TIME
    min_run_count = 2
    warmup_time = 0.1
    params = list(TINY_FRAMES)
    param_names = ["n_frames"]

    def setup_cache(self) -> dict[int, tuple[str, str]]:
        return _tiny_files()

    def time_read_ase_eon(self, cache: dict, n_frames: int) -> None:
        _text, path = cache[int(n_frames)]
        _ase_eon(path, int(n_frames), 4)


class TimeAseEonCuh2:
    """Time ASE ``format='eon'`` on the same 218-atom CON files as ``read_con``."""

    timeout = 300
    repeat = REPEAT
    sample_time = SAMPLE_TIME
    min_run_count = 2
    warmup_time = 0.1
    params = list(CUH2_FRAMES)
    param_names = ["n_frames"]

    def setup_cache(self) -> dict[int, str]:
        return _cuh2_files()

    def time_read_ase_eon(self, cache: dict, n_frames: int) -> None:
        _ase_eon(cache[int(n_frames)], int(n_frames), 218)


FIXTURE_CONVEL = REPO / "resources" / "test" / "tiny_cuh2.convel"
FIXTURE_FORCES = REPO / "resources" / "test" / "tiny_cuh2_forces.con"


class RayReadConvelTiny:
    """Memray peak for a velocity CON on the column path."""

    timeout = 180
    number = 1
    repeat = REPEAT
    rounds = 1
    unit = "bytes"
    params = list(TINY_FRAMES)
    param_names = ["n_frames"]

    def setup(self, n_frames: int) -> None:
        import readcon

        text = _ladder_con(FIXTURE_CONVEL, n_frames)
        self._path = _write_temp(text, suffix=".convel")
        self._n = n_frames
        frames = readcon.read_con(self._path)
        _hold_parsed(frames, self._n, n_atoms=4)
        assert frames[0].has_velocities

    def teardown(self, n_frames: int) -> None:
        try:
            os.unlink(self._path)
        except OSError:
            pass

    def ray_read_con_path(self, n_frames: int) -> None:
        import readcon

        frames = readcon.read_con(self._path)
        _hold_parsed(frames, self._n, n_atoms=4)
        assert frames[0].has_velocities


class RayReadForcesTiny:
    """Memray peak for a force CON on the column path."""

    timeout = 180
    number = 1
    repeat = REPEAT
    rounds = 1
    unit = "bytes"
    params = (50, 100)
    param_names = ["n_frames"]

    def setup(self, n_frames: int) -> None:
        import readcon

        text = _ladder_con(FIXTURE_FORCES, n_frames)
        self._path = _write_temp(text)
        self._n = n_frames
        frames = readcon.read_con(self._path)
        _hold_parsed(frames, self._n, n_atoms=4)
        assert frames[0].has_forces

    def teardown(self, n_frames: int) -> None:
        try:
            os.unlink(self._path)
        except OSError:
            pass

    def ray_read_con_path(self, n_frames: int) -> None:
        import readcon

        frames = readcon.read_con(self._path)
        _hold_parsed(frames, self._n, n_atoms=4)
        assert frames[0].has_forces


def _thread_params(frame_counts: tuple[int, ...]) -> list[tuple[int, int]]:
    return [(frames, threads) for frames in frame_counts for threads in THREAD_COUNTS]


class TimeReadConCuh2Threads:
    """``read_con`` of cuh2 with 2, 4, and 8 threads."""

    timeout = 300
    repeat = REPEAT
    sample_time = SAMPLE_TIME
    min_run_count = 2
    warmup_time = 0.1
    params = _thread_params(CUH2_FRAMES)
    param_names = ["n_frames", "n_threads"]

    def setup_cache(self) -> dict[int, str]:
        return _cuh2_files()

    def time_read_con_threads(self, cache: dict, n_frames: int, n_threads: int) -> None:
        _read_con_threads(cache[int(n_frames)], int(n_frames), 218, int(n_threads))


class RayReadConCuh2Threads:
    """Memray peak for threaded cuh2 reads."""

    timeout = 180
    number = 1
    repeat = REPEAT
    rounds = 1
    unit = "bytes"
    params = _thread_params(CUH2_FRAMES)
    param_names = ["n_frames", "n_threads"]

    def setup(self, n_frames: int, n_threads: int) -> None:
        text = _ladder_con(FIXTURE_CUH2, n_frames)
        self._path = _write_temp(text)
        self._n = n_frames
        self._threads = n_threads
        _read_con_threads(self._path, self._n, 218, self._threads)

    def teardown(self, n_frames: int, n_threads: int) -> None:
        try:
            os.unlink(self._path)
        except OSError:
            pass

    def ray_read_con_threads(self, n_frames: int, n_threads: int) -> None:
        _read_con_threads(self._path, self._n, 218, self._threads)


class TimeReadConvelThreads:
    """Threaded read of the tiny velocity file, repeated."""

    timeout = 300
    repeat = REPEAT
    sample_time = SAMPLE_TIME
    min_run_count = 2
    warmup_time = 0.1
    params = _thread_params((100, 200))
    param_names = ["n_frames", "n_threads"]

    def setup_cache(self) -> dict[int, str]:
        return {n: _write_temp(_ladder_con(FIXTURE_CONVEL, n), suffix=".convel") for n in (100, 200)}

    def time_read_con_threads(self, cache: dict, n_frames: int, n_threads: int) -> None:
        _read_con_threads(cache[int(n_frames)], int(n_frames), 4, int(n_threads))


class RayReadConvelThreads:
    """Memray peak for threaded velocity-file reads."""

    timeout = 180
    number = 1
    repeat = REPEAT
    rounds = 1
    unit = "bytes"
    params = _thread_params((100, 200))
    param_names = ["n_frames", "n_threads"]

    def setup(self, n_frames: int, n_threads: int) -> None:
        text = _ladder_con(FIXTURE_CONVEL, n_frames)
        self._path = _write_temp(text, suffix=".convel")
        self._n = n_frames
        self._threads = n_threads
        _read_con_threads(self._path, self._n, 4, self._threads)

    def teardown(self, n_frames: int, n_threads: int) -> None:
        try:
            os.unlink(self._path)
        except OSError:
            pass

    def ray_read_con_threads(self, n_frames: int, n_threads: int) -> None:
        _read_con_threads(self._path, self._n, 4, self._threads)


class TimeReadForcesThreads:
    """Threaded read of the tiny force file, repeated."""

    timeout = 300
    repeat = REPEAT
    sample_time = SAMPLE_TIME
    min_run_count = 2
    warmup_time = 0.1
    params = _thread_params((100, 200))
    param_names = ["n_frames", "n_threads"]

    def setup_cache(self) -> dict[int, str]:
        return {n: _write_temp(_ladder_con(FIXTURE_FORCES, n)) for n in (100, 200)}

    def time_read_con_threads(self, cache: dict, n_frames: int, n_threads: int) -> None:
        _read_con_threads(cache[int(n_frames)], int(n_frames), 4, int(n_threads))


class RayReadForcesThreads:
    """Memray peak for threaded force-file reads."""

    timeout = 180
    number = 1
    repeat = REPEAT
    rounds = 1
    unit = "bytes"
    params = _thread_params((100, 200))
    param_names = ["n_frames", "n_threads"]

    def setup(self, n_frames: int, n_threads: int) -> None:
        text = _ladder_con(FIXTURE_FORCES, n_frames)
        self._path = _write_temp(text)
        self._n = n_frames
        self._threads = n_threads
        _read_con_threads(self._path, self._n, 4, self._threads)

    def teardown(self, n_frames: int, n_threads: int) -> None:
        try:
            os.unlink(self._path)
        except OSError:
            pass

    def ray_read_con_threads(self, n_frames: int, n_threads: int) -> None:
        _read_con_threads(self._path, self._n, 4, self._threads)


class TimeAseConvel:
    """ASE eOn on the same velocity files as the threaded readcon rows."""

    timeout = 300
    repeat = REPEAT
    sample_time = SAMPLE_TIME
    min_run_count = 2
    warmup_time = 0.1
    params = (100, 200)
    param_names = ["n_frames"]

    def setup_cache(self) -> dict[int, str]:
        return {n: _write_temp(_ladder_con(FIXTURE_CONVEL, n), suffix=".convel") for n in (100, 200)}

    def time_read_ase_eon(self, cache: dict, n_frames: int) -> None:
        _ase_eon(cache[int(n_frames)], int(n_frames), 4)


class RayAseConvel:
    """Memray peak for ASE eOn on the velocity files."""

    timeout = 180
    number = 1
    repeat = REPEAT
    rounds = 1
    unit = "bytes"
    params = (100, 200)
    param_names = ["n_frames"]

    def setup(self, n_frames: int) -> None:
        text = _ladder_con(FIXTURE_CONVEL, n_frames)
        self._path = _write_temp(text, suffix=".convel")
        self._n = n_frames
        _ase_eon(self._path, self._n, 4)

    def teardown(self, n_frames: int) -> None:
        try:
            os.unlink(self._path)
        except OSError:
            pass

    def ray_read_ase_eon(self, n_frames: int) -> None:
        _ase_eon(self._path, self._n, 4)


class TimeAseForces:
    """ASE eOn on the same force files as the threaded readcon rows."""

    timeout = 300
    repeat = REPEAT
    sample_time = SAMPLE_TIME
    min_run_count = 2
    warmup_time = 0.1
    params = (100, 200)
    param_names = ["n_frames"]

    def setup_cache(self) -> dict[int, str]:
        return {n: _write_temp(_ladder_con(FIXTURE_FORCES, n)) for n in (100, 200)}

    def time_read_ase_eon(self, cache: dict, n_frames: int) -> None:
        _ase_eon(cache[int(n_frames)], int(n_frames), 4)


class RayAseForces:
    """Memray peak for ASE eOn on the force files."""

    timeout = 180
    number = 1
    repeat = REPEAT
    rounds = 1
    unit = "bytes"
    params = (100, 200)
    param_names = ["n_frames"]

    def setup(self, n_frames: int) -> None:
        text = _ladder_con(FIXTURE_FORCES, n_frames)
        self._path = _write_temp(text)
        self._n = n_frames
        _ase_eon(self._path, self._n, 4)

    def teardown(self, n_frames: int) -> None:
        try:
            os.unlink(self._path)
        except OSError:
            pass

    def ray_read_ase_eon(self, n_frames: int) -> None:
        _ase_eon(self._path, self._n, 4)


def _ray_repeats(bench) -> int:
    """``repeat`` from the benchmark class, or an ``-a repeat=`` override."""
    for source in getattr(bench, "_attr_sources", ()):
        try:
            value = getattr(source, "repeat")
        except Exception:
            continue
        if isinstance(value, bool):
            continue
        if isinstance(value, int) and value > 0:
            return value
    return REPEAT


def _install_memray_repeats() -> None:
    """Record ``repeat`` memray peaks for each ``ray_*`` call.

    asv_bench_memray 0.1.2 tracks the call once and returns that single
    peak. The memory classes set ``repeat`` so the stored value is the
    median of that many peaks. Each repeat is its own tracker. One
    tracker around every repeat would keep the frames live together.
    """
    try:
        from asv_bench_memray.benchmarks.raymem import RayMemBenchmark
    except Exception:
        return
    if getattr(RayMemBenchmark, "_readcon_repeats", False):
        return

    def run(self, *param):
        import memray

        peaks = []
        for _ in range(_ray_repeats(self)):
            fd, name = tempfile.mkstemp(suffix=".bin", dir=_bench_dir())
            os.close(fd)
            capture = Path(name)
            try:
                with memray.Tracker(
                    destination=memray.FileDestination(capture, overwrite=True)
                ):
                    self.func(*param)
                peaks.append(
                    int(memray.FileReader(str(capture)).metadata.peak_memory)
                )
            finally:
                capture.unlink(missing_ok=True)
        return {"samples": peaks, "number": 1}

    RayMemBenchmark.run = run
    RayMemBenchmark._readcon_repeats = True


_install_memray_repeats()
