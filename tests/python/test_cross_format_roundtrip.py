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
    expected = {arm["id"] for arm in cross_format.arm_table(4)[0]}
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


def test_pdb_above_serial_is_reported() -> None:
    arms, _notes = cross_format.arm_table(100_000)
    pdb = [arm for arm in arms if arm["id"] == "mda-pdb"]
    if not pdb:
        return
    assert pdb[0]["unsupported"] is True
    assert "five digits" in pdb[0]["drops"]
