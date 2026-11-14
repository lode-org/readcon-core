# Copyright (c) readcon-core developers
"""The h2h15 harness keeps the two chemfiles rows apart and names its parent."""

from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bench" / "h2h"))

import h2h15
from bench_disk import bench_file


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


def test_parent_and_tool_pins_are_full_commits():
    assert h2h15.PARENT == "0b62d689367cf69797107ca505778fde1017990d"
    assert h2h15.MDC_COMMIT == "41b600313c1a8265dbaa639651ed0124610d1bbb"
    assert h2h15.MDC_TAG == "v2.0.5"
    assert h2h15.CF012_COMMIT == "fc1e93096b797ff4848dae57c03b7c9ef287cccd"
    assert h2h15.CF012_VERSION == "0.12.0-dev"
    assert len(h2h15.diff_sha256()) == 64


def test_a_dirty_index_is_refused():
    with pytest.raises(SystemExit, match="dirty"):
        h2h15.refuse_if_dirty(" M bench/h2h/h2h15.py")
    h2h15.refuse_if_dirty("")
    h2h15.refuse_if_dirty("   \n")


def test_a_record_with_a_machine_path_is_refused():
    with pytest.raises(SystemExit, match="machine path"):
        h2h15.assert_repo_relative_record('{"path": "' + "/" + "tmp" + '/x"}')
    h2h15.assert_repo_relative_record('{"record": "bench/h2h/scaling/h2h15"}')


def test_repo_relative_drops_the_repository_root():
    assert h2h15.repo_relative(h2h15.ROOT / "bench" / "h2h" / "h2h15.py") == (
        "bench/h2h/h2h15.py"
    )
    with pytest.raises(SystemExit, match="outside"):
        h2h15.repo_relative(Path("/usr"))


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
