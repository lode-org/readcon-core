"""Each native file round-trips to the same positions and cell.

The tolerance is the format's own precision (PDB's 1e-3 Å, XTC's 1e-2 Å,
float32 trajectories, text CON and extended XYZ). A format that cannot
hold the structure is skipped with a reason, not given a fake pass.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bench" / "h2h"))

import cross_format


def test_cross_format_roundtrip(tmp_path: Path) -> None:
    rows, notes = cross_format.roundtrip_report(tmp_path, n_atoms=4, n_frames=2)
    assert any("no native CON format" in note for note in notes)
    expected = {
        arm["id"] for arm in cross_format.arm_table(4)[0] if not arm.get("one_model")
    }
    missing = expected - {row["arm"] for row in rows}
    assert not missing, (sorted(missing), notes)
    for row in rows:
        assert row["position_error"] <= row["precision"], row
        loses = set() if row["loses"] == "none" else set(row["loses"].split(","))
        if "cell" not in loses:
            assert row["cell_error"] <= row["precision"], row
        assert row["file_bytes"] > 0


def test_readcon_chemfiles_roundtrip_without_the_python_package(tmp_path, monkeypatch):
    import builtins

    import readcon

    if not readcon.has_chemfiles_support():
        return
    real_import = builtins.__import__

    def guarded(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "chemfiles" or name.startswith("chemfiles."):
            raise ImportError("chemfiles is not installed")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded)
    rows, notes = cross_format.roundtrip_report(tmp_path, n_atoms=4, n_frames=2)
    matched = [row for row in rows if row["arm"] == "readcon-chemfiles"]
    assert matched, notes
    row = matched[0]
    assert row["position_error"] <= row["precision"], row


def test_a_written_file_round_trips_the_atom_count(tmp_path: Path) -> None:
    spec = cross_format.make_spec(4, 2)
    path = tmp_path / "round.con"
    cross_format.write_readcon(path, spec, None)
    cross_format.expect_written_roundtrip("readcon-con", path, 4, 2)
    empty = tmp_path / "empty.con"
    empty.write_bytes(b"")
    try:
        cross_format.expect_written_roundtrip("readcon-con", empty, 4, 2)
    except SystemExit as exc:
        assert "0 bytes" in str(exc)
        return
    raise AssertionError("an empty write was accepted")


def test_a_stub_file_is_not_a_million_atom_write() -> None:
    try:
        cross_format.expect_file_bytes("chemfiles-xyz", 1_000_000, 1, 10)
    except SystemExit as exc:
        assert "10 bytes" in str(exc)
        return
    raise AssertionError("a 10-byte file was accepted")


def test_chemfiles_con_has_no_writer() -> None:
    pytest.importorskip(
        "chemfiles",
        reason="the chemfiles Python package is not installed",
    )
    import readcon

    if not readcon.has_chemfiles_support():
        pytest.skip(
            "this readcon build does not link chemfiles, so the chemfiles-con arm is not offered"
        )
    arms, _notes = cross_format.arm_table(8)
    row = next(arm for arm in arms if arm["id"] == "chemfiles-con")
    assert row["no_writer"] is True
    assert "no CON format" in row["notes"]


def test_a_fresh_process_finds_the_mdcompress_reader(tmp_path: Path) -> None:
    if cross_format._mdcompress_tools() is None:
        return
    spec = cross_format.make_spec(4, 2)
    path = cross_format.convert_arm("mdcompress-mdc", spec, tmp_path)
    root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("MDCOMPRESS_PYTHON", None)
    code = (
        "import sys\n"
        "from pathlib import Path\n"
        f"sys.path.insert(0, {str(root / 'bench' / 'h2h')!r})\n"
        "import cross_format\n"
        f"got = cross_format.read_mdcompress({str(path)!r})\n"
        "assert got['positions'].shape == (2, 4, 3), got['positions'].shape\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True, env=env, cwd=root)


def test_every_arm_names_the_write_clock() -> None:
    arms, _notes = cross_format.arm_table(1000)
    assert arms
    for arm in arms:
        assert arm["notes"].startswith("Clock: ") or " Clock: " in f" {arm['notes']}"
        assert cross_format.write_clock(arm["id"]) in arm["notes"]


def test_mmcif_reader_is_one_model(tmp_path: Path) -> None:
    arms, notes = cross_format.arm_table(4)
    row = next((arm for arm in arms if arm["id"] == "mda-mmcif"), None)
    if row is None:
        assert any(
            "mda-mmcif omitted" in note or "MDAnalysis is not installed" in note
            for note in notes
        )
        return
    assert row["one_model"] is True
    assert row["no_writer"] is True
    spec = cross_format.make_spec(4, 1)
    path = cross_format.convert_arm("mda-mmcif", spec, tmp_path)
    got = cross_format.read_arm("mda-mmcif", os.fspath(path))
    checked = cross_format.audit(spec, got, row["precision"])
    assert checked["position_error"] <= row["precision"], checked


def test_extxyz_ng_reads_the_same_extended_xyz(tmp_path: Path) -> None:
    arms, notes = cross_format.arm_table(4)
    row = next((arm for arm in arms if arm["id"] == "extxyz-ng"), None)
    if row is None:
        assert any("extxyz-ng 0.0.2 was not added" in note for note in notes)
        return
    assert row["no_writer"] is True
    spec = cross_format.make_spec(4, 2)
    path = cross_format.convert_arm("extxyz-ng", spec, tmp_path)
    got = cross_format.read_arm("extxyz-ng", os.fspath(path))
    checked = cross_format.audit(spec, got, row["precision"])
    assert checked["position_error"] <= row["precision"], checked


def _stub_campaign(monkeypatch, seen: list[int]) -> None:
    ident = {
        "commit": "a" * 40,
        "tree": "b" * 40,
        "diff_sha256": "0" * 64,
        "remote": "refs/heads/feat/release-0.23.0",
    }
    monkeypatch.setattr(cross_format, "refuse_stale_build", lambda _root: ident)
    monkeypatch.setattr(cross_format, "serial_threads", lambda: None)
    monkeypatch.setattr(cross_format, "pin_cores", lambda: None)
    monkeypatch.setattr(
        cross_format,
        "campaign_host",
        lambda _out, tree: {
            "loadavg": "0.1 0.1 0.1 1/1 1",
            "governor": {"0": "performance"},
            "cpu_mhz": 1000.0,
            "cpu_model": "Test",
            "lscpu": "Model name: Test\n",
            "bench_disk": "build/bench",
            "bench_disk_filesystem": "ext2/ext3",
            "work": "bench/h2h/work",
            "work_filesystem": "ext2/ext3",
            "record": "bench/out",
            "record_filesystem": "ext2/ext3",
            "tree": tree,
        },
    )
    release = (
        (Path(__file__).resolve().parents[2] / "VERSION")
        .read_text(encoding="utf-8")
        .strip()
    )
    monkeypatch.setattr(cross_format, "library_versions", lambda: {"readcon": release})
    monkeypatch.setattr(
        cross_format,
        "ovito_extxyz_periodicity_and_drift",
        lambda: {
            "pbc_matches": True,
            "wrapped_into_cell": False,
            "stuck_on_frame0": False,
            "drift_max_abs": 0.0,
        },
    )
    monkeypatch.setattr(cross_format, "core_list", lambda: "0")
    monkeypatch.setattr(
        cross_format,
        "make_spec",
        lambda n_atoms, n_frames: {
            "n_atoms": n_atoms,
            "n_frames": n_frames,
            "n_unique_frames": n_frames,
            "unique_frame_hashes": n_frames,
            "frame_sha256": ["ab"],
        },
    )
    monkeypatch.setattr(cross_format, "save_spec", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cross_format, "arm_table", lambda _n: ([], []))

    def record(arms, repeats, *_args, **_kwargs):
        seen.append(repeats)
        return {
            "samples": {arm["id"]: [] for arm in arms},
            "rss": {arm["id"]: [] for arm in arms},
            "checksums": {arm["id"]: [] for arm in arms},
        }

    monkeypatch.setattr(cross_format, "_interleave", record)


def test_omitted_repeats_use_the_size_count(monkeypatch, tmp_path: Path) -> None:
    seen: list[int] = []
    _stub_campaign(monkeypatch, seen)
    cross_format.run(
        tmp_path, None, structures=[("1k", 8, 1), ("1M", 8, 1)], ops=("write",)
    )
    assert seen == [12, 6]
    note = (tmp_path / "cross-format.log").read_text(encoding="utf-8")
    assert "6 at 1M" in note


def test_given_repeats_apply_to_every_structure(monkeypatch, tmp_path: Path) -> None:
    seen: list[int] = []
    _stub_campaign(monkeypatch, seen)
    cross_format.run(
        tmp_path, 4, structures=[("1k", 8, 1), ("1M", 8, 1)], ops=("write",)
    )
    assert seen == [4, 4]
    note = (tmp_path / "cross-format.log").read_text(encoding="utf-8")
    assert "6 at 1M" not in note
    assert "4 for every structure" in note


def test_repeats_follow_the_structure_size() -> None:
    assert cross_format.repeats_for("1k") == 12
    assert cross_format.repeats_for("100k") == 12
    assert cross_format.repeats_for("traj") == 12
    assert cross_format.repeats_for("1M") == 6
    assert cross_format.sample_count("1M", None) == 6
    assert cross_format.sample_count("1k", 3) == 3
    with pytest.raises(SystemExit, match="positive"):
        cross_format.sample_count("1k", 0)


def test_a_finished_sample_is_appended(tmp_path: Path) -> None:
    cross_format.append_arm_row(
        tmp_path,
        "1k",
        "readcon-con",
        "read-warm",
        "0",
        "0.010000",
        "100",
        "200",
        "forces,energies",
    )
    cross_format.append_arm_row(
        tmp_path,
        "1k",
        "readcon-con",
        "read-warm",
        "1",
        "0.020000",
        "110",
        "200",
        "forces,energies",
    )
    text = (tmp_path / "by-arm" / "1k" / "readcon-con.tsv").read_text(encoding="utf-8")
    assert text.startswith("op\tsample\twall_s\trss_bytes\tfile_bytes\tdrops\n")
    assert text.count("\n") == 3
    assert "0.020000" in text


def test_a_shard_with_samples_is_not_deleted(tmp_path: Path) -> None:
    cross_format.append_arm_row(
        tmp_path,
        "1k",
        "readcon-con",
        "read-warm",
        "0",
        "0.010000",
        "100",
        "200",
        "none",
    )
    shard = tmp_path / "by-arm" / "1k"
    with pytest.raises(SystemExit, match="recorded samples"):
        cross_format.refuse_recorded_shard(shard)
    assert (shard / "readcon-con.tsv").is_file()


def test_missing_rss_is_blank_not_zero() -> None:
    assert cross_format.recorded_rss({}) == ""
    assert cross_format.recorded_rss({"rss_bytes": None}) == ""
    assert cross_format.recorded_rss({"rss_bytes": 0}) == "0"
    assert cross_format.recorded_rss({"rss_bytes": 12}) == "12"


def test_a_reader_crash_is_not_an_unsupported_format() -> None:
    assert cross_format.capacity_limit("readcon-con", RuntimeError("boom")) is None
    assert cross_format.capacity_limit("ase-extxyz", ValueError("parse")) is None


def test_a_precision_miss_fails_the_run() -> None:
    with pytest.raises(SystemExit, match="round-trip failure"):
        cross_format.reject_round_trip("readcon-con", 1.0, 0.0, 1e-5)


def test_extxyz_ng_oserror_stores_the_actual_message() -> None:
    reason = cross_format.unsupported_reason(
        "extxyz-ng", OSError("frame of 256 atoms past the 128 limit")
    )
    assert reason.startswith("unsupported:")
    assert "OSError" in reason
    # The stored reason is the exception this run saw, not a fixed string.
    assert "frame of 256 atoms past the 128 limit" in reason


def test_fresh_reads_returns_and_records_its_samples(tmp_path, monkeypatch) -> None:
    calls = {"n": 0}

    def fake(_script, _job):
        calls["n"] += 1
        return {"wall_s": 0.01 * calls["n"], "rss_bytes": 7, "checksum": 1.0}

    monkeypatch.setattr(cross_format, "spawn_worker", fake)
    plain = tmp_path / "readcon.con"
    plain.write_bytes(b"x" * 64)
    samples = cross_format._fresh_reads(
        tmp_path, plain, 1, 6, "1M", "readcon-con-fresh-serial"
    )
    # The output carries one value per requested sample.
    assert len(samples) == 6
    # One warmup read, then the six recorded samples.
    assert calls["n"] == 7
    tsv = tmp_path / "by-arm" / "1M" / "readcon-con-fresh-serial.tsv"
    text = tsv.read_text(encoding="utf-8")
    assert text.startswith("op\tsample\twall_s\trss_bytes\tfile_bytes\tdrops\n")
    # header plus six sample lines
    assert text.count("\n") == 7
    for sample in samples:
        assert f"{sample:.6f}" in text


def test_interleave_keeps_one_sample_count(tmp_path: Path, monkeypatch) -> None:
    calls = {"n": 0}

    def fake(_script, _job):
        calls["n"] += 1
        wall = 1.0 if calls["n"] % 2 else 50.0
        return {"wall_s": wall, "rss_bytes": 4, "checksum": 1.0}

    monkeypatch.setattr(cross_format, "spawn_worker", fake)
    arms = [
        {"id": "a", "job": {"path": "x"}},
        {"id": "b", "job": {"path": "y"}},
    ]
    found = cross_format._interleave(
        arms,
        6,
        [],
        "read-warm 1M",
        out=tmp_path,
        structure="1M",
        op="read-warm",
        drops={"a": "none", "b": "none"},
    )
    assert len(found["samples"]["a"]) == 6
    assert len(found["samples"]["b"]) == 6
    assert calls["n"] == 12
    text = (tmp_path / "by-arm" / "1M" / "a.tsv").read_text(encoding="utf-8")
    assert text.count("\n") == 7


def test_an_unsupported_row_is_stored(tmp_path: Path) -> None:
    pytest.importorskip("MDAnalysis")
    arms, _notes = cross_format.arm_table(100_000)
    pdb = next(arm for arm in arms if arm["id"] == "mda-pdb")
    rows: list[dict] = []
    lines: list[str] = []
    cross_format.record_unsupported(
        tmp_path, rows, lines, "100k", 100_000, 1, pdb, pdb["drops"]
    )
    assert rows[0]["cache"] == "unsupported"
    assert str(rows[0]["loses"]).startswith("unsupported:")
    stored = (tmp_path / "by-arm" / "100k" / "mda-pdb.tsv").read_text(encoding="utf-8")
    assert "unsupported:" in stored


def test_pdb_above_serial_is_reported() -> None:
    pytest.importorskip("MDAnalysis")
    arms, _notes = cross_format.arm_table(100_000)
    pdb = [arm for arm in arms if arm["id"] == "mda-pdb"]
    if not pdb:
        return
    assert pdb[0]["unsupported"] is True
    assert "five digits" in pdb[0]["drops"]


def test_required_arms_are_offered() -> None:
    required = [
        name for name in os.environ.get("READCON_REQUIRE_ARMS", "").split(",") if name
    ]
    if not required:
        pytest.skip("READCON_REQUIRE_ARMS is not set")
    arms, notes = cross_format.arm_table(4)
    missing = sorted(set(required) - {arm["id"] for arm in arms})
    assert not missing, (missing, notes)
