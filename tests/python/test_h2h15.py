# Copyright (c) readcon-core developers
"""The h2h15 harness keeps the two chemfiles rows apart and names its parent."""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bench" / "h2h"))

import h2h15
from bench_disk import bench_file


def test_an_extra_only_run_writes_the_host(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("readcon")
    monkeypatch.setenv("READCON_CROSS_PART", "extra")
    ident = {
        "commit": "a" * 40,
        "tree": "b" * 40,
        "diff_sha256": "0" * 64,
        "remote": "refs/heads/feat/release-0.23.0",
    }
    monkeypatch.setattr(h2h15, "refuse_stale_build", lambda _root: ident)
    monkeypatch.setattr(h2h15, "pin_mdcompress", lambda: (tmp_path, tmp_path))
    monkeypatch.setattr(h2h15, "_extra_rows", lambda *_args, **_kwargs: ([], [], []))
    monkeypatch.setattr(
        h2h15.cross_format,
        "campaign_host",
        lambda _out, tree: {
            "loadavg": "0.10 0.10 0.10 1/1 1",
            "governor": {"0": "performance"},
            "cpu_model": "Test CPU",
            "tree": tree,
        },
    )
    h2h15.run(tmp_path)
    host = json.loads((tmp_path / "host.json").read_text(encoding="utf-8"))
    assert host["loadavg"].startswith("0.10")
    assert host["governor"]["0"] == "performance"
    assert host["cpu_model"] == "Test CPU"
    assert host["commit"] == "a" * 40


def test_chemfiles_rows_stay_separate_and_name_the_interval_unit():
    older = h2h15.DROPS["chemfiles-dcd"]
    newer = h2h15.DROPS["chemfiles-dcd-012"]
    assert older != newer
    assert "interval unit: AKMA" in older
    assert "interval unit: picoseconds" in newer
    assert "chemfiles-dcd" in h2h15.DROPS
    assert "chemfiles-dcd-012" in h2h15.DROPS


def test_readcon_keeps_velocities_and_mdcompress_drops_them():
    assert "velocities" not in h2h15.DROPS["readcon-con"]
    assert "forces,energies" == h2h15.DROPS["readcon-conbin"]
    for arm in ("mdcompress-dcd", "mdcompress-xtc"):
        assert "velocities" in h2h15.DROPS[arm]
        assert "binary64 coordinates" in h2h15.DROPS[arm]
        assert "interval unit" not in h2h15.DROPS[arm]


def test_unique_frame_hashes_sit_beside_the_million_fields():
    import cross_format

    spec = cross_format.make_spec(16, 4)
    assert spec["n_unique_frames"] == 4
    assert spec["unique_frame_hashes"] == spec["n_unique_frames"]
    assert len(spec["frame_sha256"]) == 4
    spec["positions"][1] = spec["positions"][0]
    with pytest.raises(SystemExit, match="byte-identical"):
        cross_format.require_distinct_frames(spec["positions"])


def test_tool_pins_are_full_commits():
    assert h2h15.MDC_COMMIT == "41b600313c1a8265dbaa639651ed0124610d1bbb"
    assert h2h15.MDC_TAG == "v2.0.5"
    assert h2h15.CF012_COMMIT == "fc1e93096b797ff4848dae57c03b7c9ef287cccd"
    assert h2h15.CF012_VERSION == "0.12.0-dev"


def test_the_runner_uses_the_shared_measurement_guard():
    from measured_commit import measurement, record_path

    assert h2h15.measurement is measurement
    assert h2h15.record_path is record_path


def test_record_text_drops_a_machine_prefix():
    import cross_format

    prefix = "/" + "tmp"
    raw = f"build {prefix}/venv/lib/python3.12/site-packages/chemfiles/frame.py:26(f)\n"
    cleaned = cross_format.record_text(raw)
    assert prefix not in cleaned
    assert "site-packages/chemfiles/frame.py:26(f)" in cleaned
    library = f"library {prefix}/chemfiles-install/lib/libchemfiles.so"
    assert prefix not in cross_format.record_text(library)


def test_a_record_with_a_machine_path_is_refused():
    with pytest.raises(SystemExit, match="machine path"):
        h2h15.assert_repo_relative_record('{"path": "' + "/" + "tmp" + '/x"}')
    h2h15.assert_repo_relative_record('{"record": "bench/h2h/scaling/h2h15"}')


def test_record_path_drops_the_repository_root():
    assert h2h15.record_path(h2h15.ROOT / "bench" / "h2h" / "h2h15.py", h2h15.ROOT) == (
        "bench/h2h/h2h15.py"
    )
    assert h2h15.record_path(Path("/usr"), h2h15.ROOT) == "usr"


def test_dcd_delta_reads_the_header_float():
    path = bench_file("h2h15-delta", suffix=".dcd")
    blob = bytearray(48)
    struct.pack_into("<f", blob, 44, 1.5)
    path.write_bytes(bytes(blob))
    try:
        assert h2h15.dcd_delta(path) == pytest.approx(1.5)
    finally:
        path.unlink()


def test_one_frame_mdcompress_rows_are_unsupported():
    row = h2h15._unsupported("1k", 1000, 1, "mdcompress-dcd", "write")
    assert row["n"] == 0
    assert row["median_s"] is None
    assert "one-frame" in row["loses"]
    assert row["op"] == "write"


def test_cf012_two_frame_dcd_writes_a_nonzero_delta():
    library = h2h15.chemfiles_012_library()
    if library is None:
        pytest.skip("chemfiles fc1e930 is not installed")
    import cross_format

    spec = cross_format.make_spec(4, 2)
    lib = h2h15.load_chemfiles(library)
    path = bench_file("h2h15-cf012", suffix=".dcd")
    try:
        h2h15.write_cf012(lib, path, h2h15.build_cf012_frames(lib, spec))
        assert h2h15.dcd_delta(path) != 0.0
        got = h2h15.read_cf012(lib, path)
        assert got["positions"].shape == (2, 4, 3)
    finally:
        path.unlink()
