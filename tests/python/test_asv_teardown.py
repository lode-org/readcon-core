"""asv 0.6.6 calls ``teardown``, not ``teardown_cache``.

The timing classes that write a bench file delete that file from
``teardown``. This calls the same methods asv calls for one parameter.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_readcon_timing_teardown_deletes_the_file() -> None:
    bench = _load("bench_readcon", ROOT / "benchmarks" / "bench_readcon.py")
    for cls, param in (
        (bench.TimeReadConTiny, 50),
        (bench.TimeReadConCuh2, 50),
    ):
        bench_case = cls()
        bench_case.setup(param)
        path = Path(bench_case._path)
        assert path.is_file()
        bench_case.teardown(param)
        assert not path.exists()


def test_weak_thread_teardown_deletes_the_file(monkeypatch) -> None:
    module = _load("bench_threads", ROOT / "benches" / "weak_asv" / "bench_threads.py")
    monkeypatch.setattr(module, "serial_match", lambda *_args, **_kwargs: None)
    bench_case = module.TimeWeakThreads()
    bench_case.setup(1)
    path = Path(bench_case._path)
    assert path.is_file()
    bench_case.teardown(1)
    assert not path.exists()
