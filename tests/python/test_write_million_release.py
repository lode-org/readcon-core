"""The release million files are parsed from a log, not copied."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "paper" / "cpc" / "bench" / "write_million_release.py"


def _load():
    spec = importlib.util.spec_from_file_location("write_million_release", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.path.insert(0, str(SCRIPT.parent))
    spec.loader.exec_module(module)
    return module


def _log() -> str:
    samples = "\n".join(f"sample {0.10 + index * 0.001:.9f}" for index in range(12))
    peer = "\n".join(f"sample {1.0 + index * 0.01:.9f}" for index in range(12))
    wide = "\n".join(f"sample {0.01 if index < 6 else 5.0:.9f}" for index in range(12))
    return "\n".join(
        [
            "commit " + "a" * 40,
            "frames 1M n_frames 1 unique 1",
            "read warm 1M readcon-con 0.105000 0.002000 rss 1000 bytes 45000000 loses none",
            samples,
            "read warm 1M ase-extxyz 1.050000 0.020000 rss 2000 bytes 90000000 loses velocities",
            peer,
            "read warm 1M readcon-con-gz 9.000000 20.000000 rss 3000 bytes 5000000 loses none",
            wide,
            "",
        ]
    )


def test_a_wide_row_is_not_published(tmp_path: Path) -> None:
    module = _load()
    log = tmp_path / "cross-format.log"
    log.write_text(_log(), encoding="utf-8")
    hold = tmp_path / "million_hold.json"
    peers = tmp_path / "peers_n1e6.json"
    found = module.write_release(log, hold, peers)
    assert found["hold"] == 1
    assert found["peers"] == 1
    assert any("readcon-con-gz" in line for line in found["unpublished"])
    written = json.loads(hold.read_text(encoding="utf-8"))
    assert written[0]["arm"] == "readcon-con"
    assert written[0]["n"] == 12
    assert written[0]["frames"] == 1
    assert written[0]["atoms_per_frame"] == 1_000_000
    assert "100000000" not in hold.read_text(encoding="utf-8")
    peer = json.loads(peers.read_text(encoding="utf-8"))
    assert peer[0]["arm"] == "ase-extxyz"
    assert peer[0]["loses"] == "velocities"


def test_the_old_tree_is_refused(tmp_path: Path) -> None:
    module = _load()
    log = tmp_path / "r0174" / "million" / "cross-format.log"
    log.parent.mkdir(parents=True)
    log.write_text(_log(), encoding="utf-8")
    with pytest.raises(SystemExit, match="superseded"):
        module.write_release(log, tmp_path / "h.json", tmp_path / "p.json")
