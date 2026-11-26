"""Reader samples do not give one arm a fixed place in the repeat."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "paper"
    / "cpc"
    / "scripts"
    / "bench_readers.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("bench_readers_schedule", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_schedule_is_a_seeded_permutation() -> None:
    module = _load()
    names = ["readcon", "ase", "ovito", "chemfiles"]
    first = module.schedule(names)
    second = module.schedule(names)
    assert first == second
    assert len(first) == module.REPEATS
    for order in first:
        assert sorted(order) == sorted(names)
    assert first[0] != list(reversed(names))
