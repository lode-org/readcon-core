"""Each timing entry point refuses a module that was not built from this tree."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bench" / "h2h"))

import camp24_run
import cross_format
import h2h15
import h2h15_asv
import measured_commit
import million_ab

pytest.importorskip("readcon")
import readcon


def _install_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        measured_commit,
        "measurement",
        lambda _root: {
            "commit": "a" * 40,
            "tree": "b" * 40,
            "diff_sha256": "0" * 64,
            "remote": "refs/heads/feat/release-0.23.0",
        },
    )
    monkeypatch.setattr(readcon, "__commit__", "c" * 40, raising=False)
    monkeypatch.setattr(readcon, "__tree__", "d" * 40, raising=False)
    monkeypatch.setattr(readcon, "__source_digest__", "stale", raising=False)


def test_h2h15_run_refuses_a_stale_build(monkeypatch, tmp_path: Path) -> None:
    _install_stale(monkeypatch)
    monkeypatch.setattr(h2h15.cross_format, "run", lambda *_args, **_kwargs: None)
    with pytest.raises(SystemExit, match="not built from HEAD"):
        h2h15.run(tmp_path, repeats=12)


def test_h2h15_asv_refuses_a_stale_build(monkeypatch, tmp_path: Path) -> None:
    _install_stale(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["h2h15_asv.py", str(h2h15_asv.RECORD)])
    with pytest.raises(SystemExit, match="not built from HEAD"):
        h2h15_asv.main()


def test_cross_format_run_refuses_a_stale_build(monkeypatch, tmp_path: Path) -> None:
    _install_stale(monkeypatch)
    with pytest.raises(SystemExit, match="not built from HEAD"):
        cross_format.run(tmp_path, repeats=1)


def test_million_ab_refuses_a_stale_build(monkeypatch, tmp_path: Path) -> None:
    _install_stale(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["million_ab.py", str(tmp_path)])
    with pytest.raises(SystemExit, match="not built from HEAD"):
        million_ab.main()


def test_camp24_conbin_writes_refuse_a_stale_build(monkeypatch) -> None:
    _install_stale(monkeypatch)
    with pytest.raises(SystemExit, match="not built from HEAD"):
        camp24_run.conbin_writes()


def test_camp24_host_refuses_a_stale_build(monkeypatch) -> None:
    _install_stale(monkeypatch)
    with pytest.raises(SystemExit, match="not built from HEAD"):
        camp24_run.host()


def test_camp24_main_refuses_a_stale_build(monkeypatch) -> None:
    _install_stale(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["camp24_run.py", "ranked"])

    def _ranked() -> None:
        raise AssertionError("ranked ran")

    monkeypatch.setattr(camp24_run, "ranked", _ranked)
    with pytest.raises(SystemExit, match="not built from HEAD"):
        camp24_run.main()
