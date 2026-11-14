"""The million-atom comparison reads the 0.23.0 record and does not rewrite it."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bench" / "h2h"))

import million_report as report


def _row(arm, tool, op, median, iqr=0.01, cache=None):
    return {
        "structure": "1M",
        "arm": arm,
        "tool": tool,
        "op": op,
        "cache": cache or ("warm" if op == "read" else "create"),
        "median_s": median,
        "iqr_s": iqr,
        "rss_bytes": 10,
        "file_bytes": 20,
        "loses": "none",
    }


def _pair(old_rc, new_rc, old_peer, new_peer):
    old = {
        ("1M", "readcon-con", "read", "warm"): _row(
            "readcon-con", "readcon", "read", old_rc
        ),
        ("1M", "ase-extxyz", "read", "warm"): _row(
            "ase-extxyz", "ase", "read", old_peer
        ),
    }
    new = {
        ("1M", "readcon-con", "read", "warm"): _row(
            "readcon-con", "readcon", "read", new_rc
        ),
        ("1M", "ase-extxyz", "read", "warm"): _row(
            "ase-extxyz", "ase", "read", new_peer
        ),
    }
    return old, new


def test_type7_median_matches_the_middle_of_an_odd_count():
    assert report.type7_median([1.0, 3.0, 2.0]) == 2.0


def test_uniform_slowdown_is_not_a_readcon_regression():
    old, new = _pair(0.10, 0.20, 2.0, 4.0)
    factor = {"read": report.machine_factor(old, new, "read")[0], "write": 1.0}
    assert factor["read"] == pytest.approx(2.0)
    assert report.self_regressions(old, new, factor) == []
    assert report.lost_leads(old, new) == []


def test_readcon_slower_than_the_peer_factor_is_a_regression():
    old, new = _pair(0.10, 0.40, 2.0, 2.0)
    factor = {"read": 1.0, "write": 1.0}
    found = report.self_regressions(old, new, factor)
    assert len(found) == 1
    assert "readcon-con" in found[0]


def test_lost_lead_needs_a_real_gap():
    old, new = _pair(0.50, 1.50, 1.0, 1.0)
    assert report.lost_leads(old, new)
    old_close, new_close = _pair(0.99, 1.01, 1.0, 1.0)
    assert report.lost_leads(old_close, new_close) == []


def test_report_refuses_to_write_the_baseline_directory():
    with pytest.raises(SystemExit, match="existing records"):
        report.fresh_output(report.BASELINE.parent)


def test_notes_name_the_fields_con_keeps(tmp_path: Path):
    doc = {
        "commit": "abc",
        "warmup": 1,
        "repeats": 12,
        "percentile": "type7",
        "serial": True,
        "process": "fresh subprocess per sample",
        "affinity": "taskset -c 0",
        "versions": {"readcon": "0.23.2"},
        "host": {"cpu_mhz": 2400.0, "loadavg": "0.1", "lscpu": "Model name: test\n"},
        "rows": [
            _row("readcon-con", "readcon", "read", 0.20),
            _row("ase-extxyz", "ase", "read", 4.0),
            _row("readcon-con", "readcon", "write", 0.30),
            _row("ase-extxyz", "ase", "write", 8.0),
        ],
    }
    baseline = {
        "rows": [
            _row("readcon-con", "readcon", "read", 0.10),
            _row("ase-extxyz", "ase", "read", 2.0),
            _row("readcon-con", "readcon", "write", 0.15),
            _row("ase-extxyz", "ase", "write", 4.0),
        ]
    }
    (tmp_path / "cross-format.json").write_text(json.dumps(doc))
    notes, flags = report.build_notes(doc, baseline)
    assert flags == []
    assert "masses, velocities, constraints" in notes
    assert "Peer reads" in notes and "Peer writes" in notes
    report.write_record(tmp_path, doc, notes)
    assert (tmp_path / "host.json").is_file()
    assert (tmp_path / "lscpu.txt").read_text().startswith("Model name")


def test_library_commit_matches_the_sources_at_head():
    import subprocess

    found = report.library_commit(report.ROOT)
    head_src = subprocess.check_output(
        ["git", "rev-parse", "HEAD:src"], cwd=report.ROOT, text=True
    )
    lib_src = subprocess.check_output(
        ["git", "rev-parse", f"{found}:src"], cwd=report.ROOT, text=True
    )
    assert head_src == lib_src
    assert found == "80dde969650cdfdd736f78328b371a7a98597159"


def test_write_only_campaign_does_not_demand_read_rows():
    doc = {
        "commit": "abc",
        "warmup": 1,
        "repeats": 12,
        "percentile": "type7",
        "serial": True,
        "process": "fresh subprocess per sample",
        "affinity": "taskset -c 0",
        "versions": {"readcon": "0.23.2"},
        "host": {"cpu_mhz": 2400.0, "loadavg": "0.1", "lscpu": "Model name: test\n"},
        "rows": [
            _row("readcon-con", "readcon", "write", 0.30),
            _row("ase-extxyz", "ase", "write", 8.0),
        ],
    }
    baseline = {
        "rows": [
            _row("readcon-con", "readcon", "read", 0.10),
            _row("ase-extxyz", "ase", "read", 2.0),
            _row("readcon-con", "readcon", "write", 0.15),
            _row("ase-extxyz", "ase", "write", 4.0),
        ]
    }
    notes, flags = report.build_notes(doc, baseline)
    assert flags == []
    assert "Peer writes" in notes
    assert "Peer reads" not in notes
    assert "readcon-con read" not in notes
