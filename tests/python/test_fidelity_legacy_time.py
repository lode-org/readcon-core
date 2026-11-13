"""Legacy CON time labels stay the natural unit after a readcon rewrite."""

import sys
from pathlib import Path

import readcon

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bench" / "fidelity"))

import campaign  # noqa: E402


def test_to_ase_keeps_the_first_coordinate(tmp_path):
    src = campaign.fixture_path("tiny_multi_cuh2.convel")
    frame = readcon.read_con(str(src))[0]
    atoms = frame.to_ase()
    assert atoms.positions[0, 0] == frame.atoms[0].x


def test_legacy_natural_stamp_is_exact_when_the_label_was_not_authoritative():
    natural = campaign.NATURAL
    assert campaign._legacy_natural_stamp([natural], [natural], [natural])
    # A 3.1 file that named fs is authoritative. Replacing it is not a stamp.
    assert not campaign._legacy_natural_stamp([natural], ["fs"], [natural])


def test_readcon_round_trip_keeps_positions_and_the_natural_time_unit(tmp_path):
    flags = {
        "ids": True,
        "per_axis": True,
        "velocities": True,
        "unit": True,
        "id_cite": "",
        "mask_cite": "",
        "vel_cite": "",
        "unit_cite": "",
    }
    for name in ("claisen.con", "v30_fs_label.convel", "tiny_multi_cuh2.convel"):
        src = campaign.fixture_path(name)
        reference = campaign.read_readcon(src)
        dest = tmp_path / name
        readcon.write_con(str(dest), readcon.read_con(str(src)))
        written = campaign.read_readcon(dest)
        rows = {
            row["field"]: row
            for row in campaign.compare_frames(
                reference, written, campaign.TOL["readcon"], **flags
            )
        }
        assert rows["positions"]["reader"] == "exact", (name, rows["positions"])
        if rows["velocities"]["reader"] != "absent":
            assert rows["velocities"]["reader"] == "exact", (name, rows["velocities"])
            assert rows["velocity_unit"]["reader"] == "exact", (
                name,
                rows["velocity_unit"],
            )
