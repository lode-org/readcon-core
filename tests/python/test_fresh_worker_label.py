"""The fresh-process read arms label their worker count with the right plural.

A one-CPU host must read ``1 worker`` on the parallel arm, not ``1 workers``.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bench" / "h2h"))

import cross_format


def test_worker_label_singular_and_plural() -> None:
    assert cross_format._worker_label(1) == "1 worker"
    assert cross_format._worker_label(2) == "2 workers"
    assert cross_format._worker_label(8) == "8 workers"


def test_fresh_read_arms_on_one_cpu_host(monkeypatch) -> None:
    monkeypatch.setattr(cross_format.os, "cpu_count", lambda: 1)
    arms = cross_format._fresh_read_arms()
    labels = {arm_id: label for arm_id, label, _threads in arms}
    assert labels["readcon-con-fresh-ncpu"] == "1 worker"
    assert labels["readcon-con-fresh-serial"] == "1 worker"


def test_fresh_read_arms_on_a_multi_cpu_host(monkeypatch) -> None:
    monkeypatch.setattr(cross_format.os, "cpu_count", lambda: 8)
    arms = cross_format._fresh_read_arms()
    labels = {arm_id: label for arm_id, label, _threads in arms}
    assert labels["readcon-con-fresh-ncpu"] == "8 workers"
    assert labels["readcon-con-fresh-serial"] == "1 worker"
